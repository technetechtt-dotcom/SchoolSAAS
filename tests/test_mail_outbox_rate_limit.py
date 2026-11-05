"""Email outbox queue/retry and IP-aware auth rate limiting."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "mail-outbox-secret-key-32chars!!")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.pop("PLATFORM_ADMIN_EMAILS", None)
for k in ("SMTP_HOST", "SMTP_USER", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "APP_PUBLIC_URL"):
    os.environ.pop(k, None)

from app import main
from app import mail_outbox, letter_workflow, onboarding, session_security  # noqa: F401
from tests.conftest import finish_required_onboarding


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(engine, expire_on_commit=False)
    main.Base.metadata.create_all(engine)

    def override_db():
        with Session() as s:
            yield s

    main.app.dependency_overrides[main.db] = override_db
    return TestClient(main.app)


def test_mail_outbox_queues_letter_and_retry_endpoint():
    c = _client()

    def send(path, body=None, method="post"):
        return getattr(c, method)(path, json=body or {}, headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})

    try:
        assert send("/api/register", {
            "school_name": "Outbox School", "slug": "outbox-school",
            "email": "admin@outbox.test", "password": "demo-password-123456"
        }).status_code == 201
        send("/api/learners", {
            "admission_no": "O100", "first_name": "Lerato", "surname": "Dlamini",
            "grade": "5", "class_name": "5A"})
        send("/api/offences", {
            "code": "L1", "name": "Late", "category": "Attendance", "severity": 1})
        finish_required_onboarding(c, send)

        learner = c.get("/api/learners").json()[0]
        letter = send("/api/letter-documents", {
            "learner_id": learner["id"], "title": "Support notice",
            "body": "Dear guardian, please contact the school."})
        assert letter.status_code == 201, letter.text
        lid = letter.json()["id"]
        assert send(f"/api/letter-documents/{lid}/approve").status_code == 200
        delivered = send(f"/api/letter-documents/{lid}/deliver", {
            "email": "guardian@outbox.test", "channel": "email"})
        assert delivered.status_code == 200, delivered.text
        assert delivered.json().get("queued") is True
        assert delivered.json()["status"] == "queued"

        listed = c.get("/api/mail/outbox")
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert any(x["destination"] == "guardian@outbox.test" for x in items)
        assert any(x["status"] in ("pending", "failed") for x in items)

        invite = send("/api/invitations", {
            "email": "teacher@outbox.test", "role": "educator", "assigned_class": "5A"})
        assert invite.status_code == 201, invite.text
        assert invite.json().get("emailed") is False
        assert invite.json().get("token")

        retry = send("/api/mail/outbox/retry", {"limit": 10})
        assert retry.status_code == 200, retry.text
        assert "processed" in retry.json()
        assert "SMTP" in (retry.json().get("notice") or "")
    finally:
        main.app.dependency_overrides.clear()


def test_ip_auth_rate_limit_blocks_after_burst():
    c = _client()

    def send(path, body=None, method="post"):
        return getattr(c, method)(path, json=body or {}, headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})

    try:
        assert send("/api/register", {
            "school_name": "Rate School", "slug": "rate-school",
            "email": "admin@rate.test", "password": "demo-password-123456"
        }).status_code == 201
        send("/api/logout")

        codes = []
        for i in range(35):
            r = send("/api/login", {
                "school_slug": "rate-school",
                "email": f"missing{i}@rate.test",
                "password": "wrong-password-xxxxxx"})
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in codes, codes[-8:]
    finally:
        main.app.dependency_overrides.clear()
