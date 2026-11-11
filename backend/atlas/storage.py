import os
import socket
import certifi
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Float, Text, Integer, UniqueConstraint, select, event, tuple_
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase): pass
class Observation(Base):
 __tablename__="observations"
 __table_args__=(UniqueConstraint("series_id","date","retrieved_at"),)
 id: Mapped[int]=mapped_column(primary_key=True)
 series_id: Mapped[str]=mapped_column(String,index=True)
 date: Mapped[str]=mapped_column(String)
 value: Mapped[float]=mapped_column(Float)
 retrieved_at: Mapped[str]=mapped_column(String)
 source_url: Mapped[str]=mapped_column(Text)
 provider: Mapped[str]=mapped_column(String)
 unit: Mapped[str]=mapped_column(String)
 frequency: Mapped[str]=mapped_column(String)
 geography: Mapped[str]=mapped_column(String)
 currency: Mapped[str | None]=mapped_column(String,nullable=True)
 publication_date: Mapped[str | None]=mapped_column(String,nullable=True)
 revision_status: Mapped[str]=mapped_column(String,default="current vintage; original publication unknown")
class ProviderRun(Base):
 __tablename__="provider_runs"
 provider: Mapped[str]=mapped_column(String,primary_key=True)
 checked_at: Mapped[str]=mapped_column(String)
 status: Mapped[str]=mapped_column(String)
 message: Mapped[str]=mapped_column(Text)
class Workspace(Base):
 __tablename__="workspaces"
 id: Mapped[int]=mapped_column(primary_key=True)
 name: Mapped[str]=mapped_column(String)
 series_ids: Mapped[str]=mapped_column(Text)

def now(): return datetime.now(timezone.utc).isoformat()
def database_url(url=None):
 url=url or os.environ.get("DATABASE_URL")
 if not url:
  directory=Path(os.environ.get("ATLAS_DATA_DIR", "var")); directory.mkdir(parents=True,exist_ok=True)
  url=f"sqlite:///{directory / 'atlas.db'}"
 if url.startswith("postgres://"): url="postgresql+psycopg://"+url[len("postgres://"):]
 elif url.startswith("postgresql://"): url="postgresql+psycopg://"+url[len("postgresql://"):]
 return url

def make_engine(url=None):
 url=database_url(url)
 if (os.environ.get("ATLAS_ENV")=="production" or os.environ.get("RENDER")) and make_url(url).query.get("sslmode")!="verify-full":
  raise RuntimeError("Production DATABASE_URL requires sslmode=verify-full for verified TLS")
 connect_args={"check_same_thread":False} if url.startswith("sqlite:") else {}
 if url.startswith("postgresql") and make_url(url).query.get("sslmode")=="verify-full" and "sslrootcert" not in make_url(url).query:
  connect_args["sslrootcert"]=os.environ.get("PGSSLROOTCERT") or certifi.where()
 engine=create_engine(url, pool_pre_ping=True, connect_args=connect_args, hide_parameters=True)
 if engine.dialect.name=="postgresql":
  @event.listens_for(engine, "do_connect")
  def use_ipv4(dialect, connection_record, cargs, cparams):
   # Resolve on every physical connection, including pool reconnects after DNS changes.
   # Keep host untouched: libpq uses it for SNI and verify-full certificate checks.
   host=cparams.get("host")
   if not host:
    raise RuntimeError("PostgreSQL IPv4 connections require a database hostname")
   try:
    addresses=socket.getaddrinfo(host,cparams.get("port",5432),socket.AF_INET,socket.SOCK_STREAM)
   except socket.gaierror:
    raise RuntimeError("PostgreSQL hostname IPv4 resolution failed") from None
   if not addresses:
    raise RuntimeError("PostgreSQL hostname has no IPv4 addresses")
   cparams["hostaddr"]=addresses[0][4][0]
 return engine

def init_db(url=None):
 from .migrate import upgrade
 engine=make_engine(url)
 upgrade(engine)
 return sessionmaker(engine,expire_on_commit=False)

class LoginSession(Base):
 __tablename__="login_sessions"
 token_hash: Mapped[str]=mapped_column(String(64),primary_key=True)
 expires: Mapped[int]=mapped_column(Integer)
 credential_tag: Mapped[str]=mapped_column(String(64))

class LoginThrottle(Base):
 __tablename__="login_throttle"
 id: Mapped[int]=mapped_column(primary_key=True)
 failures: Mapped[int]=mapped_column(Integer)
 window_start: Mapped[int]=mapped_column(Integer)

def current_rows(session, series_id):
 rows=session.scalars(select(Observation).where(Observation.series_id==series_id).order_by(Observation.retrieved_at,Observation.id)).all()
 latest={r.date:r for r in rows}
 return [latest[d] for d in sorted(latest)]

def persist(session, points, commit=True):
 # Fetch existing vintages in bounded batches instead of a network round trip per point.
 keys=list(dict.fromkeys((p["series_id"],p["date"]) for p in points))
 latest={}
 for offset in range(0,len(keys),400):
  rows=session.scalars(select(Observation).where(tuple_(Observation.series_id,Observation.date).in_(keys[offset:offset+400])).order_by(Observation.retrieved_at,Observation.id)).all()
  for row in rows: latest[(row.series_id,row.date)]=row
 added=0
 for point in points:
  key=(point["series_id"],point["date"])
  prior=latest.get(key)
  if prior and prior.value==point["value"] and prior.unit==point["unit"] and prior.source_url==point["source_url"]: continue
  row=Observation(**point)
  session.add(row);latest[key]=row;added+=1
 session.flush()
 if commit: session.commit()
 return added


class IngestionJob(Base):
 __tablename__="ingestion_job"
 id: Mapped[int]=mapped_column(primary_key=True)
 job_id: Mapped[str]=mapped_column(String)
 status: Mapped[str]=mapped_column(String)
 started_at: Mapped[float]=mapped_column(Float)
 updated_at: Mapped[float]=mapped_column(Float)
 deadline: Mapped[float]=mapped_column(Float)
 payload: Mapped[str]=mapped_column(Text)
