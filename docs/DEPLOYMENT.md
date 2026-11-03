# Database migrations and deployment

For a fresh development database, set DATABASE_URL and JWT_SECRET, then run `alembic upgrade head`.

For an existing populated database, first back up and verify the database. The initial revision is a schema baseline, not an automatic upgrade of historical databases. Reconcile older schemas before stamping the baseline.

To prevent automatic table creation at API startup, set SCHEMA_AUTO_CREATE=false. Use COOKIE_SECURE=true only behind HTTPS.

Copy `.env.example` and set SMTP_* + APP_PUBLIC_URL for recovery, staff invite email and parent notices. Set PLATFORM_ADMIN_EMAILS for `/api/platform/*`.

Backup helper (verify restores separately):

    set DATABASE_URL=...
    python scripts/backup_db.py

Optional Postgres RLS sketch (reviewed apply only): `scripts/postgres_rls.sql`.

Not production-approved: school identity verification, payment gateway, PDF letter production, approved child-data handling, retention automation, and independent security testing still need implementation.
