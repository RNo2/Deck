import asyncio, csv, io, json, logging, re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
import httpx
from .catalog import catalog, SOURCES
from .storage import init_db, Observation, ProviderRun, Workspace, current_rows, persist, now
from .providers import WorldBank, ECB, point
from .analysis import analyze
from .auth import install_auth, settings

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("atlas")
Session=init_db()
from .ingestion import IngestionService, RefreshRejected
ingestion=IngestionService(lambda: Session)

@asynccontextmanager
async def lifespan(app):
 settings()
 await ingestion.recover()
 try:
  yield
 finally:
  await ingestion.stop()

app=FastAPI(title="ATLAS Research API",version="0.1.0",lifespan=lifespan,docs_url=None,redoc_url=None)
install_auth(app, lambda: Session)

# Preserve authenticated API documentation with nonce-protected initialization.
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import HTMLResponse
import secrets

def documentation_response(response):
 nonce=secrets.token_urlsafe(24)
 body=response.body.decode().replace("<script>",f'<script nonce="{nonce}">')
 body=body.replace("SwaggerUIBundle({",'SwaggerUIBundle({requestInterceptor: (request) => {request.headers["X-ATLAS-CSRF"]="1"; return request;},')
 return HTMLResponse(body,headers={"Content-Security-Policy":f"default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'nonce-{nonce}'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})

@app.get("/docs",include_in_schema=False)
def swagger_docs():
 return documentation_response(get_swagger_ui_html(openapi_url="/openapi.json",title="ATLAS API"))

@app.get("/redoc",include_in_schema=False)
def redoc_docs():
 return documentation_response(get_redoc_html(openapi_url="/openapi.json",title="ATLAS API",with_google_fonts=False))

def available(session):
 items={item["id"]:item for item in catalog()}
 for row in session.scalars(select(Observation).where(Observation.provider=="csv")).all():
  items[row.series_id]=dict(id=row.series_id,name=row.series_id.removeprefix("csv:"),provider="csv",country=row.geography,unit=row.unit,frequency=row.frequency,category="uploaded research")
 return list(items.values())

@app.get("/api/health")
def health(): return {"status":"ok","version":"0.1.0","mode":"local research · no paid services"}

@app.get("/api/catalog")
def get_catalog():
 with Session() as s: return available(s)

@app.get("/api/coverage")
def coverage():
 with Session() as s:
  results=[]
  for key,source in SOURCES.items():
   run=s.get(ProviderRun,key)
   rows=s.scalars(select(Observation).where(Observation.provider==key)).all()
   results.append(dict(id=key,**source,status=run.status if run else "not checked",message=run.message if run else "Refresh to test provider availability",checked_at=run.checked_at if run else None,observations=len(rows),series=len({r.series_id for r in rows}),latest_observation=max((r.date for r in rows),default=None),last_retrieved=max((r.retrieved_at for r in rows),default=None)))
  return results

class RefreshInput(BaseModel):
 series_ids: list[str] | None=Field(default=None,max_length=100)

@app.get("/api/refresh")
async def refresh_status():
 return await ingestion.status()

@app.post("/api/refresh",status_code=202)
async def refresh(body: RefreshInput | None=None):
 try:
  return await ingestion.start(body.series_ids if body else None)
 except RefreshRejected as exc:
  raise HTTPException(429,"Refresh cooldown active; stored data remains available.",headers={"Retry-After":str(exc.seconds)}) from None
 except ValueError:
  raise HTTPException(422,"Only configured provider series can be refreshed") from None

@app.get("/api/series/{series_id:path}")
def series(series_id: str):
 with Session() as s:
  item=next((i for i in available(s) if i["id"]==series_id),None)
  if not item: raise HTTPException(404,"Unknown series")
  rows=current_rows(s,series_id)
  points=[{col.name:getattr(r,col.name) for col in Observation.__table__.columns if col.name!="id"} for r in rows]
  return {"metadata":item,"observations":points,"analysis":analyze(rows,item["frequency"]),"freshness":{"latest_observation":rows[-1].date if rows else None,"retrieved_at":max((r.retrieved_at for r in rows),default=None),"age_days":(date.today()-date.fromisoformat(rows[-1].date)).days if rows else None}}

@app.get("/api/discovery")
def discovery():
 with Session() as s:
  results=[]
  for item in available(s):
   rows=current_rows(s,item["id"])
   result=analyze(rows,item["frequency"])
   if result.get("z_score") is not None and abs(result["z_score"])>=2:
    results.append({"series":item,"analysis":result,"support":[f"Latest value deviates {result['z_score']:.2f} standard deviations from its trailing baseline."],"counterarguments":["A single-series anomaly may reflect a temporary shock, revision, or structural break."],"catalysts":[],"historical_comparison":"Trailing baseline only; no matched historical scenario engine yet.","sources":list({r.source_url for r in rows}),"risk":"No independent fundamental, policy, or cross-market corroboration."})
  return sorted(results,key=lambda x:x["analysis"]["priority"],reverse=True)

class WatchlistInput(BaseModel):
 name: str=Field(min_length=1,max_length=100)
 series_ids: list[str]=Field(max_length=100)

@app.get("/api/watchlists")
def watchlists():
 with Session() as s: return [{"id":w.id,"name":w.name,"series_ids":json.loads(w.series_ids)} for w in s.scalars(select(Workspace)).all()]

@app.post("/api/watchlists")
def save_watchlist(body: WatchlistInput):
 with Session() as s:
  valid={i["id"] for i in available(s)}
  if any(i not in valid for i in body.series_ids): raise HTTPException(422,"Unknown series")
  w=Workspace(name=body.name.strip(),series_ids=json.dumps(list(dict.fromkeys(body.series_ids)))); s.add(w); s.commit()
  return {"id":w.id,"name":w.name,"series_ids":json.loads(w.series_ids)}

@app.delete("/api/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id:int):
 with Session() as s:
  w=s.get(Workspace,watchlist_id)
  if not w: raise HTTPException(404,"Unknown watchlist")
  s.delete(w); s.commit()
 return {"deleted":True}

class ImportInput(BaseModel):
 name: str=Field(pattern=r"^[A-Za-z0-9 _.-]{1,80}$")
 source_url: str=Field(pattern=r"^https?://",max_length=1000)
 unit: str=Field(min_length=1,max_length=80)
 geography: str=Field(min_length=1,max_length=80)
 frequency: str=Field(pattern="^(daily|weekly|monthly|annual)$")
 csv_text: str=Field(max_length=2_000_000)

@app.post("/api/import")
def import_csv(body:ImportInput):
 try:
  reader=csv.DictReader(io.StringIO(body.csv_text))
  if reader.fieldnames!=["date","value"]: raise ValueError("Expected exactly date,value columns")
  rows=list(reader)
  if not rows or len(rows)>10000: raise ValueError("Supply 1–10000 observations")
  if len({r["date"] for r in rows})!=len(rows): raise ValueError("Duplicate observation dates")
  points=[point("csv:"+body.name,r["date"],r["value"],body.source_url,"csv",body.unit,body.frequency,body.geography) for r in rows]
  if any(p["date"]>date.today().isoformat() for p in points): raise ValueError("Future observations are not accepted")
 except (ValueError,KeyError,TypeError) as exc: raise HTTPException(422,str(exc)) from exc
 with Session() as s:
  existing=current_rows(s,"csv:"+body.name)
  if existing and any(getattr(existing[-1],k)!=getattr(body,k) for k in ("unit","frequency","geography")): raise HTTPException(409,"Existing series metadata differs; use a new name")
  count=persist(s,points)
 return {"added":count,"series_id":"csv:"+body.name}

@app.get("/api/export")
def export(series_id:str):
 with Session() as s:
  rows=current_rows(s,series_id)
  if not rows: raise HTTPException(404,"No stored data")
  out=io.StringIO(); writer=csv.writer(out); columns=[c.name for c in Observation.__table__.columns if c.name!="id"]
  writer.writerow(columns)
  for r in rows: writer.writerow([getattr(r,c) for c in columns])
  return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=atlas-observations.csv"})

@app.get("/api/report")
def report(series_id:str):
 data=series(series_id)
 return {"title":data["metadata"]["name"],"generated_at":now(),"research_question":"Has the latest observation changed unusually relative to its trailing history?","summary":data["analysis"]["status"],"analysis":data["analysis"],"sources":list({r["source_url"] for r in data["observations"]}),"limitations":["Single-series descriptive research, not an investment recommendation.","Policy, fundamentals and historical scenario corroboration are not implemented."],"data":data["observations"]}

# Production serves the built frontend from the same origin as the protected API.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
frontend_dist=Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
 app.mount("/",StaticFiles(directory=frontend_dist,html=True),name="frontend")
