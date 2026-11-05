"""Alembic migrations for SchoolSAAS."""
from alembic import context
from sqlalchemy import create_engine, pool, text
import os
from app import main
from app import extended, operations, pilot_pack, learner_journey, privacy_requests, onboarding, letter_workflow, session_security, account_security, directory_ops  # noqa: F401

config=context.config
target_metadata=main.Base.metadata
def url():return os.environ.get("DATABASE_URL",config.get_main_option("sqlalchemy.url"))
def offline():
    context.configure(url=url(),target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
def online():
    engine=create_engine(url(),poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Preserve historical long revision IDs. Alembic defaults to VARCHAR(32),
        # which rejects revisions such as 0006_lifecycle_placements_hearings.
        # The DDL is idempotent for both new and existing PostgreSQL databases.
        if connection.dialect.name == "postgresql":
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(128) NOT NULL)"))
            connection.execute(text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
            connection.commit()
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
    engine.dispose()
if context.is_offline_mode():offline()
else:online()
