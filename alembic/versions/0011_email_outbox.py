"""Durable email outbox for failed/pending SMTP deliveries.

Revision ID: 0011_email_outbox
Revises: 0010_staff_access_reviews
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0011_email_outbox"
down_revision = "0010_staff_access_reviews"
branch_labels = None
depends_on = None


def upgrade():
    tables = inspect(op.get_bind()).get_table_names()
    if "email_outbox" not in tables:
        op.create_table(
            "email_outbox",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=True, index=True),
            sa.Column("destination", sa.String(255), nullable=False),
            sa.Column("subject", sa.String(200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    raise RuntimeError("Do not drop email_outbox without an approved retention plan")
