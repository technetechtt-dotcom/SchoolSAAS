# SchoolCare SaaS — multi-school learner behaviour management

A runnable **proof-of-concept**, based on the Venus Primary learner discipline specification and Excel database prototype. **Not production-ready. Do not load identifiable children's data.**

## Included in v0.1
- Separate school organisations and configurable subscription-plan/status placeholders.
- School-scoped authenticated memberships with `school_admin`, `principal`, `smt`, `hod`, `educator` roles in data model.
- Password hashing (Argon2), signed short-lived HTTP-only session cookie.
- School-scoped learner directory, offence catalogue, incident reporting and repeat-count review flags.
- Case linking (one learner, multiple incidents), interventions, audit-event recording, simple dashboard.
- Responsive browser UI, REST API/OpenAPI at `/docs`, tenant-boundary test.

## Start locally using Docker
1. `cp .env.example .env`
2. Set random, strong `DB_PASSWORD` and `JWT_SECRET` (32+ random bytes), never commit `.env`.
3. `docker compose up --build`
4. Open http://localhost:8000 and create two demonstration school workspaces. Use **fake learner records only**.

For Python-only local use: `pip install -r requirements.txt`; set `JWT_SECRET` in your shell; `uvicorn app.main:app --reload` (defaults to disposable local SQLite). Run `pytest -q` to exercise tenant isolation.

## SaaS data model
Every school-owned record includes `school_id`; current membership is resolved from a server-signed token and checked in the database. All implemented queries filter by school. A membership cannot select an arbitrary tenant through a URL parameter. Postgres is the deployment database; SQLite is local-development-only.

## Critical gaps before a real school pilot
1. Secure **invitation/member provisioning**, role change approval, SSO/MFA, password reset, account deactivation, authentication rate limits and lockout, security alerts.
2. CSRF protection for cookie-authenticated writes; secure cookies behind TLS; reverse proxy security headers, strict CORS, session revocation, secrets vault.
3. Independently verified tenant access tests **on every resource and export**; Postgres row-level security as second layer; encryption, formal threat model and penetration testing.
4. Versioned **Alembic migrations** instead of `create_all`, audit durability/immutability, backup/restore tests, retention/deletion and transfer processes.
5. School-specific Code of Conduct versioning, offence-to-intervention approvals, review queues, time windows, serious-incident alerts and safeguards; no automated disciplinary sanctions.
6. Implement the remaining specification registers: parent communications, outcomes, documents, grade/class histories, appeal/reviews, follow-up tasks, settings, incident correction and case state transitions.
7. Enforce least-privilege incident/learner access down to phase/class/assignment: currently educators see a broad learner lookup, while case/report access is restricted.
8. Typed validation, race-safe unique ID generation, pagination/search, async jobs, observability, alerts, accessibility and mobile E2E tests.
9. Subscription provisioning, payment provider, invoices/VAT, quotas, trial expiry and lifecycle management. Current `plan` field is **only a placeholder**.
10. Privacy impact assessment, POPIA lawful-basis assessment for children, operator agreements, school contracts, incident-response procedure, appropriate retention, data subject request handling and legal review before personal data processing.

## Product roadmap
- **Phase A**: Foundation + tenant and permission hardening.
- **Phase B**: Workflow parity with the supplied specification (case lifecycle, escalation, support plans, letters, reports).
- **Phase C**: Commercial features (school onboarding, billing, independent tenant admin, support, SLAs, migrations).
- **Phase D**: Multi-region architecture, optional SSO, parent portal, analytics and approved AI-assisted drafting with human review.

## Specification mapping
`Learners` → learner directory; `Offences` → school-specific catalogue; `Incidents` → report form and same-offence counter; `Interventions` → staff support actions; `Cases` → grouped cases; `AuditLog` → basic creation records; dashboards → initial school-scoped totals. The other specification components are planned, **not implemented**.

## Legal design constraints
South African Schools Act and BELA amendments require school-approved codes and fair, age-appropriate processes; POPIA has special conditions for children's personal information. A school and qualified legal/privacy advisers must approve the live configuration and processing arrangements.


## v0.2 changes (November 2026)
Added CSRF double-submit checks, basic security response headers, active memberships, class-scoped educator learner access, restricted navigation, staff invitation/acceptance, learner edits, case status changes, incident review, review tasks for flagged incidents, parent communication records, school-configurable repeat threshold and management summary API.

**Still a development prototype.** Not production safe: no real email delivery, MFA, rate limits, Alembic migrations, complete relational tenant constraints, full backup/recovery tests, consent/retention workflows, billing, or external audit. Existing databases require schema migration before upgrading; do not run against real records. Use fictitious learner data only.


## v0.3 navigation and school operations (3 November 2026)
- Replaced the prototype navigation with grouped, role-aware menus, hash URLs, responsive mobile navigation and searchable data views.
- Learner directory supports server-side search and 50-record pages, including schools with more than 500 learners.
- Added learner profiles, incident details/review, case details/assignment/status, staff editing/invitation acceptance, intervention outcomes, review-task actions, appeals, parent contacts, meeting scheduling and document draft records.
- Added school switching for authorised multi-school memberships.
- Dashboards and reports now show monthly trends, severity and repeat-behaviour summaries, with administrator-only CSV incident export.
- Added API regression tests and frontend JavaScript syntax checking in GitHub Actions.

### Upgrading an existing v0.2 database
Back up your database first. Stop the old application, set DATABASE_URL to the existing database and run:

    python scripts/upgrade_v02_to_v03.py

Then start the v0.3 application and verify school data and roles. Never run an untested migration against production data. This script upgrades new columns only and is not a substitute for versioned Alembic migrations.

### Work that remains
This is still a development prototype, not production-certified or appropriate for genuine learner disciplinary data. Not yet implemented: real invitation email delivery, password recovery, MFA, subscription billing/payment processing, parent accounts/portal, external evidence uploads, PDF/Word letter templates, complete Code of Conduct versioning, scheduled notifications, full tenant-enforcing database constraints/RLS, tamper-resistant audit, backup/restore automation, deployment hardening, accessibility certification and browser-based end-to-end testing.
Subscriptions are informational; no payments are collected. Document records are drafts and are not sent to guardians.

### New screens
Overview, learners and learner profiles, classes, incidents and details, cases and details, interventions, appeals, tasks, parent contacts, meetings, document drafts, reports, offences, staff administration, settings, subscription status, audit log and notifications.

## v0.4 security and case workflow increment (3 November 2026)
- Server-side revocable session records: logout invalidates the token; switching school creates a new session and revokes the previous one.
- Login failures are limited to five per school/email identity in a rolling 15-minute window (basic application-level throttling, not distributed edge rate limiting).
- HOD/SMT case assignment now uses a restricted eligible-assignees endpoint, not the administrator-only member directory.
- CSV incident export neutralises leading spreadsheet formula characters in potentially user-supplied cells.
- New automated regression coverage for session revocation, failed login throttling, HOD case assignment visibility, school switch revocation and CSV safety.
- All changes live on main. Check GitHub Actions after each change.

### Upgrade caveats
Existing login sessions from previous releases will no longer be accepted because they lack a stored session identifier. Users must sign in again. The new active_sessions and login_failures tables are created on startup for the development setup; formal Alembic migrations are still required for a production rollout. A staged upgrade and backup remain essential.

### Still outstanding
Multi-factor authentication, verified email invitations and password recovery, network-level rate limits, tenant-safe relational constraints, database migration framework, session/device management screen, full end-to-end browser tests, commercial billing, incident lifecycle and POPIA compliance assessment are not yet complete.

## v0.5 development increment
- Added school-scoped guardian contacts, append-only case timeline notes, explicit case status/assignment history, owner-assigned follow-ups, and multi-class staff assignments.
- Added database-paginated incident/case directories, SQL-aggregated dashboard totals, filtered incident reports by date/grade/class and corresponding frontend views.
- Added a fresh-install Alembic schema baseline. Existing populated deployments need a separate reconciled migration plan; do not assume stamp or create_all is a valid upgrade.
- Added an SMTP-configured one-use password recovery flow. SMTP_HOST, SMTP_PORT (default 465), SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM and APP_PUBLIC_URL must be configured; no email tokens are displayed through API responses.
- Added Chromium Playwright browser smoke test for registration, learner creation, mobile navigation and logout. CI tests its results separately from Python API checks.
- Added operations, multi-class and recovery regression tests.

### Important unimplemented items
Do not use with identifiable child data until POPIA, safeguarding and security assessments are complete. Foundations now exist for several former gaps (see v0.6), but legal sign-off, payment gateways, PDF/Word production templates, penetration testing and automated retention enforcement remain unfinished.

### Deployment caution
Only new fresh development or staging databases should run the baseline Alembic revision automatically. Populated legacy databases need a reviewed migration and tested backup. SCHEMA_AUTO_CREATE=false disables automatic startup schema creation. Use COOKIE_SECURE=true behind TLS.

## v0.6 pilot foundation (local increment)
Adds foundational controls requested for a broader pilot surface. **Still not production-approved for identifiable children's data.**

- TOTP MFA enroll/enable/disable and MFA challenge at login (`/api/mfa/*`)
- SMTP-backed staff invitations when SMTP_* is configured (falls back to private token)
- Versioned Code of Conduct register with approval
- Disciplinary hearing schedule/update register (human-led; no automated sanctions)
- Evidence file uploads (local disk under `EVIDENCE_UPLOAD_DIR`)
- Letter templates with plain-text render placeholders
- Parent acknowledgement invite + redeem flow
- Billing invoice stubs (no payment gateway)
- Privacy retention placeholders + POPIA status endpoint
- Platform-admin console gated by `PLATFORM_ADMIN_EMAILS`
- Append-only audit delete blocked; `scripts/backup_db.py`; `scripts/postgres_rls.sql` sketch
- Shared `app/mailer.py` for recovery/invites/parent notices

### Still not complete
Independent POPIA legal assessment, real payment collection, parent self-service portal accounts, PDF/Word generation, SSO, full Postgres RLS wiring in the app session, penetration testing, and immutable offsite audit storage remain unfinished.

## v0.6 pilot foundation
- Shared SMTP mailer for password recovery, staff invitations (email when configured) and parent acknowledgement invites.
- TOTP MFA setup/enable/disable with login challenge (`mfa_required` + `/api/mfa/verify-login`).
- Code of Conduct versioning with draft/approve workflow; disciplinary hearing register (human-led outcomes only).
- Evidence file uploads (local disk under `EVIDENCE_UPLOAD_DIR`); plain-text letter templates with merge fields.
- Parent portal access tokens + acknowledgement API/UI (`#parent=` hash).
- Billing invoice stubs (no payment gateway); privacy/retention placeholders; platform-admin console gated by `PLATFORM_ADMIN_EMAILS`.
- Audit delete blocked (append-only intent); `scripts/backup_db.py`; optional `scripts/postgres_rls.sql` sketch.
- Expanded `.env.example` and `tests/test_pilot_pack.py`.

**Still not production / not POPIA-cleared:** no payment processor, no PDF/Word generation, no proven backup restore certification, no enforced Postgres RLS in the app connection layer, no independent security audit.