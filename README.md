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
