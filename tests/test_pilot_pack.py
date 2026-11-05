"""Regression coverage for v0.6 pilot foundation features."""
import os
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["JWT_SECRET"] = "pilot-pack-test-secret-key-32chars"
os.environ["SCHEMA_AUTO_CREATE"] = "true"
os.environ["MFA_ENCRYPTION_KEY"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
os.environ["PLATFORM_ADMIN_EMAILS"] = "admin@school.test"
os.environ.pop("SMTP_HOST", None)

from app import main
from app import pilot_pack  # noqa: F401
import pyotp


def test_pilot_pack_mfa_conduct_hearing_billing_platform(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(engine, expire_on_commit=False)
    main.Base.metadata.create_all(engine)

    def override_db():
        with TestingSession() as s:
            yield s

    main.app.dependency_overrides[main.db] = override_db
    c = TestClient(main.app)

    def send(path, body=None, method="post"):
        return getattr(c, method)(path, json=body or {}, headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})

    try:
        assert send("/api/register", {
            "school_name": "Pilot School", "slug": "pilot-school",
            "email": "admin@school.test", "password": "demo-password-123456"
        }).status_code == 201
        me = c.get("/api/me").json()
        assert me["authenticated"] is True
        assert me["platform_admin"] is True

        setup = send("/api/mfa/setup", {})
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        code = pyotp.TOTP(secret).now()
        assert send("/api/mfa/enable", {"code": code}).status_code == 200

        send("/api/logout", {})
        login = send("/api/login", {
            "school_slug": "pilot-school", "email": "admin@school.test",
            "password": "demo-password-123456"})
        assert login.status_code == 200
        assert login.json()["mfa_required"] is True
        pending = login.json()["mfa_token"]
        assert c.get("/api/me").json()["authenticated"] is False
        verify = send("/api/mfa/verify-login", {
            "mfa_token": pending, "code": pyotp.TOTP(secret).now()})
        assert verify.status_code == 200
        assert c.get("/api/me").json()["authenticated"] is True

        conduct = send("/api/conduct-versions", {
            "version_label": "2026.1", "title": "Code of Conduct",
            "body": "Respectful behaviour is required at all times.",
            "effective_from": "2026-01-01T00:00:00+00:00"})
        assert conduct.status_code == 201
        vid = conduct.json()["id"]
        assert send(f"/api/conduct-versions/{vid}/approve", {}, "patch").status_code == 200

        learner = send("/api/learners", {
            "admission_no": "A1", "first_name": "Ann", "surname": "Bee",
            "grade": "4", "class_name": "4A"})
        assert learner.status_code == 201
        offence = send("/api/offences", {
            "code": "L1", "name": "Late", "category": "punctuality", "severity": 1})
        assert offence.status_code == 201
        incident = send("/api/incidents", {
            "learner_id": learner.json()["id"], "offence_id": offence.json()["id"],
            "location": "Classroom", "description": "Arrived late",
            "immediate_action": "Verbal correction"})
        assert incident.status_code == 201
        case = send("/api/cases", {
            "learner_id": learner.json()["id"], "title": "Punctuality support",
            "incident_ids": [incident.json()["id"]]})
        assert case.status_code == 201
        hearing = send("/api/hearings", {
            "case_id": case.json()["id"], "scheduled_at": "2026-02-01T10:00:00+00:00",
            "chair": "Principal", "notes": "Supportive discussion"})
        assert hearing.status_code == 201

        up = c.post("/api/evidence",
                    data={"incident_id": str(incident.json()["id"])},
                    files={"file": ("note.txt", b"evidence note", "text/plain")},
                    headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})
        assert up.status_code == 201

        tpl = send("/api/letter-templates", {
            "code": "parent-note", "name": "Parent note",
            "body": "Dear guardian of {{learner_name}} in {{grade}}/{{class_name}} at {{school}} on {{date}}."})
        assert tpl.status_code == 201
        rendered = c.post(f"/api/letter-templates/{tpl.json()['id']}/render",
                          params={"learner_id": learner.json()["id"]},
                          headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})
        assert rendered.status_code == 200
        assert "Ann Bee" in rendered.json()["rendered_text"]

        invite = send("/api/parent-portal/invite", {
            "learner_id": learner.json()["id"], "email": "parent@example.test",
            "subject": "Notice"})
        assert invite.status_code == 201
        assert "token" in invite.json()
        ack = send("/api/parent-portal/acknowledge", {
            "token": invite.json()["token"], "subject": "Notice"})
        assert ack.status_code == 200

        inv = send("/api/billing/invoices", {"amount_cents": 25000, "description": "Trial"})
        assert inv.status_code == 201
        assert send(f"/api/billing/invoices/{inv.json()['id']}/mark-paid", {}).status_code == 200

        assert c.get("/api/privacy/status").json()["popia_assessment_complete"] is False
        assert send("/api/privacy/retention", {
            "record_type": "incidents", "retain_days": 2555, "notes": "placeholder"}, "put").status_code == 200

        schools = c.get("/api/platform/schools")
        assert schools.status_code == 200
        assert len(schools.json()) >= 1
        assert c.get("/api/platform/health").status_code == 200
        blocked = c.delete("/api/audit/1", headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})
        assert blocked.status_code == 405
    finally:
        main.app.dependency_overrides.clear()
