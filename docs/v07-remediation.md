# SchoolSAAS v0.7 — security and workflow remediation

This release contains implementation work across five tracks. It is **not** a certification that the platform is production-ready for children's personal information.

## 1. Security and CI
- Password-recovery tests now patch the shared mailer after the refactor.
- Educator evidence uploads require ownership of the incident and access to the learner's assigned class; direct case evidence uploads are denied to educators.
- Evidence uploads enforce a bounded read and accepted MIME types.
- Sensitive learner journey and recommendation endpoints are limited to management; formal cognitive entries require a formal-assessment source and descriptive provenance.
- MFA secrets use Fernet encryption with a separately configured MFA_ENCRYPTION_KEY. Generate a fresh key in the deployment secret store, never in the repository.
- Existing *plaintext* MFA enrollments are not accepted after this change; a verified operator must arrange secure reset and re-enrollment. Old tokens/sessions are not migrated automatically.

## 2. Database and privacy
- The Alembic baseline now refuses to run against a populated database. Reconcile historical schemas in staging before any upgrade.
- Later revisions widen the MFA secret column and add notice-subject and privacy-request storage.
- PostgreSQL app transactions set a school-specific RLS context; the context is reapplied on new transactions. A revised optional scripts/postgres_rls.sql includes FORCE RLS and both read and write policies for the six core tables. The script is **not automatically deployed**.
- Added identity-gated, school-scoped data-subject request intake and review, with no automatic record disclosure/deletion.
- Legal basis, POPIA obligations, retention and erasure rules, qualified assessment provenance, and coverage for all database tables need independent review.

## 3. Disciplinary workflows
- Hearing statuses are validated, completed hearings require an explicit staff-written outcome, closed hearings cannot silently reopen, and changes are appended to the case timeline.
- Parent acknowledgment tokens are linked to the original school notice subject; a different subject is rejected.
- These controls do not replace hearing procedural safeguards, guardian identity verification, case evidence review or school-approved Code of Conduct mappings.

## 4. UI/UX and test coverage
- Fixed asynchronous navigation race in which a stale dashboard replaced the selected page.
- Expanded Playwright browser smoke coverage to school operations, reports, staff, security, privacy and billing pages.
- Added browser diagnostics, scoped evidence tests, privacy request tests, and extra billing/MFA/hearing assertions.
- Personal MFA settings are available to every authenticated staff role.
- Full accessibility, device, load, penetration and end-to-end test matrices are still outstanding.

## 5. Commercial SaaS
- Manual invoice reconciliation requires platform operator authorisation and cannot activate a subscription.
- This is **not a live payment integration**. No gateway, verified webhooks, automated tax invoices, refunds, recurring subscriptions or settlement reconciliation is implemented. Select a payment provider and connect merchant credentials before claiming live billing.

## Deployment checklist
1. Back up and verify a restore from the actual existing database.
2. Run migrations against a staging clone first. Never run the baseline on an existing populated database.
3. Configure SMTP, JWT_SECRET, TLS/COOKIE_SECURE, SCHEMA_AUTO_CREATE=false, and a strong independently generated MFA_ENCRYPTION_KEY.
4. Review/re-enrol legacy plaintext MFA users; test account recovery and tenant isolation.
5. Deploy vetted PostgreSQL RLS only after testing all request paths and connection identities. Expand policies to all sensitive tables.
6. Run GitHub Actions, PostgreSQL-specific integration tests, privacy impact assessment and independent security review.
7. Do not load real learner disciplinary, cognitive or wellbeing data until the necessary controls and school approvals are in place.
