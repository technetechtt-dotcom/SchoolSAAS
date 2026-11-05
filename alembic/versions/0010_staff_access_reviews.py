"""Staff access review history table.

Revision ID: 0010_staff_access_reviews
Revises: 0009_mfa_recovery_security_events
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010_staff_access_reviews"
down_revision = "0009_mfa_recovery_security_events"
branch_labels = None
depends_on = None


def upgrade():
    tables = inspect(op.get_bind()).get_table_names()
    if "staff_access_reviews" not in tables:
        op.create_table(
            "staff_access_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("deactivated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    raise RuntimeError("Do not drop staff access review history without an approved retention plan")
