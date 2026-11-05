"""Onboarding progress, letter PDF workflow, parent delivery tracking, incident closure."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "onboard-letters-secret-key-32chars!!")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.pop("PLATFORM_ADMIN_EMAILS", None)
os.environ.pop("BILLING_GATEWAY", None)
os.environ.pop("BILLING_WEBHOOK_SECRET", None)

from app import main
from app import pilot_pack, operations, extended, onboarding, letter_workflow  # noqa: F401
from app.letter_workflow import render_simple_pdf


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(engine, expire_on_commit=False)
    main.Base.metadata.create_all(engine)

    def override_db():
        with Session() as s:
            yield s

    main.app.dependency_overrides[main.db] = override_db
    return TestClient(main.app), Session


def test_onboarding_letters_parent_delivery_and_incident_close():
    c, _Session = _client()

    def send(path, body=None, method="post"):
        return getattr(c, method)(path, json=body or {}, headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})

    try:
        assert send("/api/register", {
            "school_name": "Setup School", "slug": "setup-school",
            "email": "admin@setup.test", "password": "demo-password-123456"
        }).status_code == 201

        status = c.get("/api/onboarding/status").json()
        assert status["required_total"] >= 5
        assert status["complete"] is False
        # Auto: school profile + staff + eventually learners/offences
        assert any(x["id"] == "school_profile" and x["completed"] for x in status["items"])

        assert send("/api/settings/academic", {
            "academic_year": 2026, "term": 1, "school_contact_email": "office@setup.test"}, "put").status_code == 200
        assert send("/api/settings", {
            "repeat_threshold": 3, "repeat_window_days": 30,
            "repeat_similar_threshold": 2, "repeat_total_threshold": 5,
            "follow_up_default_days": 7,
            "incident_prefix": "INC", "case_prefix": "CASE", "admission_prefix": "ADM"}, "put").status_code == 200

        learner = send("/api/learners", {
            "admission_no": "S1", "first_name": "Sipho", "surname": "Dlamini",
            "grade": "3", "class_name": "3A"}).json()
        offence = send("/api/offences", {
            "code": "B1", "name": "Disruption", "category": "Behaviour", "severity": 2}).json()
        coc = send("/api/conduct-versions", {
            "version_label": "v1", "title": "Code", "effective_from": "2026-01-01T00:00:00+00:00",
            "body": "Respect and safety."}).json()
        assert send(f"/api/conduct-versions/{coc['id']}/approve", {}, "patch").status_code == 200
        tpl = send("/api/letter-templates", {
            "code": "NOTICE", "name": "Parent notice",
            "body": "Dear guardian of {{learner_name}} ({{grade}} {{class_name}}) at {{school}} on {{date}}."
        }).json()

        status = c.get("/api/onboarding/status").json()
        assert status["complete"] is True, status
        assert status["progress_percent"] == 100

        # Letter document draft → approve (PDF) → deliver (manual without SMTP)
        letter = send("/api/letter-documents", {
            "template_id": tpl["id"], "learner_id": learner["id"],
            "title": "Behaviour notice", "body": "placeholder body text here"})
        assert letter.status_code == 201, letter.text
        lid = letter.json()["id"]
        assert send(f"/api/letter-documents/{lid}/approve").status_code == 200
        pdf = c.get(f"/api/letter-documents/{lid}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content[:5] == b"%PDF-"
        delivered = send(f"/api/letter-documents/{lid}/deliver", {
            "email": "guardian@example.test", "channel": "email"})
        assert delivered.status_code == 200, delivered.text
        assert delivered.json().get("manual") is True or delivered.json().get("queued") is True \
            or delivered.json()["status"] in ("approved", "delivered", "queued")

        # Parent notice delivery tracking + resend
        invite = send("/api/parent-portal/invite", {
            "learner_id": learner["id"], "email": "parent@example.test",
            "subject": "Meeting request"})
        assert invite.status_code == 201, invite.text
        inv = invite.json()
        assert inv["delivery_status"] in ("manual", "emailed", "queued")
        assert inv["delivery_attempts"] == 1
        notices = c.get("/api/parent-portal/notices").json()
        assert notices[0]["delivery_attempts"] >= 1
        assert notices[0]["can_resend"] is True
        resent = send(f"/api/parent-portal/notices/{inv['id']}/resend")
        assert resent.status_code == 200, resent.text
        assert resent.json()["delivery_attempts"] == 2

        # Incident closure checklist blocks resolve without notes; allows after notes
        incident = send("/api/incidents", {
            "learner_id": learner["id"], "offence_id": offence["id"],
            "location": "Classroom", "description": "Talking during lesson",
            "immediate_action": "Verbal reminder"}).json()
        ck = c.get(f"/api/incidents/{incident['id']}/closure-checklist").json()
        assert ck["ready_to_close"] is False
        blocked = send(f"/api/incidents/{incident['id']}/review", {
            "status": "resolved", "notes": ""}, "patch")
        assert blocked.status_code == 409, blocked.text
        # Verify first so review path works, then resolve with notes
        assert send(f"/api/incidents/{incident['id']}/review", {
            "status": "verified", "notes": "Confirmed"}, "patch").status_code == 200
        closed = send(f"/api/incidents/{incident['id']}/review", {
            "status": "resolved", "notes": "Support conversation completed"}, "patch")
        assert closed.status_code == 200, closed.text

        pdf_bytes = render_simple_pdf("Title", "Body line\nSecond line")
        assert pdf_bytes.startswith(b"%PDF-")
        assert b"Title" in pdf_bytes
    finally:
        main.app.dependency_overrides.clear()
