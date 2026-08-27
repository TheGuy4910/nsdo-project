-- Nigerian Student Diaspora Observatory
-- Migration 002: additional academic dimensions for CSV-imported observations
--
-- Purely additive: no existing table is dropped or altered destructively,
-- no existing column changes type or is removed. Every new column is
-- nullable, so Phase 1/Phase 2 rows (which predate these columns) remain
-- valid without modification.
--
-- Rationale: seed_data.py's 11 observations only ever needed
-- destination_country + value. Real CSV exports from ministries/agencies
-- commonly break counts down by additional dimensions -- state of origin,
-- gender, funding type, institution type, and a per-row academic year/session
-- that may differ from the dataset's overall reference_period (e.g. a single
-- release covering several years in one file). Column mapping decides,
-- per import, which of these a given source actually supplies -- an
-- unmapped or absent field is stored as NULL, never fabricated.

ALTER TABLE observations ADD COLUMN nigerian_state    TEXT;
ALTER TABLE observations ADD COLUMN academic_year     TEXT;
ALTER TABLE observations ADD COLUMN gender            TEXT;
ALTER TABLE observations ADD COLUMN funding_type      TEXT;
ALTER TABLE observations ADD COLUMN institution_type  TEXT;

-- Groups every row inserted by a single import call together, independent
-- of which dataset(s) they ended up in. Purely a traceability aid: "show me
-- everything this one CSV upload produced," including rows that were
-- rejected/excluded (tracked in validation_reports, not here).
ALTER TABLE observations ADD COLUMN import_batch_id   TEXT;

CREATE INDEX idx_observations_import_batch ON observations(import_batch_id);
