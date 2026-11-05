"""Isolate mutable environment variables between test modules and cases."""
from __future__ import annotations
import os
import pytest

def finish_required_onboarding(client, send):
    """Complete required auto-detected onboarding steps for gated formal workflows.

    Caller must already have at least one learner and one offence at the school.
    """
    assert send("/api/settings/academic", {
        "academic_year": 2026, "term": 1, "school_contact_email": "office@test.local"
    }, "put").status_code == 200
    assert send("/api/settings", {
        "repeat_threshold": 3, "repeat_window_days": 30,
        "repeat_similar_threshold": 2, "repeat_total_threshold": 5,
        "follow_up_default_days": 7,
        "incident_prefix": "INC", "case_prefix": "CASE", "admission_prefix": "ADM"
    }, "put").status_code == 200
    status = client.get("/api/onboarding/status").json()
    if not any(x["id"] == "code_of_conduct" and x["completed"] for x in status["items"]):
        coc = send("/api/conduct-versions", {
            "version_label": "v1", "title": "Code of Conduct",
            "effective_from": "2026-01-01T00:00:00+00:00",
            "body": "Respect, safety and fairness."
        })
        assert coc.status_code == 201, coc.text
        assert send(f"/api/conduct-versions/{coc.json()['id']}/approve", {}, "patch").status_code == 200
    status = client.get("/api/onboarding/status").json()
    assert status["complete"] is True, status


_ENV_KEYS = (
    "JWT_SECRET",
    "DATABASE_URL",
    "PLATFORM_ADMIN_EMAILS",
    "BILLING_GATEWAY",
    "BILLING_WEBHOOK_SECRET",
    "MFA_ENCRYPTION_KEY",
    "SCHEMA_AUTO_CREATE",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "COOKIE_SECURE",
    "EVIDENCE_UPLOAD_DIR",
    "EVIDENCE_MAX_BYTES",
)

# Safe defaults for every test unless the test itself overrides them.
_SAFE_DEFAULTS = {
    "BILLING_GATEWAY": "none",
    "BILLING_WEBHOOK_SECRET": "",
}


@pytest.fixture(autouse=True)
def _isolate_process_env():
    """Snapshot env, apply safe defaults, restore after each test.

    Module-level os.environ writes at collection time must not leak billing/platform
    configuration across unrelated tests.
    """
    before = {k: os.environ.get(k) for k in _ENV_KEYS}
    for key, value in _SAFE_DEFAULTS.items():
        if value == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
