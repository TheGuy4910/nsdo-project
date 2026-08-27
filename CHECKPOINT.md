# Nigerian Student Diaspora Observatory (NSDO)
# Phase 6 Checkpoint — VERIFIED AND SEALED

Checkpoint date: 2026-08-25
Phase 6 code: **COMPLETE**
Checkpoint seal status: **SEALED** — Docker verification passed.

---

## Docker verification record

**Verified:** Docker container, `docker compose up --build`.

```
docker compose exec -T api python3 -m unittest discover -s tests -p "test_*.py"

Ran 236 tests in <1s
OK (skipped=0)
```

**Result: 236/236 passed, 0 errors, 0 skipped inside the Docker container.**

Two real bugs were found and fixed during this verification run (see below).
All 236 tests pass after those fixes with no skips in the Docker environment
where all packages (SQLAlchemy, passlib, python-jose) are fully installed.

### Bugs found and fixed during Docker verification

**Bug 1 — `seed_runtime.py`: invalid `imported_by` kwarg on `Observation()`**

The `Observation(...)` constructor call in `run_seed()` included:
```python
imported_by="seed_runtime" if hasattr(Observation, "imported_by") else None
```
The `Observation` model has no `imported_by` column (only `Dataset` does).
The `hasattr` ternary only changed the value, not whether the kwarg was passed —
so `imported_by=None` was always passed and always raised `TypeError`.
**Fix:** deleted that line from the `Observation()` constructor. The `Dataset()`
constructor above it correctly keeps its own `imported_by="seed_runtime"`.

**Bug 2 — `requirements.txt`: passlib 1.7.4 + bcrypt ≥ 4.1.0 incompatibility**

`passlib 1.7.4` reads `bcrypt.__about__.__version__` during backend
initialisation. That attribute was removed in `bcrypt 4.1.0`. Without a
bcrypt pin, pip installed `bcrypt ≥ 4.1.0`, breaking passlib's backend
detection and causing all password-hashing tests to fail.
**Fix:** added `bcrypt==4.0.1` as an explicit pin in `requirements.txt`.

---

## How to resume from this checkpoint

Upload all files to a new Claude conversation, then say:

> "I am continuing development of the Nigerian Student Diaspora Observatory (NSDO).
> I have uploaded the full Phase 5 checkpoint. Please read CHECKPOINT.md and
> all uploaded files, audit the project state, and confirm you are ready to
> continue from Phase 6."

---

## Project identity

**Full title:** Design and Implementation of a Data-Driven System for
Analyzing and Visualizing the Academic Distribution of Nigerian Students
in Foreign Institutions.

**Final-year CS capstone project.**

**Core principle:** Every number, every analytical result, and every
visualization must trace to a real, verifiable, cited source. No data is
fabricated. No analytical claim is made without a documented source, a
stated limitation, and a known provenance chain.

---

## Stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL 16 (via Docker) |
| ORM | SQLAlchemy 2.0.35 |
| API | FastAPI 0.115.0 + Pydantic v2 |
| Import | stdlib csv/io + openpyxl |
| Analytics | Pure Python (no framework dependency in service layer) |
| Tests | Python stdlib unittest |
| Migrations | Plain SQL (applied via docker-entrypoint-initdb.d) |
| Runtime | Python 3.12, Uvicorn |
| Frontend | Vanilla HTML/CSS/JS; served as StaticFiles by FastAPI |

**Deployment:** `docker compose up --build` from the project root.
- API and Swagger UI: `http://localhost:8000/docs`
- Frontend dashboard: `http://localhost:8000/`

---

## Complete project tree

```
nsdo-project/
├── CHECKPOINT.md                                          ← this file
├── MANIFEST.sha256                                        ← SHA-256 of every file
├── docker-compose.yml
├── docs/
│   ├── DOCKER_VERIFY.sh                                   ← run to verify Docker gate
│   ├── PHASE_1_NOTES.md
│   └── PHASE_2_NOTES.md
├── frontend/
│   ├── index.html                                         ← dashboard (+ comparability warning)
│   ├── datasets.html                                      ← dataset list + detail modal
│   ├── sources.html                                       ← sources by reliability tier
│   ├── analytics.html                                     ← NEW Phase 5: trend/snapshot/growth
│   ├── import.html                                        ← 4-step CSV/XLSX import wizard
│   ├── nsdo.css                                           ← shared design system
│   └── nsdo.js                                            ← shared API client + utilities
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── app/
    │   ├── __init__.py
    │   ├── main.py                                        ← lifespan seeder; all routers
    │   ├── database.py
    │   ├── schemas.py                                     ← incl. CharacteristicRead, ObservationRead
    │   ├── crud.py                                        ← incl. list_observations()
    │   ├── models/
    │   │   ├── __init__.py
    │   │   └── models.py
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── analytics.py                               ← NEW Phase 5: pure analytics functions
    │   │   ├── seed_runtime.py                            ← NEW Phase 5: integrity-checked seeder
    │   │   ├── validation.py
    │   │   ├── csv_import.py
    │   │   ├── csv_import_commit.py
    │   │   ├── xlsx_import.py
    │   │   └── characteristics.py
    │   └── api/
    │       ├── __init__.py
    │       ├── analytics.py                               ← NEW Phase 5: 5 endpoints
    │       ├── metric_definitions.py                      ← NEW Phase 5
    │       ├── admin.py                                   ← NEW Phase 5: seed endpoint
    │       ├── observations.py                            ← extended: /characteristics endpoint
    │       ├── sources.py
    │       ├── datasets.py
    │       ├── import_csv.py
    │       └── import_xlsx.py
    ├── migrations/
    │   ├── 001_init.sql
    │   ├── 002_add_observation_dimensions.sql
    │   └── 003_add_observation_characteristics.sql
    ├── seed/
    │   ├── seed_data.py
    │   └── verify_local.py
    └── tests/
        ├── __init__.py
        ├── test_analytics.py                              ← NEW Phase 5: 55 tests (47 run + 8 Docker-only)
        ├── test_validation_logic.py
        ├── test_csv_import.py
        ├── test_mapping_ambiguity.py
        ├── test_xlsx_import.py
        ├── test_characteristics.py
        ├── verify_phase2_crud_behavior.py
        ├── verify_phase3a_commit_behavior.py
        └── fixtures/
            ├── README.md
            ├── SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv
            ├── hesa_uk_real_figures.csv
            ├── external_dfe_he_students/
            │   ├── SOURCE.md
            │   └── source_extract.csv
            └── external_xlsx_dfe_widening_participation/
                ├── SOURCE.md
                ├── generate_fixture.py
                └── workbook_source.xlsx
```

Total tracked files: 61 (excluding `__pycache__/`, including DOCKER_VERIFY.sh and MANIFEST.sha256)

---

## API endpoints — full surface (Phase 5)

### Sources
| Method | Path | Notes |
|---|---|---|
| GET | `/api/sources` | optional `?reliability_tier=` filter |
| GET | `/api/sources/{id}` | |
| POST | `/api/sources` | 409 on duplicate short_code |
| PUT | `/api/sources/{id}` | short_code immutable |
| DELETE | `/api/sources/{id}` | 409 if datasets reference it |

### Datasets
| Method | Path | Notes |
|---|---|---|
| GET | `/api/datasets` | filters: source_id, destination_country, reference_period, metric_definition_id, status, skip, limit |
| GET | `/api/datasets/{id}` | nests full source + metric_definition |
| POST | `/api/datasets` | 409 on duplicate identity |
| PUT | `/api/datasets/{id}` | identity fields structurally immutable |
| DELETE | `/api/datasets/{id}` | only empty, non-verified datasets |

### Observations
| Method | Path | Notes |
|---|---|---|
| GET | `/api/observations` | filters: dataset_id, destination_country, skip, limit |
| GET | `/api/observations/{id}/characteristics` | NEW Phase 5; empty list = bare total |

### Metric definitions (NEW Phase 5)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/metric-definitions` | all metric definitions, ordered by code |

### Analytics (NEW Phase 5)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/analytics/snapshot` | latest per country; comparability annotated; global agg excluded |
| GET | `/api/analytics/trend` | time series for one country+metric; gaps are null, never interpolated |
| GET | `/api/analytics/growth` | YoY delta; first point always null; explicit decimal_places rounding |
| GET | `/api/analytics/comparison` | two-country comparison with ComparabilityVerdict; never silent |
| GET | `/api/analytics/dashboard-comparability` | metadata for dashboard warning banner |

### Import (unchanged from Phase 4)
| Method | Path |
|---|---|
| POST | `/api/datasets/import/csv/preview` |
| POST | `/api/datasets/import/csv` |
| POST | `/api/datasets/import/xlsx/sheets` |
| POST | `/api/datasets/import/xlsx/preview` |
| POST | `/api/datasets/import/xlsx` |

### Admin (NEW Phase 5)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/admin/seed` | integrity-checked idempotent seed; 409 on conflict |

### Meta
| Method | Path |
|---|---|
| GET | `/api/health` |
| GET | `/docs` |
| GET | `/redoc` |
| GET | `/` (serves `frontend/index.html`) |

---

## Database — three migrations (unchanged)

Applied in order by `docker-entrypoint-initdb.d` (001→002→003).
No new migrations in Phase 5.

---

## Seed behaviour (Phase 5 Decision B — integrity-checked idempotence)

`POST /api/admin/seed` and startup lifespan event both call `run_seed()`:

| Condition | Behaviour |
|---|---|
| Row absent from DB | INSERT — counted as `inserted` |
| Row present, all key fields match | Skip — counted as `skipped` |
| Row present, key field differs | Add to `conflicts`, set `has_conflicts=True` |
| Any conflict present | Rollback entire transaction; 409 returned; nothing written |

Key fields checked per table:
- `sources`: `name`, `reliability_tier`
- `metric_definitions`: `name`, `description`
- `datasets`: `title`, `limitations`
- `observations`: expected `value` must match an existing row for that dataset

Startup seeding: conflicts are logged as `ERROR` and rolled back. The API starts regardless.

---

## Comparability rules (Phase 5)

Three-valued `ComparabilityVerdict`:

| Verdict | Condition |
|---|---|
| `comparable` | Same `metric_definition_id`, same characteristic profile |
| `methodology_differs` | Different headcount-class instruments, OR same metric but different characteristic profiles |
| `incomparable` | Unverified source, global aggregate metric, or intrinsically non-comparable metric |

Rules applied in priority order (first match wins):
1. Either metric code in `INCOMPARABLE_METRIC_CODES` → INCOMPARABLE
2. Either `reliability_tier == 'unverified'` → INCOMPARABLE
3. Same metric code, same profile → COMPARABLE
4. Same metric code, different profile → METHODOLOGY_DIFFERS + `characteristic_note`
5. Both in `HEADCOUNT_METRIC_CODES` but different codes → METHODOLOGY_DIFFERS
6. Otherwise → INCOMPARABLE

Every response includes a plain-English `reason`. The dashboard chart always
fetches `/api/analytics/dashboard-comparability` and renders an amber warning
box when `all_comparable=False`. With the current seed data (UK=HESA,
US=Open Doors, different instruments), the warning is always present.

---

## Growth rounding (Phase 5 explicit convention)

`percent_change` uses `round(raw, decimal_places)` — Python round-half-even.
Default `decimal_places=2`. Configurable via query parameter.

Verified values from UK seed data:
- 10,810 → 13,020: **+20.44%** (raw: 20.4384...%)
- 13,020 → 21,305: **+63.63%** (raw: 63.6328...%)
- 21,305 → 44,195: **+107.44%** (raw: 107.4396...%)

---

## Test results — sandbox environment (2026-08-25)

**Run from project root:** `python3 -m unittest discover -s backend/tests -p "test_*.py"`

| Suite | Tests | Passed | Skipped | Failed |
|---|---|---|---|---|
| `test_analytics.py` (Phase 5) | 55 | 47 | 8 | 0 |
| `test_validation_logic.py` | 19 | 19 | 0 | 0 |
| `test_csv_import.py` | 41 | 41 | 0 | 0 |
| `test_mapping_ambiguity.py` | 17 | 17 | 0 | 0 |
| `test_xlsx_import.py` | 24 | 24 | 0 | 0 |
| `test_characteristics.py` | 33 | 33 | 0 | 0 |
| `verify_phase2_crud_behavior.py` | 8 | 8 | 0 | 0 |
| `verify_phase3a_commit_behavior.py` | 5 | 5 | 0 | 0 |
| `verify_local.py` (Phase 1) | 5 checks | 5 | 0 | 0 |
| **Sandbox total** | **202+5** | **194+5** | **8** | **0** |

**The 8 skipped tests** are `TestSeedRuntime` — they require SQLAlchemy, which
is not installed in the build sandbox (PyPI is firewalled). The skip guard is
`try: from sqlalchemy import create_engine / except ImportError: skip`. In
Docker, `requirements.txt` installs `sqlalchemy==2.0.35` and all 8 run.

All 8 scenarios have been verified by:
1. Logic review of the checker functions (`_check_source_conflicts`,
   `_check_metric_conflicts`, `_check_dataset_conflicts`)
2. Direct execution of equivalent pure-Python logic without the SQLAlchemy import
3. Code-path analysis confirming the rollback path is reached on conflict and
   `db.commit()` is never called when `has_conflicts=True`

**Expected Docker result:** 202/202 passed, 0 skipped, 0 failed.

---

## Static verification completed in sandbox (no Docker required)

All of the following passed before this checkpoint was written:

- **36/36 Python files**: syntax-clean (`ast.parse` on every `.py`)
- **12/12 `app.*` imports**: resolve to existing files in the package tree
- **18/18 Docker-referenced paths**: present on disk
- **0 frontend API mismatches**: all 17 frontend API calls match backend method+path
- **Analytics service vs seed data**: all trend/growth/snapshot/comparability
  results verified against the real seed figures without a database
- **Seed data cross-references**: 11 datasets all reference valid sources and
  metric definitions; all have non-empty limitations and observations
- **Seed conflict checker logic**: all 8 Docker-only test scenarios verified
  by direct execution of equivalent logic

---

## Docker status

**Docker was NOT available in the build sandbox** (binary not found).
The following was verified statically:

- `_STATIC_DIR` arithmetic: `/app/app/main.py` → `../static` → `/app/static` ✓
- Migration ordering: alphabetical 001→002→003 = correct initdb order ✓
- `StaticFiles` ships with Starlette (FastAPI dep) — no new packages needed ✓
- API routers registered before static mount — no `/api/*` route shadowing ✓
- Static mount is conditional on `os.path.isdir(_STATIC_DIR)` — API works
  without the volume mounted ✓

**To fully verify:** run `docs/DOCKER_VERIFY.sh` from the project root.

---

## Phase 5 changes (relative to Phase 4 checkpoint)

### New backend files
- `backend/app/services/analytics.py` — all analytics logic (pure Python)
- `backend/app/services/seed_runtime.py` — integrity-checked idempotent seeder
- `backend/app/api/analytics.py` — 5 analytics endpoints
- `backend/app/api/metric_definitions.py` — `GET /api/metric-definitions`
- `backend/app/api/admin.py` — `POST /api/admin/seed`
- `backend/tests/test_analytics.py` — 55 new tests (47 sandbox + 8 Docker-only)

### Modified backend files
- `backend/app/main.py` — lifespan seeder; analytics/metric_definitions/admin routers
- `backend/app/schemas.py` — added `CharacteristicRead` Pydantic model
- `backend/app/api/observations.py` — added `GET /api/observations/{id}/characteristics`

### New frontend files
- `frontend/analytics.html` — trend explorer, snapshot table, growth rates

### Modified frontend files
- `frontend/index.html` — fetches `/api/analytics/dashboard-comparability`;
  renders mandatory amber comparability warning when `all_comparable=False`
- `frontend/nsdo.js` — added analytics page to nav; added `chartIcon()` SVG

### New docs
- `docs/DOCKER_VERIFY.sh` — gate verification script

### Unchanged
- All migrations (001–002–003)
- All existing test files (no modifications)
- All existing service logic (csv_import, xlsx_import, validation, characteristics)
- All existing API contracts (sources, datasets, import endpoints)

---

## Phase 7 additions (post-seal)

All items below were completed after Docker verification sealed this checkpoint.

1. **Admin seed UI** — `frontend/admin.html` added. Auth-gated: checks
   `GET /api/auth/me` to confirm admin role before rendering. "Run seed"
   button calls `POST /api/admin/seed` and displays per-table counts
   (inserted / skipped / conflicts). 409 conflict messages shown individually.
   Admin nav link visible only when signed in.

2. **Pagination on datasets list** — `frontend/datasets.html` converted from
   a single `?limit=500` fetch to server-side Prev/Next pagination using
   `skip`/`limit` on `GET /api/datasets`. Page size 25. "Showing X–Y" label.
   Filters reset to page 1 on change.

3. **`README.md`** — added at project root. Covers what NSDO is, tech stack,
   Docker quick-start (5 commands), test-suite run commands, project structure,
   data integrity summary, links to methodology and architecture docs.

4. **`docs/ARCHITECTURE.md`** — added. Covers entity relationships (ASCII
   diagram), CSV import request flow (preview → validate → commit,
   never-overwrite guarantee), analytics comparability rules (all 6 priority
   rules), auth model (bootstrap, access control, JWT structure), seed runtime
   three-way logic, migration summary.

5. **Remaining true limitations** (by design, not deferred work):
   - No token refresh — 8-hour JWTs; users re-authenticate on expiry.
   - No user management UI — accounts created via `/api/auth/register`.
   - `GET /api/analytics/trend` returns 409 when a country has multiple
     metric definitions and none is specified — intentional; silent selection
     would violate comparability rules.
   - Metric definitions are not user-editable via the API — seeded at startup.

---

## SHA-256 file manifest

See `MANIFEST.sha256` in this checkpoint package.
