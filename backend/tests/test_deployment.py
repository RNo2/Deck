import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from atlas import main
from atlas.auth import COOKIE, digest, settings
from atlas.storage import init_db, make_engine, database_url, LoginSession, Observation
from atlas.migrate import upgrade

@pytest.fixture
def private_client(tmp_path,monkeypatch):
 monkeypatch.setattr(main,'Session',init_db(f'sqlite:///{tmp_path}/auth.db'))
 with TestClient(main.app) as c: yield c

def login(c,**options):
 return c.post('/auth/login',data={'username':'tester','password':'test-password-long'},headers={'Origin':'http://127.0.0.1:5173'},follow_redirects=False,**options)

def test_auth_protects_data_and_docs(private_client):
 c=private_client
 for path in ['/api/catalog','/api/series/ecb:USD','/api/coverage','/api/report?series_id=ecb:USD','/api/export?series_id=ecb:USD']:
  assert c.get(path).status_code==401
 assert c.get('/docs',follow_redirects=False).status_code==303
 assert c.get('/api/health').status_code==200
 assert c.get('/auth/login').status_code==200
 assert login(c).status_code==303
 assert c.get('/api/catalog').status_code==200
 docs=c.get('/docs')
 assert docs.status_code==200 and 'script nonce=' in docs.text
 assert 'requestInterceptor' in docs.text
 assert 'https://cdn.jsdelivr.net' in docs.headers['content-security-policy']
 assert 'no-store' in c.get('/api/catalog').headers['cache-control']
 assert 'frame-ancestors' in c.get('/api/catalog').headers['content-security-policy']


def test_csrf_origin_and_logout(private_client):
 c=private_client
 assert c.post('/auth/login',data={}).status_code==403
 assert login(c).status_code==303
 assert c.post('/api/watchlists',json={'name':'x','series_ids':[]}).status_code==403
 assert c.post('/api/watchlists',headers={'X-ATLAS-CSRF':'1','Origin':'https://evil.example'},json={'name':'x','series_ids':[]}).status_code==403
 assert c.post('/api/watchlists',headers={'X-ATLAS-CSRF':'1'},json={'name':'x','series_ids':[]}).status_code==200
 token=c.cookies.get(COOKIE)
 assert c.post('/auth/logout',headers={'X-ATLAS-CSRF':'1'}).status_code==200
 c.cookies.set(COOKIE,token)
 assert c.get('/api/catalog').status_code==401


def test_rotation_expiry_and_hash_only_storage(private_client,monkeypatch):
 c=private_client;login(c);old=c.cookies.get(COOKIE)
 result=login(c);new=c.cookies.get(COOKIE)
 assert old!=new
 cookie=result.headers['set-cookie'].lower()
 assert 'httponly' in cookie and 'samesite=strict' in cookie
 with main.Session() as s:
  assert s.get(LoginSession,digest(old)) is None
  record=s.get(LoginSession,digest(new))
  assert record and record.token_hash!=new
 # New client demonstrates persistence across browser connections.
 with TestClient(main.app) as another:
  another.cookies.set(COOKIE,new)
  assert another.get('/api/catalog').status_code==200
 monkeypatch.setenv('ATLAS_USERNAME','changed-user')
 assert c.get('/api/catalog').status_code==401
 monkeypatch.setenv('ATLAS_USERNAME','tester')
 with main.Session() as s:
  s.get(LoginSession,digest(new)).expires=int(time.time())-1;s.commit()
 assert c.get('/api/catalog').status_code==401


def test_bad_credentials_throttled(private_client):
 c=private_client
 for _ in range(5):
  assert c.post('/auth/login',data={'username':'tester','password':'wrong'},headers={'Origin':'http://127.0.0.1:5173'}).status_code==401
 assert login(c).status_code==429


def test_configuration_fails_closed(monkeypatch):
 monkeypatch.delenv('ATLAS_PASSWORD_HASH')
 with pytest.raises(RuntimeError): settings()
 monkeypatch.setenv('ATLAS_ENV','production')
 with pytest.raises(RuntimeError): settings()


def test_database_url_driver_and_tls(monkeypatch):
 assert database_url('postgres://u:p@localhost/db').startswith('postgresql+psycopg://')
 assert database_url('postgresql://u:p@localhost/db').startswith('postgresql+psycopg://')
 engine=make_engine('postgresql://u:p@localhost/db?sslmode=verify-full')
 assert engine.dialect.name=='postgresql'
 assert engine.dialect.driver=='psycopg'
 engine.dispose()
 monkeypatch.setenv('ATLAS_ENV','production')
 with pytest.raises(RuntimeError): make_engine('postgresql://u:p@localhost/db')


def test_migrations_preserve_legacy_data_and_repeat(tmp_path):
 engine=make_engine(f'sqlite:///{tmp_path}/legacy.db')
 # Emulate the original unversioned schema.
 Observation.__table__.create(engine)
 with engine.begin() as c:
  c.execute(Observation.__table__.insert().values(series_id='legacy',date='2020-01-01',value=3.2,retrieved_at='original-timestamp',source_url='https://example.org',provider='csv',unit='index',frequency='annual',geography='Global',revision_status='original',publication_date='2020-02-01',currency=None))
 upgrade(engine);upgrade(engine)
 with engine.connect() as c:
  row=c.execute(select(Observation.__table__)).mappings().one()
  assert row['retrieved_at']=='original-timestamp'
  assert row['publication_date']=='2020-02-01'
  assert row['value']==3.2
  assert c.scalar(text('select version_num from alembic_version'))=='0003'


def test_transfer_preserves_all_vintages_and_refuses_overwrite(tmp_path):
 from atlas.transfer import transfer
 from atlas.providers import point
 from atlas.storage import persist
 source=f'sqlite:///{tmp_path}/source.db';target=f'sqlite:///{tmp_path}/target.db'
 factory=init_db(source)
 with factory() as s:
  a=point('csv:test','2020-01-01',1,'https://example.org','csv','index','annual','Global')
  persist(s,[a]);a=dict(a,value=2,retrieved_at='later-retrieval');persist(s,[a])
 assert transfer(source,target)['observations']==2
 factory=init_db(target)
 with factory() as s:
  rows=s.scalars(select(Observation).order_by(Observation.id)).all()
  assert [r.value for r in rows]==[1,2]
  assert rows[0].source_url=='https://example.org'
  assert rows[1].retrieved_at=='later-retrieval'
 with pytest.raises(RuntimeError):transfer(source,target)


@pytest.mark.skipif(not __import__('os').environ.get('ATLAS_TEST_DATABASE_URL'),reason='Disposable PostgreSQL not configured')
def test_postgresql_migrations_transfer_and_authenticated_api(tmp_path,monkeypatch):
 import os
 from atlas.transfer import transfer
 from atlas.providers import point
 from atlas.storage import persist, current_rows
 target=os.environ['ATLAS_TEST_DATABASE_URL']
 source=f'sqlite:///{tmp_path}/postgres-source.db'
 factory=init_db(source)
 with factory() as s:
  original=point('csv:postgres-test','2020-01-01',5,'https://example.org','csv','index','annual','Global')
  persist(s,[original])
 assert transfer(source,target)['observations']==1
 factory=init_db(target)
 monkeypatch.setattr(main,'Session',factory)
 with TestClient(main.app,headers={'X-ATLAS-CSRF':'1'}) as c:
  assert login(c).status_code==303
  assert c.get('/api/series/csv:postgres-test').json()['observations'][0]['retrieved_at']==original['retrieved_at']
  body={'name':'postgres-test','source_url':'https://example.org','unit':'index','geography':'Global','frequency':'annual','csv_text':'date,value\n2021-01-01,6\n'}
  assert c.post('/api/import',json=body).json()['added']==1
  assert c.post('/api/import',json=body).json()['added']==0
  with factory() as s:
   assert len(current_rows(s,'csv:postgres-test'))==2
  w=c.post('/api/watchlists',json={'name':'Persistent','series_ids':['csv:postgres-test']}).json()
  assert c.get('/api/watchlists').json()[0]['id']==w['id']
  assert c.get('/api/report?series_id=csv:postgres-test').status_code==200
 # Exercise durable ingestion against PostgreSQL, using controlled provider data.
  from atlas import ingestion as ingestion_module
  from atlas.catalog import catalog
  class Provider:
   def __init__(self,client):pass
   async def fetch(self,sid):
    item=next(i for i in catalog() if i['id']==sid)
    host='api.worldbank.org' if item['provider']=='worldbank' else 'data-api.ecb.europa.eu'
    return [point(sid,'2020-01-01',2,'https://'+host+'/source',item['provider'],item['unit'],item['frequency'],item['country'])]
  monkeypatch.setattr(ingestion_module,'PROVIDERS',{'worldbank':Provider,'ecb':Provider})
  assert c.post('/api/refresh',json={'series_ids':['ecb:USD','wb:BRA:FP.CPI.TOTL.ZG']}).status_code==202
  for _ in range(100):
   job=c.get('/api/refresh').json()
   if job['status'] not in ('queued','running'):break
   time.sleep(.02)
  assert job['status']=='succeeded' and job['added']==2
 token=c.cookies.get(COOKIE)
 # Reinitialize the engine as a process restart would; data and sessions must remain.
 factory=init_db(target)
 with factory() as s:assert len(current_rows(s,'csv:postgres-test'))==2
 monkeypatch.setattr(main,'Session',factory)
 with TestClient(main.app) as restarted:
  restarted.cookies.set(COOKIE,token)
  assert restarted.get('/api/catalog').status_code==200


def test_https_secure_cookie(private_client,monkeypatch):
 monkeypatch.setenv('APP_ORIGIN','https://atlas.example')
 with TestClient(main.app,base_url='https://atlas.example') as c:
  r=c.post('/auth/login',data={'username':'tester','password':'test-password-long'},headers={'Origin':'https://atlas.example'},follow_redirects=False)
  assert r.status_code==303
  assert 'secure' in r.headers['set-cookie'].lower()
  assert c.get('/api/catalog').status_code==200
  assert 'Strict-Transport-Security' in r.headers
