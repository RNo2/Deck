"""Explicit one-time data copy into an empty migrated target; never auto-run."""
import os
from sqlalchemy import select, func, text
from .storage import make_engine, Observation, ProviderRun, Workspace
from .migrate import upgrade

def transfer(source_url, target_url):
 source=make_engine(source_url)
 target=make_engine(target_url)
 upgrade(target)
 tables=[Observation.__table__,ProviderRun.__table__,Workspace.__table__]
 counts={}
 # Copy every stored vintage and provenance column, not just current observations.
 # Authentication records are deliberately not transferable.
 with source.connect() as origin, target.begin() as destination:
  if any(destination.scalar(select(func.count()).select_from(t)) for t in tables):
   raise RuntimeError("Target must have no application data; refusing to overwrite")
  for table in tables:
   rows=[dict(r) for r in origin.execute(select(table)).mappings()]
   for start in range(0,len(rows),500):
    destination.execute(table.insert(),rows[start:start+500])
   counts[table.name]=len(rows)
   if target.dialect.name=="postgresql" and "id" in table.c:
    # Reset serial sequences after copying explicit IDs.
    destination.execute(text("SELECT setval(pg_get_serial_sequence(:table, 'id'), COALESCE((SELECT MAX(id) FROM "+table.name+"), 1), EXISTS(SELECT 1 FROM "+table.name+"))"),{"table":table.name})
 source.dispose();target.dispose()
 return counts

if __name__=="__main__":
 if not os.environ.get("ATLAS_SOURCE_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
  raise SystemExit("Set ATLAS_SOURCE_DATABASE_URL and DATABASE_URL in the environment")
 print(transfer(os.environ["ATLAS_SOURCE_DATABASE_URL"],os.environ["DATABASE_URL"]))
