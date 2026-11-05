"""Regression for hearings attendance, placements, appeals-hearing link and intervention due dates."""
import os
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "lifecycle-tranche-secret-key-32chars")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from app import main
from app import pilot_pack, operations, extended  # noqa: F401


def test_hearings_placements_appeals_and_intervention_due():
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
        os.environ["PLATFORM_ADMIN_EMAILS"] = "admin@life.test"
        assert send("/api/register", {
            "school_name": "Life School", "slug": "life-school",
            "email": "admin@life.test", "password": "demo-password-123456"
        }).status_code == 201
        learner = send("/api/learners", {
            "admission_no": "L1", "first_name": "Lindi", "surname": "Mokoena",
            "grade": "4", "class_name": "4A"}).json()
        place = send(f"/api/learners/{learner['id']}/placements", {
            "grade": "5", "class_name": "5B", "reason": "promotion",
            "notes": "Promoted with support plan", "effective_on": "2026-01-15"})
        assert place.status_code == 201, place.text
        hist = c.get(f"/api/learners/{learner['id']}/placements").json()
        assert len(hist) == 1 and hist[0]["reason"] == "promotion"
        assert c.get(f"/api/learners/{learner['id']}").json()["grade"] == "5"

        offence = send("/api/offences", {
            "code": "X1", "name": "Disruption", "category": "Behaviour", "severity": 2}).json()
        incident = send("/api/incidents", {
            "learner_id": learner["id"], "offence_id": offence["id"],
            "location": "Classroom", "description": "Demo", "immediate_action": "Talk"}).json()
        case = send("/api/cases", {
            "learner_id": learner["id"], "title": "Support",
            "incident_ids": [incident["id"]]}).json()
        hearing = send("/api/hearings", {
            "case_id": case["id"], "scheduled_at": "2026-03-01T09:00:00+00:00",
            "chair": "Principal", "participants": "SMT panel", "notes": "Scheduled"}).json()
        assert send(f"/api/hearings/{hearing['id']}", {
            "status": "completed", "outcome": "Support plan"}, "patch").status_code == 422
        done = send(f"/api/hearings/{hearing['id']}", {
            "status": "completed", "outcome": "Support plan approved",
            "participants": "Principal, guardian, learner",
            "attendance_notes": "All present",
            "procedural_checks": "Notice issued; learner heard"}, "patch")
        assert done.status_code == 200, done.text
        detail = c.get(f"/api/hearings/{hearing['id']}").json()
        assert detail["attendance_notes"] == "All present"

        appeal = send("/api/appeals", {
            "case_id": case["id"], "hearing_id": hearing["id"],
            "reason": "Request review of outcome timing"})
        assert appeal.status_code == 201, appeal.text
        assert c.get("/api/appeals").json()[0]["hearing_id"] == hearing["id"]

        due = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        iv = send("/api/interventions", {
            "incident_id": incident["id"], "type": "Monitoring",
            "notes": "Weekly check", "due_at": due})
        assert iv.status_code == 201
        warn = c.get("/api/analytics/early-warning").json()
        assert warn["counts"]["overdue_interventions"] >= 1
        assert any(x["id"] == iv.json()["id"] for x in warn["overdue_interventions"])
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        assert send(f"/api/interventions/{iv.json()['id']}", {
            "outcome": "follow_up", "notes": "Rescheduled", "due_at": future}, "patch").status_code == 200
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
