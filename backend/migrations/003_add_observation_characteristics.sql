-- Nigerian Student Diaspora Observatory
-- Migration 003: generic observation characteristics table
--
-- Purely additive: no existing table is altered, dropped, or constrained
-- further. Every column on every existing table is unchanged.
--
-- Rationale: real external datasets (HESA, DfE) break student counts down
-- by dimensions -- mode_of_study, ethnicity, sex, FSM status -- that vary
-- by source and cannot all be pre-anticipated as fixed schema columns.
-- Adding a column per dimension produces a wide, sparse observations table
-- that grows unboundedly and makes metric_definition_id do work it isn't
-- designed for. This EAV-style table stores any number of (dimension, value)
-- pairs per observation without requiring schema changes for each new source.
--
-- Relationship to metric_definition_id:
--   metric_definition_id defines WHAT is being counted (enrolled headcount,
--   visa issuances, etc.). observation_characteristics defines the POPULATION
--   SLICE the count applies to (Full-time students, Female students, etc.).
--   These are independent concerns and must never be merged.
--
-- Uniqueness constraint:
--   UNIQUE (observation_id, dimension) enforces that each observation has at
--   most one value for any given dimension. If a source reports Male=500 and
--   Female=450 separately, those are two separate observations (rows in the
--   observations table), not two characteristics on one observation.

CREATE TABLE observation_characteristics (
    id              BIGSERIAL PRIMARY KEY,
    observation_id  BIGINT NOT NULL
                    REFERENCES observations(id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL,           -- e.g. 'mode_of_study', 'ethnicity'
    value           TEXT NOT NULL,           -- e.g. 'full_time', 'White'
    value_source    TEXT NOT NULL            -- was the value normalized or left as-is?
                    CHECK (value_source IN ('source_raw', 'normalized')),
    raw_value       TEXT,                    -- original source value when normalized; NULL when unchanged
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (observation_id, dimension)       -- one value per dimension per observation
);

CREATE INDEX idx_obs_char_obs  ON observation_characteristics(observation_id);
CREATE INDEX idx_obs_char_dim  ON observation_characteristics(dimension);
CREATE INDEX idx_obs_char_dval ON observation_characteristics(dimension, value);
