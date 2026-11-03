"""Initial schema for new installations.

Revision ID: 0001_baseline
Revises:
"""
from alembic import op
from app import main
from app import extended, operations
revision="0001_baseline"
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    main.Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
def downgrade():
    raise RuntimeError("Restore a verified backup instead of dropping school records")
