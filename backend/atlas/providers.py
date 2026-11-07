import asyncio, csv, io, math
from datetime import date
from typing import Protocol
import httpx
from .catalog import INDICATORS
from .storage import now

class Provider(Protocol):
 async def fetch(self, series_id: str) -> list[dict]: ...

async def request(client, url, **kwargs):
 for attempt in range(3):
  try:
   response=await client.get(url,**kwargs)
   response.raise_for_status()
   return response
  except (httpx.TimeoutException,httpx.NetworkError,httpx.HTTPStatusError) as exc:
   if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code not in (429,500,502,503,504): raise
   if attempt==2: raise
   await asyncio.sleep(2**attempt)

def point(series_id,day,value,url,provider,unit,frequency,geography,currency=None):
 number=float(value)
 if not math.isfinite(number): raise ValueError("Non-finite observation")
 date.fromisoformat(day)
 return dict(series_id=series_id,date=day,value=number,source_url=url,provider=provider,unit=unit,frequency=frequency,geography=geography,currency=currency,retrieved_at=now(),publication_date=None,revision_status="current vintage; publication date unavailable")

class WorldBank:
 def __init__(self,client): self.client=client
 async def fetch(self,series_id):
  _,country,code=series_id.split(":")
  url=f"https://api.worldbank.org/v2/country/{country}/indicator/{code}"
  response=await request(self.client,url,params={"format":"json","per_page":100,"date":f"1990:{date.today().year-1}"})
  body=response.json()
  if not isinstance(body,list) or len(body)!=2 or not isinstance(body[1],list): raise ValueError("World Bank returned no observation list")
  return [point(series_id,f"{r['date']}-12-31",r["value"],str(response.url),"worldbank",INDICATORS[code][1],"annual",country) for r in body[1] if r.get("value") is not None]

class ECB:
 def __init__(self,client): self.client=client
 async def fetch(self,series_id):
  currency=series_id.split(":")[1]
  url=f"https://data-api.ecb.europa.eu/service/data/EXR/D.{currency}.EUR.SP00.A"
  response=await request(self.client,url,params={"lastNObservations":300,"format":"csvdata"},headers={"Accept":"text/csv"})
  rows=list(csv.DictReader(io.StringIO(response.text)))
  if not rows or "OBS_VALUE" not in rows[0]: raise ValueError("ECB returned no valid CSV observations")
  return [point(series_id,r["TIME_PERIOD"],r["OBS_VALUE"],str(response.url),"ecb",f"{currency} per EUR","daily","Global",currency) for r in rows if r.get("OBS_VALUE")]
