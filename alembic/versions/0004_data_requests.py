"""Create audited data subject request tracker.

Revision ID: 0004_data_requests
Revises: 0003_parent_subject
"""
from alembic import op
from app.privacy_requests import DataSubjectRequest
revision="0004_data_requests"
down_revision="0003_parent_subject"
branch_labels=None
depends_on=None
def upgrade():
    DataSubjectRequest.__table__.create(bind=op.get_bind(),checkfirst=True)
def downgrade():
    raise RuntimeError("Do not drop privacy request records without an approved retention plan")
