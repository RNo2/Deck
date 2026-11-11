from types import SimpleNamespace
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from atlas import main
from atlas.storage import init_db, persist, current_rows, Observation
from atlas.providers import WorldBank, ECB, point
from atlas.analysis import analyze

@pytest.fixture
def client(tmp_path, monkeypatch):
 monkeypatch.setattr(main,'Session',init_db(f'sqlite:///{tmp_path}/test.db'))
 with TestClient(main.app,headers={"X-ATLAS-CSRF":"1"}) as c:
  response=c.post('/auth/login',data={"username":"tester","password":"test-password-long"},headers={"Origin":"http://127.0.0.1:5173"},follow_redirects=False)
  assert response.status_code==303
  yield c

def payload(**overrides):
 return dict(name='Test research',source_url='https://example.org/observations',unit='index',geography='Test',frequency='monthly',csv_text='date,value\n2020-01-01,1\n2020-02-01,2\n',**overrides)

def test_import_is_atomic_deduplicated_and_exportable(client):
 body=payload()
 assert client.post('/api/import',json=body).json()['added']==2
 assert client.post('/api/import',json=body).json()['added']==0
 detail=client.get('/api/series/csv:Test research').json()
 assert len(detail['observations'])==2
 assert detail['analysis']['status']=='insufficient evidence'
 assert detail['observations'][0]['publication_date'] is None
 assert 'source_url' in client.get('/api/export',params={'series_id':'csv:Test research'}).text
 body['csv_text']='date,value\n2020-01-01,3\n2020-02-01,nan\n'
 assert client.post('/api/import',json=body).status_code==422
 assert client.get('/api/series/csv:Test research').json()['observations'][0]['value']==1

@pytest.mark.parametrize('csv_text',['date,value\n2020-01-01,1\n2020-01-01,2','date,value\n2099-01-01,3','date,value\n2020-02-30,2','date,value\n2020-01-01,inf','date,wrong\n2020-01-01,1'])
def test_invalid_imports_rejected(client,csv_text):
 body=payload();body['csv_text']=csv_text
 assert client.post('/api/import',json=body).status_code==422
 assert all(c['observations']==0 for c in client.get('/api/coverage').json())

def test_revisions_retained_not_double_counted(client):
 body=payload();client.post('/api/import',json=body)
 body['csv_text']='date,value\n2020-01-01,9\n'
 assert client.post('/api/import',json=body).json()['added']==1
 with main.Session() as s:
  assert len(s.scalars(select(Observation)).all())==3
  assert len(current_rows(s,'csv:Test research'))==2
  assert current_rows(s,'csv:Test research')[0].value==9

def test_watchlists_and_no_fake_discoveries(client):
 assert client.get('/api/discovery').json()==[]
 assert client.get('/api/health').status_code==200
 assert len(client.get('/api/catalog').json())==32
 assert client.post('/api/watchlists',json={'name':'x','series_ids':['unknown']}).status_code==422
 result=client.post('/api/watchlists',json={'name':'Macro','series_ids':['ecb:USD']}).json()
 assert client.get('/api/watchlists').json()[0]['name']=='Macro'
 assert client.delete('/api/watchlists/'+str(result['id'])).status_code==200
 assert client.get('/api/watchlists').json()==[]

def test_zscore_excludes_latest_and_no_direction_claim():
 rows=[SimpleNamespace(value=float(i),date=f'2020-{i+1:02d}-01') for i in range(10)]
 rows.append(SimpleNamespace(value=100.,date='2020-11-01'))
 result=analyze(rows,'monthly')
 assert result['baseline_mean']==4.5
 assert result['baseline_sample']==10
 assert result['z_score']>30
 assert result['components']['corroboration']==0
 assert result['priority']<=80
 assert result['direction']=='uncertain'
 assert result['slope_95_ci'][0]==pytest.approx(1)

def test_constant_history_has_no_infinite_signal():
 rows=[SimpleNamespace(value=1.,date=str(i)) for i in range(30)]
 assert analyze(rows,'daily')['z_score'] is None
 assert analyze(rows,'daily')['slope_p_value'] is None

def test_worldbank_normalizes_nulls_and_provenance():
 def handler(request):
  return httpx.Response(200,json=[{'page':1},[{'date':'2020','value':4.2},{'date':'2019','value':None}]])
 async def run():
  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
   rows=await WorldBank(c).fetch('wb:BRA:FP.CPI.TOTL.ZG')
   assert len(rows)==1
   assert rows[0]['date']=='2020-12-31'
   assert rows[0]['unit']=='% annual'
   assert rows[0]['publication_date'] is None
 asyncio.run(run())

def test_ecb_normalizes_reference_rate():
 async def run():
  async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='TIME_PERIOD,OBS_VALUE\n2020-01-02,1.12\n'))) as c:
   rows=await ECB(c).fetch('ecb:USD')
   assert rows[0]['value']==1.12
   assert rows[0]['currency']=='USD'
 asyncio.run(run())

def test_refresh_access_denial_visible_and_cooldown(client,monkeypatch):
 async def denied(self,sid):
  req=httpx.Request('GET','https://example.org')
  raise httpx.HTTPStatusError('blocked',request=req,response=httpx.Response(403,request=req))
 monkeypatch.setattr(WorldBank,'fetch',denied);monkeypatch.setattr(ECB,'fetch',denied)
 result=client.post('/api/refresh')
 assert result.status_code==202
 import time
 for _ in range(100):
  status=client.get('/api/refresh').json()
  if status['status'] not in ('queued','running'):break
  time.sleep(.02)
 assert status['status']=='failed'
 assert all(p['status']=='unavailable' for p in client.get('/api/coverage').json() if p['id']!='csv')
 assert client.get('/api/discovery').json()==[]
 assert client.post('/api/refresh').status_code==429
