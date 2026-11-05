"""Learner activity timeline, controlled CSV exports, onboarding soft-gates."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "activity-exports-secret-key-32chars!")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.pop("PLATFORM_ADMIN_EMAILS", None)

from app import main
from app import pilot_pack, operations, extended, letter_workflow, learner_activity, onboarding  # noqa: F401
from tests.conftest import finish_required_onboarding


def test_activity_exports_and_onboarding_gate():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(engine, expire_on_commit=False)
    main.Base.metadata.create_all(engine)

    def override_db():
        with Session() as s:
            yield s

    main.app.dependency_overrides[main.db] = override_db
    c = TestClient(main.app)

    def send(path, body=None, method="post"):
        return getattr(c, method)(path, json=body or {}, headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})

    try:
        assert send("/api/register", {
            "school_name": "Activity School", "slug": "activity-school",
            "email": "admin@activity.test", "password": "demo-password-123456"
        }).status_code == 201
        learner = send("/api/learners", {
            "admission_no": "A100", "first_name": "Neo", "surname": "Botha",
            "grade": "4", "class_name": "4B"}).json()
        offence = send("/api/offences", {
            "code": "D1", "name": "Disruption", "category": "Behaviour", "severity": 2}).json()
        incident = send("/api/incidents", {
            "learner_id": learner["id"], "offence_id": offence["id"],
            "location": "Hall", "description": "Loud disruption", "immediate_action": "Redirect"}).json()

        # Gate blocks formal case before onboarding complete
        blocked = send("/api/cases", {
            "learner_id": learner["id"], "title": "Too early", "incident_ids": [incident["id"]]})
        assert blocked.status_code == 409, blocked.text

        finish_required_onboarding(c, send)
        case = send("/api/cases", {
            "learner_id": learner["id"], "title": "Support plan",
            "incident_ids": [incident["id"]]})
        assert case.status_code == 201, case.text
        send(f"/api/cases/{case.json()['id']}/timeline", {
            "kind": "decision", "note": "Support conversation agreed"})
        send("/api/interventions", {
            "incident_id": incident["id"], "type": "Check-in", "notes": "Weekly"})
        send("/api/parent-contacts", {
            "learner_id": learner["id"], "method": "phone",
            "purpose": "Inform guardian", "outcome": "Reached"})

        activity = c.get(f"/api/learners/{learner['id']}/activity").json()
        kinds = {x["kind"] for x in activity["items"]}
        assert "incident" in kinds
        assert "case" in kinds
        assert "case_note" in kinds or "intervention" in kinds or "parent_contact" in kinds
        assert activity["count"] >= 3

        exports = c.get("/api/reports/exports").json()
        assert len(exports["items"]) >= 4
        for path in ("/api/reports/incidents.csv", "/api/reports/learners.csv",
                     "/api/reports/cases.csv", "/api/reports/interventions.csv"):
            resp = c.get(path)
            assert resp.status_code == 200, path
            assert "text/csv" in resp.headers["content-type"]
            assert "no-store" in resp.headers.get("cache-control", "")
            body = resp.text
            assert not any(line.lstrip().startswith("=") for line in body.splitlines()[1:] if line)
    finally:
        main.app.dependency_overrides.clear()
