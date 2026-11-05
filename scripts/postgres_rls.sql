-- Optional PostgreSQL row-level security sketch for SchoolCare tenants.
-- Apply only after a reviewed migration and with application SET app.school_id.
-- This is a defence-in-depth aid, not a substitute for application filters.

-- Example session GUC set by the app connection factory:
--   SET app.school_id = '<integer school id>';

ALTER TABLE learners ENABLE ROW LEVEL SECURITY;
ALTER TABLE learners FORCE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents FORCE ROW LEVEL SECURITY;
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases FORCE ROW LEVEL SECURITY;
ALTER TABLE offences ENABLE ROW LEVEL SECURITY;
ALTER TABLE offences FORCE ROW LEVEL SECURITY;
ALTER TABLE interventions ENABLE ROW LEVEL SECURITY;
ALTER TABLE interventions FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_learners ON learners;
CREATE POLICY tenant_learners ON learners
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_incidents ON incidents;
CREATE POLICY tenant_incidents ON incidents
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_cases ON cases;
CREATE POLICY tenant_cases ON cases
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_offences ON offences;
CREATE POLICY tenant_offences ON offences
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_interventions ON interventions;
CREATE POLICY tenant_interventions ON interventions
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

DROP POLICY IF EXISTS tenant_audit ON audit_events;
CREATE POLICY tenant_audit ON audit_events
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- Audit immutability (reject updates/deletes for ordinary roles)
REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;

-- case_events: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE case_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE case_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_case_events ON case_events;
CREATE POLICY tenant_case_events ON case_events
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- follow_ups: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE follow_ups ENABLE ROW LEVEL SECURITY;
ALTER TABLE follow_ups FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_follow_ups ON follow_ups;
CREATE POLICY tenant_follow_ups ON follow_ups
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- guardians: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE guardians ENABLE ROW LEVEL SECURITY;
ALTER TABLE guardians FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_guardians ON guardians;
CREATE POLICY tenant_guardians ON guardians
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- class_assignments: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE class_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_class_assignments ON class_assignments;
CREATE POLICY tenant_class_assignments ON class_assignments
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- learner_placements: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE learner_placements ENABLE ROW LEVEL SECURITY;
ALTER TABLE learner_placements FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_learner_placements ON learner_placements;
CREATE POLICY tenant_learner_placements ON learner_placements
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- learner_observations: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE learner_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE learner_observations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_learner_observations ON learner_observations;
CREATE POLICY tenant_learner_observations ON learner_observations
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- review_tasks: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE review_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_review_tasks ON review_tasks;
CREATE POLICY tenant_review_tasks ON review_tasks
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- school_settings: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE school_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE school_settings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_school_settings ON school_settings;
CREATE POLICY tenant_school_settings ON school_settings
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- letter_documents: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE letter_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE letter_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_letter_documents ON letter_documents;
CREATE POLICY tenant_letter_documents ON letter_documents
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- school_documents: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE school_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE school_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_school_documents ON school_documents;
CREATE POLICY tenant_school_documents ON school_documents
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- appointments: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_appointments ON appointments;
CREATE POLICY tenant_appointments ON appointments
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);

-- parent_contacts: authenticated school-scoped records; never accessed by public token routes.
ALTER TABLE parent_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE parent_contacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_parent_contacts ON parent_contacts;
CREATE POLICY tenant_parent_contacts ON parent_contacts
  USING (school_id = NULLIF(current_setting('app.school_id', true), '')::int)
  WITH CHECK (school_id = NULLIF(current_setting('app.school_id', true), '')::int);
