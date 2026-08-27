# NSDO — Architecture

## Data model

### Entity relationships

```
Source
  │  (one source publishes many datasets)
  │
  ├──► Dataset  ◄── MetricDefinition
  │      │          (what was counted and how)
  │      │
  │      ├──► Observation  ──► ObservationCharacteristic
  │      │       (one numeric value      (sub-dimensions:
  │      │        per destination         mode_of_study,
  │      │        country per import)     ethnicity, etc.)
  │      │
  │      ├──► ValidationReport  (errors/warnings from import pipeline)
  │      │
  │      └──► ProvenanceLog  (who imported, when, what action)
  │
  └──► (User — separate; not linked to datasets directly)
```

### Key rules enforced at the schema level

- `Dataset.limitations` is `NOT NULL` and enforced non-empty by the API.
  A dataset that does not state what it does *not* tell you cannot exist.
- `Dataset` identity fields (`source_id`, `destination_country`,
  `reference_period`, `metric_definition_id`) are structurally immutable
  after creation — updates to these fields are rejected by the CRUD layer.
  Corrections create a new dataset linked via `superseded_by_id`;
  the original is deprecated, never deleted.
- `ObservationCharacteristic` has `UNIQUE(observation_id, dimension)` —
  one canonical value per dimension per observation.
- `ObservationCharacteristic.observation_id` has `ON DELETE CASCADE`.

### Table summary

| Table | Purpose |
|---|---|
| `sources` | Organisations publishing data. Has `reliability_tier` (official_primary / official_secondary / credible_secondary / unverified). |
| `metric_definitions` | What a numeric observation measures. `code`, `name`, `description`, `unit`. Two observations are directly comparable only if they share a `metric_definition_id`. |
| `datasets` | One import event. Links source + metric + destination country + reference period. Carries `limitations` and `status`. |
| `observations` | One numeric value from one dataset. Has optional dimension columns (`academic_year`, `degree_level`, `gender`, etc.) added in migration 002. |
| `observation_characteristics` | Sub-dimensional breakdowns (mode_of_study, ethnicity…). Added in migration 003. A bare total has zero rows here. |
| `validation_reports` | Errors and warnings recorded during import pipeline preview. |
| `provenance_log` | Audit trail: every import, deprecation, or manual action. |
| `users` | Authentication only. `username`, `password_hash`, `role` (admin/viewer). |

---

## CSV / XLSX import request flow

```
Client uploads file
        │
        ▼
POST /api/datasets/import/csv/preview  (or /xlsx/preview)
        │
        │  [No DB writes — pure parse + validate]
        │
        ├── csv_import.py: parse_csv()
        │       detect delimiter, strip BOM, read rows
        │
        ├── csv_import.py: suggest_column_mapping()
        │       match source headers to canonical fields
        │       (destination_country, student_count, academic_year, …)
        │       flag ambiguities where multiple headers match one field
        │
        ├── csv_import.py: validate_rows()
        │       validate each row: required fields present,
        │       student_count numeric and non-negative,
        │       academic_year format valid,
        │       duplicates flagged (same canonical key = duplicate)
        │
        └── returns preview response:
                summary (total / valid / error / duplicate counts)
                detected_columns
                mapping_used
                ambiguities (list of fields needing human resolution)
                sample_rows (first 10)
                issues (all errors and warnings)

Client reviews preview, resolves any ambiguities, fills metadata form
        │
        ▼
POST /api/datasets/import/csv  (commit)
        │
        │  [DB writes — wrapped in a transaction]
        │
        ├── Re-run the same pipeline (never trust client-supplied parse results)
        │
        ├── Check for unresolved required-field ambiguities → reject if any
        │
        ├── INSERT Dataset (with source_id, metric_definition_id,
        │       destination_country, reference_period, limitations, …)
        │
        ├── INSERT Observation rows (valid + optionally warning rows)
        │       Never inserts error rows.
        │       Never silently overwrites an existing Dataset.
        │       A duplicate Dataset identity → 409 Conflict.
        │
        ├── INSERT ObservationCharacteristic rows (if characteristic
        │       columns were mapped)
        │
        ├── INSERT ValidationReport (all issues, for audit)
        │
        └── INSERT ProvenanceLog (actor, action, timestamp)
```

### Never-overwrite guarantee

The commit endpoint checks for an existing `Dataset` with the same
`(source_id, destination_country, reference_period, metric_definition_id)`.
If one exists, the import is rejected with a 409. To correct data:
import a new dataset and mark the old one deprecated via `superseded_by_id`.
This is enforced in `crud.py:create_dataset()` and cannot be bypassed
through the API.

---

## Analytics and comparability

The analytics service (`services/analytics.py`) is framework-free pure Python.
It accepts plain dicts and returns plain dicts — no SQLAlchemy, no FastAPI.
This makes every analytical rule independently testable.

### Comparability verdict (three-valued)

```
assess_comparability(metric_code_a, metric_code_b,
                     reliability_tier_a, reliability_tier_b,
                     char_profile_a, char_profile_b)

Rules (applied in priority order, first match wins):

  1. Either metric is in INCOMPARABLE_METRIC_CODES
     (unverified_market_estimate, unesco_outbound_mobility)
     → INCOMPARABLE

  2. Either source has reliability_tier == 'unverified'
     → INCOMPARABLE

  3. Same metric_code AND same characteristic profile
     → COMPARABLE

  4. Same metric_code BUT different characteristic profiles
     (e.g. one is a bare total, the other is broken down by mode_of_study)
     → METHODOLOGY_DIFFERS  +  characteristic_note explaining the difference

  5. Both in HEADCOUNT_METRIC_CODES but different codes
     (e.g. hesa_enrolled_headcount vs sevis_enrolled_headcount)
     → METHODOLOGY_DIFFERS

  6. Otherwise → INCOMPARABLE
```

Every response from the analytics endpoints includes a `verdict` and a
plain-English `reason`. The frontend always renders the amber warning box
when `all_comparable` is false — it cannot be suppressed.

---

## Authentication model

### Bootstrap rule (Decision A)

```
POST /api/auth/register

  if count_users(db) == 0:
      role = 'admin'    # first user becomes admin, no token required
  else:
      require valid admin Bearer token
      role = 'viewer'   # all subsequent users are viewers by default
```

### Access control (Decision C)

```
All GET endpoints         → public (no authentication required)
GET /api/auth/me          → authenticated (any valid token)
All POST/PUT/DELETE       → admin Bearer token required
POST /api/admin/seed      → admin Bearer token required
POST /api/datasets/import → admin Bearer token required (commit only;
                            preview is open — it writes nothing)
```

### JWT structure

```
{
  "sub":  "username",
  "role": "admin" | "viewer",
  "exp":  <8 hours from issuance>,
  "iat":  <issuance timestamp>
}
```

Signed with HS256 using `JWT_SECRET_KEY` from the environment.
Dev fallback: `INSECURE-DEV-ONLY-DO-NOT-USE-IN-PRODUCTION` (logs WARNING).
Tokens are stored in `sessionStorage` — cleared when the browser tab closes.

---

## Seed runtime integrity

`services/seed_runtime.py:run_seed()` applies seed data with three-way logic:

| Condition | Action |
|---|---|
| Row absent from DB | INSERT — counted as `inserted` |
| Row present, key fields match | Skip — counted as `skipped` |
| Row present, key field differs | Add to `conflicts`, set `has_conflicts=True` |

A conflict means an existing DB row disagrees with the seed expectation on a
key field (`name`, `reliability_tier`, `limitations`, `title`, etc.).
If any conflict is detected, the transaction is rolled back and nothing is
written. Conflicts must be resolved manually by inspecting the database.
The `POST /api/admin/seed` endpoint returns 409 with a conflict list.

---

## Migrations

Three sequential plain-SQL files applied by Postgres `docker-entrypoint-initdb.d`
in alphabetical (001→002→003) order on first boot:

| Migration | Adds |
|---|---|
| `001_init.sql` | All 7 tables: sources, metric_definitions, datasets, observations, validation_reports, provenance_log, users. Core indexes. |
| `002_add_observation_dimensions.sql` | Nullable dimension columns on observations: nigerian_state, academic_year, gender, funding_type, institution_type, import_batch_id. Index on import_batch_id. |
| `003_add_observation_characteristics.sql` | observation_characteristics table with UNIQUE(observation_id, dimension) and ON DELETE CASCADE. |

No Alembic runtime dependency. Migrations run once at DB initialisation.
Subsequent container restarts do not re-run them (Postgres `initdb` only
runs on an empty data directory).
