-- Nigerian Student Diaspora Observatory
-- Migration 001: initial schema
-- Target engine: PostgreSQL 14+
-- Design principles:
--   1. Every observation traces back to exactly one dataset, which traces to exactly one source.
--   2. Datasets are never overwritten. Revisions create a new row linked via superseded_by_id.
--   3. Comparisons across datasets are only valid when metric_definition_id matches.
--   4. Every dataset must state, in plain text, what it is counting and its known limitations.

CREATE TABLE sources (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL,                 -- e.g. "Higher Education Statistics Agency"
    short_code          TEXT NOT NULL UNIQUE,           -- e.g. "HESA"
    organization_type   TEXT NOT NULL CHECK (organization_type IN
                            ('national_statistics_agency','international_organization',
                             'government_department','ngo_or_press','secondary_aggregator')),
    home_country        TEXT,                           -- country the source agency belongs to
    url                 TEXT,
    reliability_tier    TEXT NOT NULL CHECK (reliability_tier IN
                            ('official_primary','official_secondary','credible_secondary','unverified')),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE metric_definitions (
    id                  SERIAL PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,           -- e.g. "enrolled_headcount"
    name                TEXT NOT NULL,                  -- e.g. "Enrolled student headcount"
    description         TEXT NOT NULL,                  -- precise definition: who counts, when counted, dedup rules
    unit                TEXT NOT NULL DEFAULT 'count of individuals'
);

CREATE TABLE datasets (
    id                      SERIAL PRIMARY KEY,
    source_id               INTEGER NOT NULL REFERENCES sources(id),
    metric_definition_id    INTEGER NOT NULL REFERENCES metric_definitions(id),
    title                   TEXT NOT NULL,
    destination_country     TEXT NOT NULL,
    reference_period        TEXT NOT NULL,               -- e.g. "2021/22" or "2024"
    publication_date        DATE,
    original_filename       TEXT,
    original_url            TEXT,
    status                  TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                                ('draft','validated','verified','deprecated')),
    superseded_by_id        INTEGER REFERENCES datasets(id),
    imported_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    imported_by             TEXT NOT NULL DEFAULT 'system',
    verified_at             TIMESTAMPTZ,
    verified_by             TEXT,
    limitations             TEXT NOT NULL,               -- REQUIRED: what this dataset does NOT tell you
    UNIQUE (source_id, destination_country, reference_period, metric_definition_id)
);

CREATE TABLE observations (
    id                  BIGSERIAL PRIMARY KEY,
    dataset_id          INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    destination_country TEXT NOT NULL,
    institution         TEXT,                            -- nullable: not all sources report at this granularity
    discipline          TEXT,                             -- nullable
    degree_level        TEXT,                             -- nullable
    value                NUMERIC NOT NULL,
    raw_source_row       INTEGER,                          -- line number in the original uploaded file, for traceability
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE validation_reports (
    id              SERIAL PRIMARY KEY,
    dataset_id      INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    rule_name       TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pass','warning','fail')),
    message         TEXT NOT NULL,
    affected_rows   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE provenance_log (
    id          BIGSERIAL PRIMARY KEY,
    dataset_id  INTEGER REFERENCES datasets(id) ON DELETE CASCADE,
    source_id   INTEGER REFERENCES sources(id),
    action      TEXT NOT NULL CHECK (action IN
                    ('registered','imported','validated','verified','deprecated','edited','exported')),
    actor       TEXT NOT NULL,
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin','viewer')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_observations_dataset ON observations(dataset_id);
CREATE INDEX idx_observations_country ON observations(destination_country);
CREATE INDEX idx_datasets_country_period ON datasets(destination_country, reference_period);
CREATE INDEX idx_datasets_status ON datasets(status);
