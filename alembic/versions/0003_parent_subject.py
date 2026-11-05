"""Bind parent access tokens to the original school notice.

Revision ID: 0003_parent_subject
Revises: 0002_mfa_encrypted
"""
from alembic import op
import sqlalchemy as sa
revision="0003_parent_subject"
down_revision="0002_mfa_encrypted"
branch_labels=None
depends_on=None
def upgrade():
    # New installations receive this column from Base.metadata; this also
    # upgrades previously installed 0002 schemas without dropping token data.
    conn=op.get_bind()
    existing={c["name"] for c in sa.inspect(conn).get_columns("parent_access_tokens")}
    if "subject" not in existing:
        op.add_column("parent_access_tokens",sa.Column("subject",sa.String(200),
            nullable=False,server_default="SchoolCare notice"))
def downgrade():
    raise RuntimeError("Do not drop acknowledgement binding without a data recovery plan")
