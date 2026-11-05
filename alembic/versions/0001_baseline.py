"""Initial schema for new installations.

Revision ID: 0001_baseline
Revises:
"""
from alembic import op
from sqlalchemy import inspect
from app import main
from app import extended, operations, account_recovery, pilot_pack
revision="0001_baseline"
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    connection=op.get_bind()
    existing=set(inspect(connection).get_table_names())-{"alembic_version"}
    if existing:
        raise RuntimeError(
            "Baseline migration requires an empty database. "
            "Use a staging reconciliation and reviewed incremental migrations for existing data.")
    main.Base.metadata.create_all(bind=connection, checkfirst=True)
def downgrade():
    raise RuntimeError("Restore a verified backup instead of dropping school records")
