"""MFA recovery codes and security event feed tables.

Revision ID: 0009_mfa_recovery_security_events
Revises: 0008_sessions_invites_docs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009_mfa_recovery_security_events"
down_revision = "0008_sessions_invites_docs"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("mfa_recovery_codes"):
        op.create_table(
            "mfa_recovery_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_table("security_events"):
        op.create_table(
            "security_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=True, index=True),
            sa.Column("event_type", sa.String(60), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("emailed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    raise RuntimeError("Do not drop MFA recovery or security event records without an approved retention plan")
