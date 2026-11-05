"""Add onboarding steps, letter documents and parent notice delivery tracking.

Revision ID: 0007_onboarding_letters
Revises: 0006_lifecycle_placements_hearings
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007_onboarding_letters"
down_revision = "0006_lifecycle_placements_hearings"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if not _has_table("onboarding_steps"):
        op.create_table(
            "onboarding_steps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("step_id", sa.String(60), nullable=False),
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has_table("letter_documents"):
        op.create_table(
            "letter_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("template_id", sa.Integer(), sa.ForeignKey("letter_templates.id"), nullable=True),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False, index=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("delivery_channel", sa.String(40), nullable=False, server_default="none"),
            sa.Column("delivery_to", sa.String(255), nullable=False, server_default=""),
            sa.Column("delivery_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("stored_pdf", sa.String(80), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if _has_table("parent_access_tokens"):
        if not _has_column("parent_access_tokens", "created_at"):
            op.add_column("parent_access_tokens", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column("parent_access_tokens", "delivery_status"):
            op.add_column("parent_access_tokens", sa.Column("delivery_status", sa.String(40), nullable=False, server_default="pending"))
        if not _has_column("parent_access_tokens", "delivery_attempts"):
            op.add_column("parent_access_tokens", sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"))
        if not _has_column("parent_access_tokens", "delivery_notes"):
            op.add_column("parent_access_tokens", sa.Column("delivery_notes", sa.Text(), nullable=False, server_default=""))
        if not _has_column("parent_access_tokens", "last_delivery_at"):
            op.add_column("parent_access_tokens", sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    raise RuntimeError("Do not drop onboarding or letter records without an approved retention plan")
