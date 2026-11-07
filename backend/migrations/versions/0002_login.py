"""Persist revocable login sessions and single-user login throttling."""
from alembic import op
import sqlalchemy as sa
revision="0002"
down_revision="0001"

def upgrade():
 op.create_table("login_sessions",sa.Column("token_hash",sa.String(64),primary_key=True),sa.Column("expires",sa.Integer,nullable=False),sa.Column("credential_tag",sa.String(64),nullable=False))
 op.create_table("login_throttle",sa.Column("id",sa.Integer,primary_key=True),sa.Column("failures",sa.Integer,nullable=False),sa.Column("window_start",sa.Integer,nullable=False))
 op.bulk_insert(sa.table("login_throttle",sa.column("id",sa.Integer),sa.column("failures",sa.Integer),sa.column("window_start",sa.Integer)),[{"id":1,"failures":0,"window_start":0}])

def downgrade():
 op.drop_table("login_sessions")
 op.drop_table("login_throttle")
