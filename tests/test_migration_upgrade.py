"""Incremental Alembic upgrades must preserve historical school data."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(url: str, *args: str):
    env = os.environ.copy()
    env.update(
        DATABASE_URL=url,
        SCHEMA_AUTO_CREATE="false",
        JWT_SECRET="migration-upgrade-secret-not-for-deployment",
        MFA_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90,
    )


def test_upgrade_head_on_populated_historical_schema(tmp_path):
    """Simulate a 0004-era DB with learners/incidents/cases, then upgrade through 0005."""
    db = tmp_path / "historical.db"
    url = "sqlite:///" + str(db)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE schools (
                id INTEGER PRIMARY KEY,
                name VARCHAR(160) NOT NULL,
                slug VARCHAR(80) NOT NULL,
                plan VARCHAR(30) DEFAULT 'trial',
                status VARCHAR(30) DEFAULT 'active'
            )
        """))
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                active BOOLEAN DEFAULT 1,
                mfa_enabled BOOLEAN DEFAULT 0,
                mfa_secret VARCHAR(255)
            )
        """))
        conn.execute(text("""
            CREATE TABLE learners (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                admission_no VARCHAR(80) NOT NULL,
                first_name VARCHAR(120) NOT NULL,
                surname VARCHAR(120) NOT NULL,
                grade VARCHAR(25) NOT NULL,
                class_name VARCHAR(30) NOT NULL,
                active BOOLEAN DEFAULT 1
            )
        """))
        conn.execute(text("""
            CREATE TABLE incidents (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                learner_id INTEGER NOT NULL,
                offence_id INTEGER,
                location VARCHAR(80),
                description TEXT,
                immediate_action VARCHAR(120),
                status VARCHAR(40) DEFAULT 'open',
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                learner_id INTEGER NOT NULL,
                title VARCHAR(200) NOT NULL,
                status VARCHAR(40) DEFAULT 'open',
                assigned_user_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                currency VARCHAR(8) DEFAULT 'ZAR',
                status VARCHAR(30) DEFAULT 'draft',
                description VARCHAR(200),
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE appeals (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                case_id INTEGER NOT NULL,
                reason TEXT,
                status VARCHAR(30),
                outcome TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE evidence_files (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                incident_id INTEGER,
                case_id INTEGER,
                filename VARCHAR(200),
                stored_name VARCHAR(80),
                content_type VARCHAR(120),
                size_bytes INTEGER,
                uploaded_by INTEGER,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE parent_access_tokens (
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL,
                learner_id INTEGER NOT NULL,
                email VARCHAR(255),
                token_hash VARCHAR(64),
                subject VARCHAR(200),
                expires_at DATETIME,
                used BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)
        """))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0004_data_requests')"))
        conn.execute(text("INSERT INTO schools(id,name,slug) VALUES (1,'History High','history-high')"))
        conn.execute(text("INSERT INTO users(id,email,password_hash) VALUES (1,'a@h.test','x')"))
        conn.execute(text(
            "INSERT INTO learners(id,school_id,admission_no,first_name,surname,grade,class_name) "
            "VALUES (7,1,'H-01','Ada','Ndlovu','5','5A')"
        ))
        conn.execute(text(
            "INSERT INTO incidents(id,school_id,learner_id,location,description,status) "
            "VALUES (3,1,7,'Classroom','Historical incident','open')"
        ))
        conn.execute(text(
            "INSERT INTO cases(id,school_id,learner_id,title,status) "
            "VALUES (2,1,7,'Historical case','monitoring')"
        ))
    engine.dispose()

    result = _run_alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    with create_engine(url).connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == "0007_onboarding_letters"
        assert conn.execute(text("SELECT COUNT(*) FROM learners")).scalar_one() == 1
        assert conn.execute(text("SELECT first_name FROM learners WHERE id=7")).scalar_one() == "Ada"
        assert conn.execute(text("SELECT COUNT(*) FROM incidents")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM cases WHERE title='Historical case'")).scalar_one() == 1
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()}
        assert "learner_observations" in tables
        assert "payment_events" in tables
        assert "parent_disputes" in tables
        assert "evidence_access_logs" in tables
        assert "learner_placements" in tables
        assert "onboarding_steps" in tables
        assert "letter_documents" in tables
        parent_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(parent_access_tokens)")).all()}
        assert {"delivery_status", "delivery_attempts", "delivery_notes"} <= parent_cols
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(invoices)")).all()}
        assert {"gateway", "payment_ref", "paid_at"} <= cols
        learner_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(learners)")).all()}
        assert {"enrolled_on", "grade_started"} <= learner_cols
        hearing_cols = {r[1] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hearings'")).all()}
        if hearing_cols or "hearings" in tables:
            hcols = {r[1] for r in conn.execute(text("PRAGMA table_info(hearings)")).all()}
            assert {"participants", "attendance_notes", "procedural_checks"} <= hcols
