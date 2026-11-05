"""Production configuration gates intentionally reject insecure/demo defaults."""
from scripts.release_preflight import issues
from cryptography.fernet import Fernet

def test_release_preflight_rejects_development_defaults():
    errors=issues({"DATABASE_URL":"sqlite:///demo.db","COOKIE_SECURE":"false",
        "SCHEMA_AUTO_CREATE":"true","BILLING_GATEWAY":"sandbox"})
    assert any("PostgreSQL" in error for error in errors)
    assert any("COOKIE_SECURE" in error for error in errors)
    assert any("Sandbox" in error for error in errors)

def test_release_preflight_accepts_valid_configuration_without_certifying_launch():
    config={"DATABASE_URL":"postgresql+psycopg://app:test@db:5432/schoolcare",
        "COOKIE_SECURE":"true","SCHEMA_AUTO_CREATE":"false",
        "JWT_SECRET":"fictional-unique-test-only-key-123456789",
        "MFA_ENCRYPTION_KEY":Fernet.generate_key().decode(),
        "APP_PUBLIC_URL":"https://example.test",
        "PLATFORM_ADMIN_EMAILS":"verified-admin@example.test",
        "EVIDENCE_UPLOAD_DIR":"/srv/storage/evidence",
        "LETTER_UPLOAD_DIR":"/srv/storage/letters","BILLING_GATEWAY":"none"}
    assert issues(config)==[]
    config["BILLING_GATEWAY"]="paystack"
    assert any("live merchant" in error for error in issues(config))
