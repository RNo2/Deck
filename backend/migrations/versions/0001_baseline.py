"""Adopt the original schema without replacing existing SQLite data."""
from alembic import op
import sqlalchemy as sa
revision="0001"
down_revision=None

def upgrade():
 # checkfirst permits adoption of the original create_all schema.
 metadata=sa.MetaData()
 sa.Table("observations",metadata,
  sa.Column("id",sa.Integer,primary_key=True),
  sa.Column("series_id",sa.String,nullable=False,index=True),
  *[sa.Column(n,sa.String,nullable=False) for n in ("date","retrieved_at","provider","unit","frequency","geography","revision_status")],
  sa.Column("value",sa.Float,nullable=False),sa.Column("source_url",sa.Text,nullable=False),
  sa.Column("currency",sa.String),sa.Column("publication_date",sa.String),
  sa.UniqueConstraint("series_id","date","retrieved_at"))
 sa.Table("provider_runs",metadata,sa.Column("provider",sa.String,primary_key=True),
  *[sa.Column(n,sa.String,nullable=False) for n in ("checked_at","status")],sa.Column("message",sa.Text,nullable=False))
 sa.Table("workspaces",metadata,sa.Column("id",sa.Integer,primary_key=True),sa.Column("name",sa.String,nullable=False),sa.Column("series_ids",sa.Text,nullable=False))
 metadata.create_all(op.get_bind(),checkfirst=True)

def downgrade():
 raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
