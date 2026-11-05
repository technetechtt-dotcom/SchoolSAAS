"""Alembic migrations for SchoolSAAS."""
from alembic import context
from sqlalchemy import create_engine, pool
import os
from app import main
from app import extended, operations, pilot_pack, learner_journey, privacy_requests, onboarding, letter_workflow, session_security  # noqa: F401

config=context.config
target_metadata=main.Base.metadata
def url():return os.environ.get("DATABASE_URL",config.get_main_option("sqlalchemy.url"))
def offline():
    context.configure(url=url(),target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
def online():
    engine=create_engine(url(),poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
    engine.dispose()
if context.is_offline_mode():offline()
else:online()
