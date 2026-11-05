"""Expand encrypted MFA storage in existing PostgreSQL.

Revision ID: 0002_mfa_encrypted
Revises: 0001_baseline
"""
from alembic import op
import sqlalchemy as sa

revision="0002_mfa_encrypted"
down_revision="0001_baseline"
branch_labels=None
depends_on=None

def upgrade():
    # SQLite TEXT/VARCHAR lengths are not enforced; new installations have the
    # expanded column via the baseline metadata. PostgreSQL needs an ALTER.
    if op.get_bind().dialect.name=="postgresql":
        op.alter_column("users","mfa_secret",
            existing_type=sa.String(length=64),type_=sa.String(length=512),
            existing_nullable=True)
def downgrade():
    raise RuntimeError("Do not truncate encrypted MFA credentials; restore from backup")
