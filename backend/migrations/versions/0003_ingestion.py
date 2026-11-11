"""Durable, single-worker ingestion progress and admission control."""
from alembic import op
import sqlalchemy as sa
revision='0003'
down_revision='0002'

def upgrade():
 op.create_table('ingestion_job',sa.Column('id',sa.Integer,primary_key=True),
  sa.Column('job_id',sa.String,nullable=False),sa.Column('status',sa.String,nullable=False),
  sa.Column('started_at',sa.Float,nullable=False),sa.Column('updated_at',sa.Float,nullable=False),
  sa.Column('deadline',sa.Float,nullable=False),sa.Column('payload',sa.Text,nullable=False))
 table=sa.table('ingestion_job',sa.column('id',sa.Integer),sa.column('job_id',sa.String),sa.column('status',sa.String),
  sa.column('started_at',sa.Float),sa.column('updated_at',sa.Float),sa.column('deadline',sa.Float),sa.column('payload',sa.Text))
 op.bulk_insert(table,[dict(id=1,job_id='',status='idle',started_at=0,updated_at=0,deadline=0,
  payload='{"total":0,"completed":0,"added":0,"series":[],"message":"No refresh requested"}')])

def downgrade():op.drop_table('ingestion_job')
