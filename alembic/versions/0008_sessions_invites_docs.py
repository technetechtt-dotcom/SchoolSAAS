"""Session metadata, staff invite lifecycle, document approval columns.

Revision ID: 0008_sessions_invites_docs
Revises: 0007_onboarding_letters
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0008_sessions_invites_docs"
down_revision = "0007_onboarding_letters"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: str, col):
    if _has_table(table) and not _has_column(table, column):
        op.add_column(table, col)


def upgrade():
    if not _has_table("active_sessions"):
        op.create_table(
            "active_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_agent", sa.String(240), nullable=False, server_default=""),
            sa.Column("label", sa.String(120), nullable=False, server_default=""),
        )
    else:
        _add("active_sessions", "created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        _add("active_sessions", "last_seen_at", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        _add("active_sessions", "user_agent", sa.Column("user_agent", sa.String(240), nullable=False, server_default=""))
        _add("active_sessions", "label", sa.Column("label", sa.String(120), nullable=False, server_default=""))

    if not _has_table("staff_invites"):
        op.create_table(
            "staff_invites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(30), nullable=False),
            sa.Column("assigned_class", sa.String(30), nullable=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivery_status", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        _add("staff_invites", "revoked", sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()))
        _add("staff_invites", "created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        _add("staff_invites", "delivery_status", sa.Column("delivery_status", sa.String(40), nullable=False, server_default="pending"))
        _add("staff_invites", "delivery_attempts", sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"))
        _add("staff_invites", "last_delivery_at", sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True))

    if not _has_table("school_documents"):
        op.create_table(
            "school_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False),
            sa.Column("title", sa.String(180), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("document_type", sa.String(40), nullable=False, server_default="letter"),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    else:
        _add("school_documents", "status", sa.Column("status", sa.String(30), nullable=False, server_default="draft"))
        _add("school_documents", "approved_by", sa.Column("approved_by", sa.Integer(), nullable=True))
        _add("school_documents", "approved_at", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    raise RuntimeError("Do not drop session or invitation audit columns without an approved retention plan")
