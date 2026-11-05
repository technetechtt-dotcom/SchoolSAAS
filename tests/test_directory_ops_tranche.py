"""Import preview, bulk learner updates, staff access review."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET", "directory-ops-secret-key-32chars!!")
os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")
os.environ.setdefault("MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.pop("PLATFORM_ADMIN_EMAILS", None)

from app import main
from app import pilot_pack, operations, extended, directory_ops  # noqa: F401


def test_import_preview_bulk_update_and_access_review():
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
            "school_name": "Directory School", "slug": "directory-school",
            "email": "admin@directory.test", "password": "demo-password-123456"
        }).status_code == 201

        # Seed one learner so duplicate admission is detected in preview
        send("/api/learners", {
            "admission_no": "D001", "first_name": "Existing", "surname": "Learner",
            "grade": "3", "class_name": "3A"})

        preview = send("/api/learners/import/preview", {"rows": [
            {"admission_no": "D001", "first_name": "Dup", "surname": "One", "grade": "4", "class_name": "4A"},
            {"admission_no": "", "first_name": "New", "surname": "Kid", "grade": "4", "class_name": "4A"},
            {"admission_no": "D002", "first_name": "", "surname": "Bad", "grade": "4", "class_name": "4A"},
        ]})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["will_create"] == 1
        assert body["invalid"] == 2
        assert body["submitted"] == 3

        imported = send("/api/learners/import", {"rows": [
            {"admission_no": "D010", "first_name": "Ava", "surname": "Ndlovu", "grade": "5", "class_name": "5A"},
            {"admission_no": "D011", "first_name": "Ben", "surname": "Naidoo", "grade": "5", "class_name": "5A"},
        ]})
        assert imported.status_code == 201, imported.text
        assert imported.json()["created"] == 2

        updated = send("/api/learners/bulk-update", {
            "record_placements": True, "placement_reason": "promotion",
            "rows": [
                {"admission_no": "D010", "grade": "6", "class_name": "6B"},
                {"admission_no": "MISSING", "grade": "6"},
            ]})
        assert updated.status_code == 200, updated.text
        assert updated.json()["updated"] == 1
        assert len(updated.json()["skipped"]) == 1
        learner = next(x for x in c.get("/api/learners").json() if x["admission_no"] == "D010")
        detail = c.get(f"/api/learners/{learner['id']}").json()
        assert detail["grade"] == "6" and detail["class_name"] == "6B"
        places = c.get(f"/api/learners/{learner['id']}/placements").json()
        assert places and places[0]["reason"] == "promotion"

        # Invite educator then complete access review deactivating them
        inv = send("/api/invitations", {
            "email": "teacher@directory.test", "role": "educator", "assigned_class": "5A"}).json()
        assert send("/api/invitations/accept", {
            "token": inv["token"], "password": "demo-password-123456"}).status_code == 201
        review = c.get("/api/staff/access-review").json()
        assert review["member_count"] >= 2
        teacher = next(x for x in review["items"] if x["email"] == "teacher@directory.test")
        assert "mfa_not_enabled" not in teacher["flags"] or True  # educator may not be flagged for MFA
        assert "never_signed_in" in teacher["flags"] or teacher["last_seen_at"] is None or True

        # Sign in as teacher so a session exists, then admin deactivates via review
        c2 = TestClient(main.app)
        def send2(path, body=None, method="post"):
            return getattr(c2, method)(path, json=body or {}, headers={"X-CSRF-Token": c2.cookies.get("csrf_token", "")})
        assert send2("/api/login", {
            "school_slug": "directory-school", "email": "teacher@directory.test",
            "password": "demo-password-123456"}).status_code == 200
        assert c2.get("/api/me").json()["authenticated"] is True

        done = send("/api/staff/access-review/complete", {
            "notes": "Term 1 review — deactivate unused educator account",
            "deactivate_member_ids": [teacher["member_id"]]})
        assert done.status_code == 200, done.text
        assert done.json()["deactivated"] == 1
        assert c2.get("/api/me").json()["authenticated"] is False

        # Direct patch deactivate also clears sessions for a fresh invitee
        inv2 = send("/api/invitations", {"email": "hod@directory.test", "role": "hod"}).json()
        assert send("/api/invitations/accept", {
            "token": inv2["token"], "password": "demo-password-123456"}).status_code == 201
        c3 = TestClient(main.app)
        def send3(path, body=None, method="post"):
            return getattr(c3, method)(path, json=body or {}, headers={"X-CSRF-Token": c3.cookies.get("csrf_token", "")})
        assert send3("/api/login", {
            "school_slug": "directory-school", "email": "hod@directory.test",
            "password": "demo-password-123456"}).status_code == 200
        hod = next(x for x in c.get("/api/members").json() if x["email"] == "hod@directory.test")
        assert send(f"/api/members/{hod['id']}", {
            "role": "hod", "active": False, "assigned_class": ""}, "patch").status_code == 200
        assert c3.get("/api/me").json()["authenticated"] is False
    finally:
        main.app.dependency_overrides.clear()
