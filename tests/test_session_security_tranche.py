"""Staff invite resend/revoke, session self-management, document approval."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "session-security-secret-key-32chars!")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.pop("PLATFORM_ADMIN_EMAILS", None)
os.environ.pop("BILLING_GATEWAY", None)
os.environ.pop("BILLING_WEBHOOK_SECRET", None)

from app import main
from app import pilot_pack, operations, extended, session_security  # noqa: F401


def test_invites_sessions_and_document_approval():
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
            "school_name": "Session School", "slug": "session-school",
            "email": "admin@session.test", "password": "demo-password-123456"
        }).status_code == 201

        # Document approval
        learner = send("/api/learners", {
            "admission_no": "SS1", "first_name": "Thabo", "surname": "Nair",
            "grade": "6", "class_name": "6A"}).json()
        doc = send("/api/documents", {
            "learner_id": learner["id"], "title": "Support letter",
            "body": "Draft support letter content.", "document_type": "letter"})
        assert doc.status_code == 201, doc.text
        did = doc.json()["id"]
        assert c.get("/api/documents").json()[0]["status"] == "draft"
        assert send(f"/api/documents/{did}/approve").status_code == 200
        assert c.get(f"/api/documents/{did}").json()["status"] == "approved"
        assert send(f"/api/documents/{did}/approve").status_code == 409
        assert send(f"/api/documents/{did}/archive").status_code == 200
        assert c.get(f"/api/documents/{did}").json()["status"] == "archived"

        # Staff invite list / resend / revoke
        inv = send("/api/invitations", {
            "email": "teacher@session.test", "role": "educator", "assigned_class": "6A"})
        assert inv.status_code == 201, inv.text
        invite = inv.json()
        assert invite["delivery_attempts"] == 1
        assert invite.get("token")  # SMTP off → manual token
        listed = c.get("/api/invitations").json()
        assert listed[0]["status"] == "pending" and listed[0]["can_resend"]
        resent = send(f"/api/invitations/{invite['id']}/resend")
        assert resent.status_code == 200, resent.text
        assert resent.json()["delivery_attempts"] == 2
        assert send(f"/api/invitations/{invite['id']}/revoke").status_code == 200
        assert c.get("/api/invitations").json()[0]["status"] == "revoked"
        # Old token must fail after revoke
        bad = send("/api/invitations/accept", {
            "token": invite["token"], "password": "demo-password-123456"})
        assert bad.status_code == 400

        # Fresh invite still acceptable
        inv2 = send("/api/invitations", {
            "email": "hod@session.test", "role": "hod"}).json()
        ok = send("/api/invitations/accept", {
            "token": inv2["token"], "password": "demo-password-123456"})
        assert ok.status_code == 201, ok.text

        # Sessions: current device listed; revoke-others with only one session
        sessions = c.get("/api/sessions").json()
        assert sessions["count"] >= 1
        assert any(x["current"] for x in sessions["items"])
        other = send("/api/sessions/revoke-others")
        assert other.status_code == 200
        assert other.json()["revoked"] == 0
        # Cannot revoke current session via id endpoint
        current_id = next(x["id"] for x in c.get("/api/sessions").json()["items"] if x["current"])
        assert send(f"/api/sessions/{current_id}/revoke").status_code == 400
    finally:
        main.app.dependency_overrides.clear()
