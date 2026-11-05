"""Fail-closed local release preflight: checks configuration, not legal approval.

The script must be run with the exact production environment and database
credentials before attempting an operator-reviewed deployment.
"""
import os,sys
from urllib.parse import urlparse
from cryptography.fernet import Fernet

def issues(env):
    errors=[]
    url=env.get("DATABASE_URL","")
    if not url.startswith(("postgresql://","postgresql+psycopg://")):
        errors.append("DATABASE_URL must point to managed PostgreSQL")
    if env.get("COOKIE_SECURE","").lower()!="true":
        errors.append("COOKIE_SECURE must be true")
    if env.get("SCHEMA_AUTO_CREATE","").lower()!="false":
        errors.append("SCHEMA_AUTO_CREATE must be false; run migrations explicitly")
    if len(env.get("JWT_SECRET",""))<32 or "replace_" in env.get("JWT_SECRET",""):
        errors.append("JWT_SECRET must be a unique high-entropy key")
    key=env.get("MFA_ENCRYPTION_KEY","")
    try:Fernet(key.encode())
    except Exception:errors.append("MFA_ENCRYPTION_KEY must be a valid independent Fernet key")
    endpoint=env.get("APP_PUBLIC_URL","")
    parsed=urlparse(endpoint)
    if parsed.scheme!="https" or not parsed.hostname:
        errors.append("APP_PUBLIC_URL must be a publicly resolvable HTTPS URL")
    if not env.get("PLATFORM_ADMIN_EMAILS",""):
        errors.append("Verified platform administrator contacts must be configured")
    if not env.get("EVIDENCE_UPLOAD_DIR","") or not env.get("LETTER_UPLOAD_DIR",""):
        errors.append("Durable evidence and letter storage paths must be configured")
    provider=env.get("BILLING_GATEWAY","none").lower()
    if provider=="sandbox":
        errors.append("Sandbox payments must not be enabled in production")
    if provider=="paystack":
        if not env.get("PAYSTACK_SECRET_KEY","").startswith("sk_live_"):
            errors.append("Paystack production requires a live merchant secret key")
        if not env.get("PAYSTACK_WEBHOOK_SECRET","").startswith("whsec_"):
            errors.append("Paystack production requires a webhook signing secret")
    elif provider not in ("none",""):
        errors.append("Unsupported live payment gateway")
    return errors

if __name__=="__main__":
    failures=issues(os.environ)
    if failures:
        for failure in failures:print("BLOCK:",failure,file=sys.stderr)
        sys.exit(1)
    print("Configuration preflight passed. External security, POPIA, migration, backup and merchant approvals still required.")
