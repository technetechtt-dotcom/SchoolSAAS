# Database migrations and deployment

For a fresh development database, set DATABASE_URL and JWT_SECRET, then run `alembic upgrade head`.

For an existing populated database, first back up and verify the database. The initial revision is a schema baseline, not an automatic upgrade of historical databases. Reconcile older schemas before stamping the baseline.

To prevent automatic table creation at API startup, set SCHEMA_AUTO_CREATE=false. Use COOKIE_SECURE=true only behind HTTPS.

Not production-approved: school identity verification, MFA, approved child-data handling, retention rules, and security testing still need implementation.
