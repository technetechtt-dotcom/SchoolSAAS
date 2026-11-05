"""Isolate mutable environment variables between test modules and cases."""
from __future__ import annotations
import os
import pytest

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
