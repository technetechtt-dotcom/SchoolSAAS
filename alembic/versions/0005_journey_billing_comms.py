"""Add learner journey, billing settlement and parent-comms tables/columns.

Revision ID: 0005_journey_billing_comms
Revises: 0004_data_requests
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_journey_billing_comms"
down_revision = "0004_data_requests"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if not _has_table("learner_observations"):
        op.create_table(
            "learner_observations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False, index=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("grade_at_time", sa.String(25), nullable=False),
            sa.Column("domain", sa.String(40), nullable=False),
            sa.Column("title", sa.String(180), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("level", sa.String(30), nullable=False, server_default="developing"),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("contributing_factor", sa.String(20), nullable=False, server_default="unknown"),
            sa.Column("source", sa.String(40), nullable=False, server_default="classroom_observation"),
            sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has_table("evidence_access_logs"):
        op.create_table(
            "evidence_access_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence_files.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action", sa.String(40), nullable=False, server_default="download"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has_table("parent_disputes"):
        op.create_table(
            "parent_disputes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False, index=True),
            sa.Column("access_id", sa.Integer(), sa.ForeignKey("parent_access_tokens.id"), nullable=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("subject", sa.String(200), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="open"),
            sa.Column("resolution_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_table("payment_events"):
        op.create_table(
            "payment_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=False, index=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("event_type", sa.String(60), nullable=False),
            sa.Column("external_ref", sa.String(120), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("provider", "external_ref", name="uq_payment_events_provider_ref"),
        )

    if _has_table("invoices"):
        if not _has_column("invoices", "gateway"):
            op.add_column("invoices", sa.Column("gateway", sa.String(40), server_default="none"))
        if not _has_column("invoices", "payment_ref"):
            op.add_column("invoices", sa.Column("payment_ref", sa.String(80), nullable=True))
        if not _has_column("invoices", "paid_at"):
            op.add_column("invoices", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    if _has_table("appeals") and not _has_column("appeals", "hearing_id"):
        op.add_column("appeals", sa.Column("hearing_id", sa.Integer(), nullable=True))
    if _has_table("learners"):
        if not _has_column("learners", "enrolled_on"):
            op.add_column("learners", sa.Column("enrolled_on", sa.Date(), nullable=True))
        if not _has_column("learners", "grade_started"):
            op.add_column("learners", sa.Column("grade_started", sa.String(25), nullable=True))


def downgrade():
    raise RuntimeError("Do not drop journey/billing/comms records without an approved retention plan")
