"""Regression coverage for confirmed P0/P1 workflow repairs."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "workflow-repair-test-secret-key-32c")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
# Do not set PLATFORM_ADMIN_EMAILS / BILLING_* at import time — that pollutes sibling tests.
os.environ.pop("SMTP_HOST", None)

from app import main
from app import pilot_pack  # noqa: F401
from app import operations  # noqa: F401
from app import learner_journey  # noqa: F401
from tests.conftest import finish_required_onboarding
import pyotp


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(engine, expire_on_commit=False)
    main.Base.metadata.create_all(engine)

    def override_db():
        with TestingSession() as s:
            yield s

    main.app.dependency_overrides[main.db] = override_db
    return TestClient(main.app), TestingSession, engine


def test_parent_invite_token_notice_ack_dispute_and_evidence_download():
    c, TestingSession, engine = _client()

    def send(path, body=None, method="post"):
        return getattr(c, method)(path, json=body or {}, headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})

    try:
        os.environ["PLATFORM_ADMIN_EMAILS"] = "admin@repair.test"
        os.environ["BILLING_GATEWAY"] = "none"
        os.environ.pop("BILLING_WEBHOOK_SECRET", None)
        assert send("/api/register", {
            "school_name": "Repair School", "slug": "repair-school",
            "email": "admin@repair.test", "password": "demo-password-123456"
        }).status_code == 201
        learner = send("/api/learners", {
            "admission_no": "R1", "first_name": "Ria", "surname": "Molefe",
            "grade": "3", "class_name": "3A"}).json()
        offence = send("/api/offences", {
            "code": "B1", "name": "Disruption", "category": "Behaviour", "severity": 1}).json()
        incident = send("/api/incidents", {
            "learner_id": learner["id"], "offence_id": offence["id"],
            "location": "Classroom", "description": "Demo", "immediate_action": "Talk"}).json()
        finish_required_onboarding(c, send)

        invite = send("/api/parent-portal/invite", {
            "learner_id": learner["id"], "email": "guardian@example.test",
            "subject": "Behaviour support notice"}).json()
        assert invite["emailed"] is False
        assert invite["token"]
        assert invite["subject"] == "Behaviour support notice"

        notice = c.get("/api/parent-portal/notice", params={"token": invite["token"]})
        assert notice.status_code == 200
        assert notice.json()["subject"] == "Behaviour support notice"
        assert "Ria" in notice.json()["learner_name"]

        assert send("/api/parent-portal/acknowledge", {
            "token": invite["token"], "subject": "SchoolCare notice"}).status_code == 400
        assert send("/api/parent-portal/dispute", {
            "token": invite["token"], "reason": "Dates in the notice are incorrect"}).status_code == 201
        disputes = c.get("/api/parent-portal/disputes").json()
        assert len(disputes) >= 1
        assert send("/api/parent-portal/acknowledge", {
            "token": invite["token"], "subject": "Behaviour support notice"}).status_code == 200

        notices = c.get("/api/parent-portal/notices").json()
        assert any(n["status"] == "acknowledged" for n in notices)

        up = c.post("/api/evidence",
                    data={"incident_id": str(incident["id"])},
                    files={"file": ("note.txt", b"secure evidence body", "text/plain")},
                    headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})
        assert up.status_code == 201
        eid = up.json()["id"]
        dl = c.get(f"/api/evidence/{eid}/download?disposition=inline",
                   headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})
        assert dl.status_code == 200
        assert b"secure evidence body" in dl.content
        logs = c.get(f"/api/evidence/{eid}/access-log").json()
        assert logs and logs[0]["action"] == "view"

        # Letter render endpoint still returns draft text (UI must keep modal open)
        tpl = send("/api/letter-templates", {
            "code": "n1", "name": "Notice", "body": "Hello {{learner_name}}"}).json()
        rendered = c.post(f"/api/letter-templates/{tpl['id']}/render",
                          params={"learner_id": learner["id"]},
                          headers={"X-CSRF-Token": c.cookies.get("csrf_token", "")})
        assert rendered.status_code == 200
        assert "Ria Molefe" in rendered.json()["rendered_text"]

        # Class assignments expose educator email (not case-assignee-only)
        inv = send("/api/invitations", {
            "email": "teacher@repair.test", "role": "educator", "assigned_class": "3A"}).json()
        teacher = TestClient(main.app)
        assert teacher.post("/api/invitations/accept",
                            json={"token": inv["token"], "password": "teacher-password-123"},
                            headers={"X-CSRF-Token": teacher.cookies.get("csrf_token", "")}).status_code == 201
        members = c.get("/api/members").json()
        teacher_uid = next(x["user_id"] for x in members if x["email"] == "teacher@repair.test")
        assert send("/api/class-assignments", {"user_id": teacher_uid, "class_name": "3A"}).status_code == 201
        rows = c.get("/api/class-assignments").json()
        assert any(r["email"] == "teacher@repair.test" for r in rows)

        # Billing gateway checkout + webhook confirmation activates subscription
        os.environ["BILLING_GATEWAY"] = "sandbox"
        os.environ["BILLING_WEBHOOK_SECRET"] = "sandbox-webhook-secret-value"
        gw = c.get("/api/billing/gateway").json()
        assert gw["connected"] is True, gw
        inv_resp = send("/api/billing/invoices", {"amount_cents": 9900, "description": "Plan"})
        assert inv_resp.status_code == 201, inv_resp.text
        invc = inv_resp.json()
        checkout_resp = send(f"/api/billing/invoices/{invc['id']}/checkout", {})
        assert checkout_resp.status_code == 200, checkout_resp.text
        assert checkout_resp.json()["status"] == "awaiting_payment"
        pref = checkout_resp.json()["payment_ref"]
        assert send("/api/billing/webhooks/sandbox", {
            "invoice_id": invc["id"], "event": "payment.succeeded"}).status_code == 422
        bad_ref = c.post("/api/billing/webhooks/sandbox",
                         json={"invoice_id": invc["id"], "event": "payment.succeeded",
                               "external_ref": "wrong-ref", "school_id": c.get("/api/me").json()["sid"]},
                         headers={"X-CSRF-Token": c.cookies.get("csrf_token", ""),
                                  "X-Billing-Webhook-Secret": "sandbox-webhook-secret-value"})
        assert bad_ref.status_code == 409
        paid_resp = c.post("/api/billing/webhooks/sandbox",
                           json={"invoice_id": invc["id"], "event": "payment.succeeded",
                                 "external_ref": pref, "school_id": c.get("/api/me").json()["sid"]},
                           headers={"X-CSRF-Token": c.cookies.get("csrf_token", ""),
                                    "X-Billing-Webhook-Secret": "sandbox-webhook-secret-value"})
        assert paid_resp.status_code == 200, paid_resp.text
        paid = paid_resp.json()
        assert paid["status"] == "paid_gateway"
        assert paid["subscription_activated"] is True
        replay = c.post("/api/billing/webhooks/sandbox",
                        json={"invoice_id": invc["id"], "event": "payment.succeeded",
                              "external_ref": pref, "school_id": c.get("/api/me").json()["sid"]},
                        headers={"X-CSRF-Token": c.cookies.get("csrf_token", ""),
                                 "X-Billing-Webhook-Secret": "sandbox-webhook-secret-value"})
        assert replay.status_code == 200
        assert replay.json()["subscription_activated"] is False
        assert c.get("/api/subscription").json()["plan"] == "standard"

        # Case status PATCH cannot close without checklist
        case_early = send("/api/cases", {
            "learner_id": learner["id"], "title": "Early close attempt",
            "incident_ids": [incident["id"]]}).json()
        assert send(f"/api/cases/{case_early['id']}", {"status": "closed"}, "patch").status_code == 400

        # MFA enable refreshes status on /api/me
        setup = send("/api/mfa/setup", {}).json()
        code = pyotp.TOTP(setup["secret"]).now()
        assert send("/api/mfa/enable", {"code": code}).status_code == 200
        assert c.get("/api/me").json()["mfa_enabled"] is True

        # Case closure checklist
        case = send("/api/cases", {
            "learner_id": learner["id"], "title": "Support case",
            "incident_ids": [incident["id"]]}).json()
        check = c.get(f"/api/cases/{case['id']}/closure-checklist").json()
        assert check["ready_to_close"] is False
        assert send(f"/api/cases/{case['id']}/assign", {"assigned_user_id": c.get("/api/me").json()["uid"]}, "patch").status_code == 200
        assert send(f"/api/cases/{case['id']}/timeline", {
            "kind": "decision", "note": "Support plan approved by SMT"}).status_code == 201
        check2 = c.get(f"/api/cases/{case['id']}/closure-checklist").json()
        assert check2["ready_to_close"] is True
        assert send(f"/api/cases/{case['id']}/close", {}).status_code == 200
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
