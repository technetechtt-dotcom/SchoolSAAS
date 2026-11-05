# SchoolSAAS A–F production hardening status

This document tracks the requested production-hardening work. Passing CI is not a security, legal, financial or operational launch certification.

## A. Database and deployment
Implemented in repository:
- Alembic migration setup that upgrades PostgreSQL's version field to support existing long revision IDs without renaming applied migrations.
- Additional authenticated school-record RLS policies and cross-tenant read/write tests.
- Database health/readiness endpoints and a TLS Caddy + PostgreSQL deployment example.
- Separate persistent volumes for evidence, letters, and database storage.
- A consistent SQLite/pg_dump backup bundle containing evidence and letters, SHA-256 manifest, safe verifier, and tested isolated SQLite restore.
- Fail-closed production configuration preflight.

Not complete:
- Verified restoration of a populated PostgreSQL production copy across *every* historical schema and version, real offsite backup storage, encrypted archive delivery, operational image/database rollback drills, fully coverage-complete RLS (public token and billing flows need redesign), real infrastructure provisioning.

## B. UI/UX and navigation
Implemented:
- Teacher-first fast incident capture with recent category shortcuts, last-used location, mandatory confirmed immediate action, optional browser speech recognition.
- A simple source contract that fails when literal button actions lack handlers.
- Real browser navigation checks across educator, HOD, SMT, principal and school-admin accounts.
- Chromium, Firefox and WebKit browser smoke jobs, plus API regression coverage.

Not complete:
- Exhaustive inspection of every dynamic button, every modal and error state, all assistive technology combinations, formal WCAG AA certification, architectural decomposition of the large HTML file.

## C. Discipline workflows
Implemented:
- One-click, reuse-safe, review-only referral drafts that copy existing incident, learner, policy-category and reporting staff details; never issue a sanction.
- School-scoped due follow-up dashboard and queueable staff reminders with duplicate suppression by school/recipient/day.
- Existing onboarding gates, human hearings, appeals, case transitions and closure checks retained.

Not complete:
- Fully scheduled autonomous staff reminders without an operator-configured scheduler; complete automatic document lifecycle; all hearing/appeal/outcome delivery with approval policies; independently audited safeguarding transitions.

## D. Learners, staff and guardians
Previously implemented and retained:
- Learner import preview, bulk updates, placements/transfers, class assignments, staff access reviews and session revocation.
- Guardian invitation, token-scoped inbox, acknowledgement/dispute and SMTP outbox retry.
Not complete:
- Proper authenticated guardian accounts with verified identity and relationship, independently verified school authority, production identity assurance and approved customer provisioning.

## E. Privacy and safeguarding
Implemented/retained:
- Sensitive learner permissions, evidence audit events, staff session revocation, MFA, privacy request tracking, tenant checks and configurable data retention *rules*.
Not complete:
- Automated lawful deletion with litigation/safeguarding holds, verified subject access fulfilment, independent penetration testing, independent POPIA legal/DPIA review, signed operator agreements and formal bias/effectiveness validation of learner recommendations.

## F. Commercial SaaS
Implemented:
- Optional Paystack transaction initialization and hosted checkout support (disabled without merchant secrets).
- A signed webhook receiver using Paystack's timestamped HMAC-SHA512 format, with a five-minute replay window, server-side transaction verification, exact ZAR amount/reference matching and duplicate protection.
- Provider-specific browser checkout handling and mocked regression tests.
- Existing sandbox functionality preserved.

Not complete:
- Merchant connection/approved live credentials, refund/chargeback workflows, recurring subscriptions and billing dates, verified school plan entitlements, payment settlements and tax-compliant invoice policy, customer support operations and reconciliation with real merchant statements.

## Operating the example deployment
1. Create a secure environment file outside the repo. Never commit production passwords or API keys.
2. Configure PostgreSQL, JWT secret, separate Fernet MFA secret, a verified domain, email settings and permanent evidence/letter volumes.
3. Run `python scripts/release_preflight.py` from the same environment.
4. Snapshot the database and evidence and verify the bundle using `scripts/backup_bundle.py` and `scripts/verify_backup_bundle.py`.
5. Migrate a **staging copy first** with `python -m alembic upgrade head`.
6. Review RLS policies and use a restricted app DB role. Existing public guardian-token and payment callbacks require careful tenancy architecture before all tables can use FORCE RLS.
7. Review the production compose and Caddyfile, then deploy only to a non-production domain until external signoffs are complete.
8. If enabling Paystack, provide merchant-managed `PAYSTACK_SECRET_KEY`, `PAYSTACK_WEBHOOK_SECRET`, and `BILLING_GATEWAY=paystack`, configure `https://<your-domain>/api/billing/webhooks/paystack` in Paystack, and test settlement in Paystack Test Mode first.
9. Do not automatically grant a commercial plan from a paid invoice until its approved plan entitlements and renewal dates are defined.
10. Use actual evidence from browser, backup/restore, PostgreSQL, privacy and independent security tests before authorising real learner data.

## Release acceptance
Every target must show green GitHub CI, a verified staging restore, tenant-safe access, approved human disciplinary decisions and no launch-blocking defects. External security, child-data privacy, operating agreements, merchant approval and real settlement tests are outstanding requirements, not checks that code can self-certify.
