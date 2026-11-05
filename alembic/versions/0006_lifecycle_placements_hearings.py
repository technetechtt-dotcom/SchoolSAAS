"""Add learner placements and hearing attendance/procedure fields.

Revision ID: 0006_lifecycle_placements_hearings
Revises: 0005_journey_billing_comms
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_lifecycle_placements_hearings"
down_revision = "0005_journey_billing_comms"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if not _has_table("learner_placements"):
        op.create_table(
            "learner_placements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, index=True),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False, index=True),
            sa.Column("grade", sa.String(25), nullable=False),
            sa.Column("class_name", sa.String(30), nullable=False),
            sa.Column("reason", sa.String(40), nullable=False, server_default="enrolment"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("effective_on", sa.Date(), nullable=False),
            sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if _has_table("hearings"):
        if not _has_column("hearings", "participants"):
            op.add_column("hearings", sa.Column("participants", sa.Text(), server_default=""))
        if not _has_column("hearings", "attendance_notes"):
            op.add_column("hearings", sa.Column("attendance_notes", sa.Text(), server_default=""))
        if not _has_column("hearings", "procedural_checks"):
            op.add_column("hearings", sa.Column("procedural_checks", sa.Text(), server_default=""))


def downgrade():
    raise RuntimeError("Do not drop placement or hearing procedure records without an approved retention plan")
