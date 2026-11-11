import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from atlas import main, ingestion
from atlas.storage import init_db, IngestionJob, ProviderRun, Observation, persist
from atlas.providers import point, request
from atlas.catalog import catalog

SID='wb:BRA:FP.CPI.TOTL.ZG'
FX='ecb:USD'


def points(sid,value=2):
    item=next(i for i in catalog() if i['id']==sid)
    host='api.worldbank.org' if item['provider']=='worldbank' else 'data-api.ecb.europa.eu'
    return [point(sid,'2020-01-01',value,'https://'+host+'/source',item['provider'],item['unit'],item['frequency'],item['country'])]


class Success:
    def __init__(self,client): pass
    async def fetch(self,sid): return points(sid)


@pytest.fixture
def factory(tmp_path): return init_db(f'sqlite:///{tmp_path}/ingestion.db')


@pytest.fixture
def web(factory,monkeypatch):
    monkeypatch.setattr(main,'Session',factory)
    monkeypatch.setattr(ingestion,'PROVIDERS',{'worldbank':Success,'ecb':Success})
    with TestClient(main.app,headers={'X-ATLAS-CSRF':'1'}) as c:
        assert c.post('/auth/login',data={'username':'tester','password':'test-password-long'},headers={'Origin':'http://127.0.0.1:5173'},follow_redirects=False).status_code==303
        yield c


def finish(client):
    for _ in range(200):
        state=client.get('/api/refresh').json()
        if state['status'] not in ingestion.ACTIVE:return state
        time.sleep(.01)
    pytest.fail('Refresh did not finish')


def test_background_progress_attribution_and_revision_retention(web,factory):
    with factory() as s:persist(s,points(SID,1))
    response=web.post('/api/refresh',json={'series_ids':[SID,FX]})
    assert response.status_code==202
    assert response.json()['total']==2
    state=finish(web)
    assert state['status']=='succeeded' and state['completed']==2 and state['added']==2
    coverage={i['id']:i for i in web.get('/api/coverage').json()}
    assert coverage['worldbank']['status']=='available'
    with factory() as s:
        rows=s.scalars(select(Observation).where(Observation.series_id==SID)).all()
        assert len(rows)==2 and {r.value for r in rows}=={1,2}
        assert all(r.retrieved_at and r.source_url=='https://api.worldbank.org/source' for r in rows)
        job=s.get(IngestionJob,1);job.started_at=0;s.commit()
    assert web.post('/api/refresh',json={'series_ids':[SID,FX]}).status_code==202
    assert finish(web)['added']==0
    assert web.post('/api/refresh').status_code==429
    assert int(web.post('/api/refresh').headers['Retry-After'])>0


def test_slow_provider_does_not_block_api_or_other_provider(web,monkeypatch):
    class Slow(Success):
        async def fetch(self,sid):
            await asyncio.sleep(10)
            return points(sid)
    monkeypatch.setitem(ingestion.PROVIDERS,'worldbank',Slow)
    monkeypatch.setattr(ingestion,'SERIES_SECONDS',.4)
    started=time.monotonic()
    first=web.post('/api/refresh',json={'series_ids':[SID,FX]}).json()
    assert time.monotonic()-started<1
    assert web.get('/api/health').status_code==200
    second=web.post('/api/refresh').json()
    assert second['job_id']==first['job_id']
    state=finish(web)
    assert state['status']=='partial'
    results={i['id']:i for i in state['series']}
    assert results[SID]['error']=='timeout' and results[FX]['status']=='succeeded'


def test_access_denial_short_circuits_only_affected_provider(web,monkeypatch):
    calls=[]
    class Denied(Success):
        async def fetch(self,sid):
            calls.append(sid)
            r=httpx.Response(403,request=httpx.Request('GET','https://api.worldbank.org/private-token'))
            raise httpx.HTTPStatusError('secret exception detail',request=r.request,response=r)
    monkeypatch.setitem(ingestion.PROVIDERS,'worldbank',Denied)
    web.post('/api/refresh')
    state=finish(web)
    assert state['status']=='partial' and len(calls)==1
    assert sum(i['status']=='skipped' for i in state['series'])==23
    assert sum(i['status']=='succeeded' for i in state['series'])==8
    assert 'secret' not in json.dumps(state) and 'private-token' not in json.dumps(state)


def test_entire_run_budget_and_restart_recovery(factory,monkeypatch):
    class Hung(Success):
        async def fetch(self,sid):await asyncio.sleep(10)
    monkeypatch.setattr(ingestion,'PROVIDERS',{'worldbank':Hung,'ecb':Hung})
    monkeypatch.setattr(ingestion,'RUN_SECONDS',.15)
    async def run():
        service=ingestion.IngestionService(lambda:factory)
        await service.start([SID,FX])
        await asyncio.wait_for(service.task,1)
        state=await service.status()
        assert state['status'] in ('failed','interrupted')
        assert all(i['status'] not in ingestion.ACTIVE for i in state['series'])
        # Simulate a process disappearing before finishing its durable job.
        with factory() as s:
            job=s.get(IngestionJob,1);job.status='running';job.deadline=time.time()+100
            payload=json.loads(job.payload);payload['series'][0]['status']='running';job.payload=json.dumps(payload);s.commit()
        recovered=ingestion.IngestionService(lambda:factory)
        await recovered.recover()
        state=await recovered.status()
        assert state['status']=='interrupted'
        assert state['series'][0]['error']=='worker_stopped_or_restarted'
        assert (await recovered.status())['job_id']==state['job_id']
    asyncio.run(run())


def test_concurrent_claims_create_one_job(factory):
    service=ingestion.IngestionService(lambda:factory)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:service._claim([SID]),range(4)))
    assert sum(created for _,created in results)==1
    assert len({state['job_id'] for state,_ in results})==1


@pytest.mark.parametrize('kind',['nan','duplicate','wrong_series','wrong_source'])
def test_invalid_batch_cannot_partially_overwrite_history(web,factory,monkeypatch,kind):
    with factory() as s:persist(s,points(SID,1))
    class Invalid(Success):
        async def fetch(self,sid):
            batch=points(sid,2)
            if kind=='nan':batch.append(dict(batch[0],date='2021-01-01',value=float('nan')))
            if kind=='duplicate':batch.append(dict(batch[0]))
            if kind=='wrong_series':batch[0]['series_id']='csv:injected'
            if kind=='wrong_source':batch[0]['source_url']='https://untrusted.example/private'
            return batch
    monkeypatch.setitem(ingestion.PROVIDERS,'worldbank',Invalid)
    web.post('/api/refresh',json={'series_ids':[SID]})
    state=finish(web)
    assert state['status']=='failed' and state['added']==0
    with factory() as s:assert [r.value for r in s.scalars(select(Observation)).all()]==[1]


def test_unknown_series_no_arbitrary_network_requests(web):
    assert web.post('/api/refresh',json={'series_ids':['https://internal.example']}).status_code==422
    assert web.get('/api/refresh').json()['status']=='idle'
    assert web.post('/api/refresh',json={'series_ids':[]}).status_code==422


def test_status_and_start_require_auth_and_csrf(factory,monkeypatch):
    monkeypatch.setattr(main,'Session',factory)
    with TestClient(main.app) as c:
        assert c.get('/api/refresh').status_code==401
        assert c.post('/api/refresh',headers={'X-ATLAS-CSRF':'1'}).status_code==401
        assert c.post('/api/refresh').status_code==403


def test_retry_after_long_delay_is_respected_without_early_retry(monkeypatch):
    calls=[]
    def transport(req):
        calls.append(req)
        return httpx.Response(429,headers={'Retry-After':'60'},request=req)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as c:
            with pytest.raises(httpx.HTTPStatusError):await request(c,'https://api.worldbank.org')
    asyncio.run(run())
    assert len(calls)==1


def test_storage_failure_rolls_back_observations_and_reports_error(web,factory,monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    def fail_after_flush(session,batch,commit=False):
        persist(session,batch,commit=False)
        raise SQLAlchemyError('sensitive storage detail')
    monkeypatch.setattr(ingestion,'persist',fail_after_flush)
    web.post('/api/refresh',json={'series_ids':[SID]})
    state=finish(web)
    assert state['status']=='failed'
    assert state['series'][0]['error']=='storage_write_failed'
    assert 'sensitive' not in json.dumps(state)
    with factory() as s:assert s.scalars(select(Observation)).all()==[]


def test_replaced_job_cannot_commit_late_results(factory):
    service=ingestion.IngestionService(lambda:factory)
    original,_=service._claim([SID])
    with factory() as s:
        job=s.get(IngestionJob,1);job.deadline=0;job.started_at=0;s.commit()
    replacement,_=service._claim([SID])
    assert original['job_id']!=replacement['job_id']
    service._update(original['job_id'],SID,'succeeded',points(SID))
    with factory() as s:assert s.scalars(select(Observation)).all()==[]


def test_provider_http_parsing_to_storage_end_to_end(web,monkeypatch):
    from atlas.providers import WorldBank, ECB
    monkeypatch.setattr(ingestion,'PROVIDERS',{'worldbank':WorldBank,'ecb':ECB})
    original=httpx.AsyncClient
    def respond(req):
        if req.url.host=='api.worldbank.org':return httpx.Response(200,json=[{},[{'date':'2020','value':2}]])
        return httpx.Response(200,text='TIME_PERIOD,OBS_VALUE\n2020-01-01,1.2\n')
    monkeypatch.setattr(ingestion.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    web.post('/api/refresh',json={'series_ids':[SID,FX]})
    state=finish(web)
    assert state['status']=='succeeded' and state['added']==2
    for sid in [SID,FX]:
        observation=web.get('/api/series/'+sid).json()['observations'][0]
        assert observation['source_url'].startswith('https://') and observation['retrieved_at']
        assert observation['publication_date'] is None


def test_shutdown_marks_active_job_and_retains_history(factory,monkeypatch):
    class Hung(Success):
        async def fetch(self,sid):await asyncio.sleep(10)
    monkeypatch.setattr(ingestion,'PROVIDERS',{'worldbank':Hung})
    async def run():
        service=ingestion.IngestionService(lambda:factory)
        await service.start([SID])
        await service.stop()
        state=await service.status()
        assert state['status'] not in ingestion.ACTIVE
        assert state['series'][0]['error']=='worker_stopped_or_restarted'
    asyncio.run(run())


def test_observation_batch_avoids_per_point_database_reads(factory):
    from datetime import date,timedelta
    from sqlalchemy import event
    engine=factory.kw['bind']
    reads=[]
    def count(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'FROM observations' in statement:reads.append(statement)
    event.listen(engine,'before_cursor_execute',count)
    batch=[dict(points(FX)[0],date=(date(2020,1,1)+timedelta(days=i)).isoformat(),value=i) for i in range(300)]
    try:
        with factory() as s:
            assert persist(s,batch)==300
            assert persist(s,batch)==0
        assert len(reads)==2
    finally:event.remove(engine,'before_cursor_execute',count)
