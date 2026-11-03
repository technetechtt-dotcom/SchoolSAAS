-- Optional PostgreSQL row-level security sketch for SchoolCare tenants.
-- Apply only after a reviewed migration and with application SET app.school_id.
-- This is a defence-in-depth aid, not a substitute for application filters.

-- Example session GUC set by the app connection factory:
--   SET app.school_id = '<integer school id>';

ALTER TABLE learners ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE offences ENABLE ROW LEVEL SECURITY;
ALTER TABLE interventions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_learners ON learners;
CREATE POLICY tenant_learners ON learners
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_incidents ON incidents;
CREATE POLICY tenant_incidents ON incidents
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_cases ON cases;
CREATE POLICY tenant_cases ON cases
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_offences ON offences;
CREATE POLICY tenant_offences ON offences
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_interventions ON interventions;
CREATE POLICY tenant_interventions ON interventions
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_audit ON audit_events;
CREATE POLICY tenant_audit ON audit_events
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- Audit immutability (reject updates/deletes for ordinary roles)
REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;
