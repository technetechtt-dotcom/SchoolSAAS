"""MFA recovery codes, security events, admin MFA reset, guardian inbox."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "account-security-secret-key-32chars!")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.pop("PLATFORM_ADMIN_EMAILS", None)
os.environ.pop("BILLING_GATEWAY", None)
os.environ.pop("BILLING_WEBHOOK_SECRET", None)

from app import main
from app import pilot_pack, operations, extended, session_security, account_security  # noqa: F401
from tests.conftest import finish_required_onboarding


def test_mfa_recovery_security_events_and_parent_inbox():
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
            "school_name": "Secure School", "slug": "secure-school",
            "email": "admin@secure.test", "password": "demo-password-123456"
        }).status_code == 201

        # Login creates a security event
        events = c.get("/api/security/events").json()
        # register issues token without login_success; sign out and login
        send("/api/logout")
        assert send("/api/login", {
            "school_slug": "secure-school", "email": "admin@secure.test",
            "password": "demo-password-123456"}).status_code == 200
        events = c.get("/api/security/events").json()
        assert any(x["event_type"] == "login_success" for x in events)

        # MFA setup + enable returns recovery codes
        setup = send("/api/mfa/setup")
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        import pyotp
        code = pyotp.TOTP(secret).now()
        enabled = send("/api/mfa/enable", {"code": code})
        assert enabled.status_code == 200, enabled.text
        codes = enabled.json()["recovery_codes"]
        assert len(codes) == 10
        status = c.get("/api/mfa/recovery-status").json()
        assert status["mfa_enabled"] is True
        assert status["recovery_codes_remaining"] == 10

        # Login requires MFA; recovery code works once
        send("/api/logout")
        login = send("/api/login", {
            "school_slug": "secure-school", "email": "admin@secure.test",
            "password": "demo-password-123456"}).json()
        assert login.get("mfa_required") is True
        recovered = send("/api/mfa/verify-recovery", {
            "mfa_token": login["mfa_token"], "recovery_code": codes[0]})
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["recovery_codes_remaining"] == 9
        # Same code cannot be reused
        send("/api/logout")
        login2 = send("/api/login", {
            "school_slug": "secure-school", "email": "admin@secure.test",
            "password": "demo-password-123456"}).json()
        reuse = send("/api/mfa/verify-recovery", {
            "mfa_token": login2["mfa_token"], "recovery_code": codes[0]})
        assert reuse.status_code == 401
        # Authenticator still works
        ok = send("/api/mfa/verify-login", {
            "mfa_token": login2["mfa_token"], "code": pyotp.TOTP(secret).now()})
        assert ok.status_code == 200, ok.text

        # Invite educator and admin-reset MFA after they enable it
        inv = send("/api/invitations", {
            "email": "teacher@secure.test", "role": "educator", "assigned_class": "1A"}).json()
        assert send("/api/invitations/accept", {
            "token": inv["token"], "password": "demo-password-123456"}).status_code == 201
        members = c.get("/api/members").json()
        teacher = next(x for x in members if x["email"] == "teacher@secure.test")
        # Teacher enables MFA in separate client
        c2 = TestClient(main.app)
        def send2(path, body=None, method="post"):
            return getattr(c2, method)(path, json=body or {}, headers={"X-CSRF-Token": c2.cookies.get("csrf_token", "")})
        assert send2("/api/login", {
            "school_slug": "secure-school", "email": "teacher@secure.test",
            "password": "demo-password-123456"}).status_code == 200
        tsetup = send2("/api/mfa/setup").json()
        tenable = send2("/api/mfa/enable", {"code": pyotp.TOTP(tsetup["secret"]).now()})
        assert tenable.status_code == 200
        assert c2.get("/api/me").json()["mfa_enabled"] is True
        reset = send(f"/api/members/{teacher['id']}/mfa-reset", {"reason": "Lost phone — verified in person"})
        assert reset.status_code == 200, reset.text
        assert c2.get("/api/me").json()["authenticated"] is False  # sessions revoked

        # Parent inbox via token
        learner = send("/api/learners", {
            "admission_no": "SEC1", "first_name": "Aneesa", "surname": "Pillay",
            "grade": "2", "class_name": "2A"}).json()
        send("/api/offences", {"code": "S1", "name": "Support", "category": "Behaviour", "severity": 1})
        finish_required_onboarding(c, send)
        invite = send("/api/parent-portal/invite", {
            "learner_id": learner["id"], "email": "guardian@secure.test",
            "subject": "Meeting about support plan"})
        assert invite.status_code == 201, invite.text
        token = invite.json()["token"]
        inbox = c.get(f"/api/parent-portal/inbox?token={token}").json()
        assert inbox["email"] == "guardian@secure.test"
        assert inbox["items"][0]["subject"] == "Meeting about support plan"
        assert inbox["items"][0]["can_acknowledge"] is True
    finally:
        main.app.dependency_overrides.clear()
