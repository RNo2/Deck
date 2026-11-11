"""Bounded, tracked ingestion for catalog series; reusable for later on-demand retrieval."""
import asyncio
import json
import logging
import math
from datetime import date, datetime
from urllib.parse import urlsplit
import time
import uuid
import threading
from functools import wraps
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
import httpx
from .catalog import catalog
from .providers import WorldBank, ECB
from .storage import IngestionJob, ProviderRun, now, persist

log=logging.getLogger('atlas.ingestion')
RUN_SECONDS=120
SERIES_SECONDS=20
COOLDOWN_SECONDS=300
ACTIVE=('queued','running')
PROVIDERS={'worldbank':WorldBank,'ecb':ECB}


def error_code(exc):
    if isinstance(exc,httpx.HTTPStatusError): return 'http_'+str(exc.response.status_code)
    if isinstance(exc,(TimeoutError,httpx.TimeoutException)): return 'timeout'
    if isinstance(exc,httpx.ProxyError): return 'proxy_connection_failed'
    if isinstance(exc,httpx.ConnectError): return 'connection_failed_dns_tls_or_network'
    if isinstance(exc,httpx.HTTPError): return 'transport_failed'
    if isinstance(exc,SQLAlchemyError): return 'storage_write_failed'
    if isinstance(exc,(ValueError,KeyError,TypeError)): return 'invalid_or_empty_provider_data'
    return 'internal_ingestion_error'


def validate_points(points, item):
    # Validate the whole series before opening its atomic storage transaction.
    if not isinstance(points,list) or not points or len(points)>10000:
        raise ValueError('Invalid observation count')
    dates=set()
    source_hosts={'worldbank':'api.worldbank.org','ecb':'data-api.ecb.europa.eu'}
    for point in points:
        if (point['series_id']!=item['id'] or point['provider']!=item['provider'] or
            point['unit']!=item['unit'] or point['frequency']!=item['frequency'] or
            point['geography']!=item['country']):
            raise ValueError('Observation metadata mismatch')
        day=date.fromisoformat(point['date'])
        if day>date.today() or point['date'] in dates: raise ValueError('Invalid observation date')
        dates.add(point['date'])
        if isinstance(point['value'],bool) or not math.isfinite(float(point['value'])): raise ValueError('Invalid observation value')
        source=urlsplit(point['source_url'])
        if source.scheme!='https' or source.hostname!=source_hosts[item['provider']] or source.username or source.password:
            raise ValueError('Invalid provider attribution')
        if datetime.fromisoformat(point['retrieved_at']).tzinfo is None: raise ValueError('Missing retrieval timezone')


def snapshot(row):
    return dict(job_id=row.job_id,status=row.status,started_at=row.started_at,updated_at=row.updated_at,
                deadline=row.deadline,**json.loads(row.payload))


def serialized(method):
    # SQLite ignores SELECT FOR UPDATE; serialize local job writes as well.
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with self.db_lock:return method(self,*args,**kwargs)
    return wrapped


class RefreshRejected(Exception):
    def __init__(self,seconds): self.seconds=seconds


class IngestionService:
    def __init__(self,factory):
        self.factory=factory
        self.task=None
        self.db_lock=threading.RLock()

    @serialized
    def _status(self):
        with self.factory()() as s:
            row=s.get(IngestionJob,1)
            if row.status in ACTIVE and time.time()>row.deadline:
                self._finish_locked(s,row,'interrupted','run_deadline_exceeded')
            return snapshot(row)

    async def status(self): return await asyncio.to_thread(self._status)

    @serialized
    def _claim(self,ids):
        items=[i for i in catalog() if ids is None or i['id'] in ids]
        if not items: raise ValueError('No supported provider series selected')
        with self.factory()() as s:
            row=s.scalar(select(IngestionJob).where(IngestionJob.id==1).with_for_update())
            current=time.time()
            if row.status in ACTIVE and current<=row.deadline: return snapshot(row),False
            if row.status in ACTIVE: self._finish_locked(s,row,'interrupted','run_deadline_exceeded')
            if row.started_at and current-row.started_at<COOLDOWN_SECONDS:
                raise RefreshRejected(max(1,int(COOLDOWN_SECONDS-(current-row.started_at))))
            job_id=uuid.uuid4().hex
            payload={'total':len(items),'completed':0,'added':0,'message':'Refresh queued',
                     'series':[dict(id=i['id'],provider=i['provider'],status='queued',added=0,error=None) for i in items]}
            # Conditional claim also serializes competing SQLite writers (FOR UPDATE is PostgreSQL-only).
            result=s.execute(update(IngestionJob).where(IngestionJob.id==1,IngestionJob.status.not_in(ACTIVE)).values(
                job_id=job_id,status='queued',started_at=current,updated_at=current,deadline=current+RUN_SECONDS,payload=json.dumps(payload)))
            if result.rowcount!=1:
                s.rollback();return snapshot(s.get(IngestionJob,1)),False
            for key in {i['provider'] for i in items}:
                s.merge(ProviderRun(provider=key,checked_at=now(),status='queued',message='Refresh queued; awaiting provider request.'))
            s.commit();s.expire_all()
            return snapshot(s.get(IngestionJob,1)),True

    async def start(self,ids=None):
        if ids is not None:
            known={i['id'] for i in catalog()}
            if not ids or not set(ids)<=known: raise ValueError('Only configured provider series can be refreshed')
        result,created=await asyncio.to_thread(self._claim,ids)
        if created:
            self.task=asyncio.create_task(self._run(result['job_id']),name='atlas-ingestion')
        return result

    @serialized
    def _update(self,job_id,series_id,status,points=None,error=None):
        with self.factory()() as s:
            row=s.scalar(select(IngestionJob).where(IngestionJob.id==1).with_for_update())
            if row.job_id!=job_id or row.status not in ACTIVE or time.time()>row.deadline: return
            payload=json.loads(row.payload)
            item=next(i for i in payload['series'] if i['id']==series_id)
            added=persist(s,points,commit=False) if points else 0
            item.update(status=status,added=added,error=error)
            payload['completed']=sum(i['status'] not in ACTIVE for i in payload['series'])
            payload['added']=sum(i['added'] for i in payload['series'])
            payload['message']=f"{payload['completed']}/{payload['total']} series finished; {payload['added']} new or revised observations"
            row.status='running';row.updated_at=time.time();row.payload=json.dumps(payload)
            self._provider(s,payload,item['provider'])
            s.commit()

    def _provider(self,s,payload,key):
        items=[i for i in payload['series'] if i['provider']==key]
        pending=any(i['status'] in ACTIVE for i in items)
        succeeded=sum(i['status']=='succeeded' for i in items)
        errors=[i['error'] for i in items if i['error']]
        status='running' if pending else ('available' if succeeded==len(items) else 'partial' if succeeded else 'unavailable')
        message=f"{sum(i['status'] not in ACTIVE for i in items)}/{len(items)} series finished; {sum(i['added'] for i in items)} new or revised observations."
        if errors: message+=' Errors: '+', '.join(sorted(set(errors)))
        s.merge(ProviderRun(provider=key,checked_at=now(),status=status,message=message))

    def _finish_locked(self,s,row,status,error=None):
        payload=json.loads(row.payload)
        for item in payload.get('series',[]):
            if item['status'] in ACTIVE: item.update(status='failed',error=error or 'interrupted')
        payload['completed']=len(payload.get('series',[]))
        payload['message']=error or f"Refresh {status}; {payload.get('added',0)} new or revised observations"
        row.status=status;row.updated_at=time.time();row.payload=json.dumps(payload)
        for key in {i['provider'] for i in payload.get('series',[])}: self._provider(s,payload,key)
        s.commit()

    @serialized
    def _finish(self,job_id,error=None):
        with self.factory()() as s:
            row=s.scalar(select(IngestionJob).where(IngestionJob.id==1).with_for_update())
            if row.job_id!=job_id or row.status not in ACTIVE: return
            items=json.loads(row.payload)['series']
            successes=sum(i['status']=='succeeded' for i in items)
            status='succeeded' if successes==len(items) else 'partial' if successes else 'failed'
            self._finish_locked(s,row,status,error)

    async def _provider_run(self,client,job_id,key,items):
        provider=PROVIDERS[key](client)
        blocked=None
        for item in items:
            sid=item['id']
            if blocked:
                await asyncio.to_thread(self._update,job_id,sid,'skipped',None,blocked)
                continue
            await asyncio.to_thread(self._update,job_id,sid,'running')
            try:
                async with asyncio.timeout(SERIES_SECONDS):
                    points=await provider.fetch(sid)
                    validate_points(points,next(i for i in catalog() if i['id']==sid))
                await asyncio.to_thread(self._update,job_id,sid,'succeeded',points)
            except Exception as exc:
                code=error_code(exc)
                log.warning('ingestion series=%s outcome=%s',sid,code)
                await asyncio.to_thread(self._update,job_id,sid,'failed',None,code)
                if code in ('http_401','http_403','http_429','proxy_connection_failed'): blocked=code
            await asyncio.sleep(.2)

    async def _run(self,job_id):
        error=None
        try:
            async with asyncio.timeout(RUN_SECONDS):
                state=await self.status()
                async with httpx.AsyncClient(timeout=httpx.Timeout(8,connect=5),follow_redirects=True,
                       headers={'User-Agent':'ATLAS-local-research/0.1'}) as client:
                    async with asyncio.TaskGroup() as group:
                        for key in PROVIDERS:
                            items=[i for i in state['series'] if i['provider']==key]
                            if items: group.create_task(self._provider_run(client,job_id,key,items))
        except asyncio.CancelledError: error='worker_stopped_or_restarted'
        except TimeoutError: error='run_deadline_exceeded'
        except Exception: error='internal_ingestion_error'
        try: await asyncio.to_thread(self._finish,job_id,error)
        except Exception: log.error('ingestion outcome=status_persistence_failed')

    @serialized
    def _recover(self):
        with self.factory()() as s:
            row=s.get(IngestionJob,1)
            if row.status in ACTIVE:self._finish_locked(s,row,'interrupted','worker_stopped_or_restarted')

    async def recover(self):
        await asyncio.to_thread(self._recover)

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
            await asyncio.to_thread(self._recover)
