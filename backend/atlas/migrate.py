"""Run versioned, forward-only migrations without logging database credentials."""
from pathlib import Path
from alembic.config import Config
from alembic import command

def upgrade(engine):
 config=Config()
 config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
 with engine.begin() as connection:
  config.attributes["connection"]=connection
  command.upgrade(config,"head")

if __name__=="__main__":
 from .storage import make_engine
 upgrade(make_engine())
