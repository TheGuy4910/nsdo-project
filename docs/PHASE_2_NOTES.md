# Phase 2 — FastAPI backend skeleton, models, and sources/datasets CRUD

## Files in this deliverable

```
backend/migrations/001_init.sql               Phase 1 schema (unchanged)
backend/app/models/models.py                  Phase 1 SQLAlchemy models (unchanged)
backend/seed/seed_data.py                     Phase 1 seed data (unchanged)
backend/seed/verify_local.py                  Phase 1 verification shim (unchanged)
backend/app/database.py                       SQLAlchemy engine/session, DATABASE_URL-driven
backend/app/schemas.py                        Pydantic request/response contracts
backend/app/services/validation.py            framework-independent business rules
backend/app/crud.py                           data-access layer used by both routers
backend/app/api/sources.py                    /api/sources router
backend/app/api/datasets.py                   /api/datasets router
backend/app/main.py                           FastAPI app assembly, CORS, OpenAPI metadata
backend/Dockerfile                            container build for the API service
backend/tests/test_validation_logic.py        19 real unit tests (executed)
backend/tests/verify_phase2_crud_behavior.py  8 real behavior tests against sqlite (executed)
docker-compose.yml                            Postgres 16 + API service
backend/requirements.txt                      Python dependencies
```

This is the complete Phase 2 scope: sources/datasets CRUD only. No import
pipeline, no file upload, no `/api/datasets/import`, no admin endpoints, no
startup-seeding hook -- those are Phase 3 and are intentionally absent here.

## Database changes

**None beyond Phase 1.** No new tables, no altered columns, no new migration
file. Phase 2 is an API layer on top of the Phase 1 schema exactly as it
stood.

## API endpoints implemented

| Method | Path | Notes |
|---|---|---|
| GET | `/api/sources` | optional `?reliability_tier=` filter |
| GET | `/api/sources/{id}` | 404 if missing |
| POST | `/api/sources` | 201; 409 on duplicate `short_code` |
| PUT | `/api/sources/{id}` | partial update; `short_code` cannot be changed via this endpoint |
| DELETE | `/api/sources/{id}` | 409 if any dataset still references it |
| GET | `/api/datasets` | filters: `source_id`, `destination_country`, `reference_period`, `metric_definition_id`, `status`; plus `skip`/`limit` pagination |
| GET | `/api/datasets/{id}` | 404 if missing; nests full source and metric-definition detail |
| POST | `/api/datasets` | 201; 422 if `source_id`/`metric_definition_id` don't exist; 409 on duplicate identity |
| PUT | `/api/datasets/{id}` | **cannot** change `source_id`, `metric_definition_id`, `destination_country`, or `reference_period` — Pydantic rejects those keys with 422 |
| DELETE | `/api/datasets/{id}` | 409 unless the dataset is empty (no observations) and not `verified` — otherwise use `PUT status=deprecated` |
| GET | `/api/health` | liveness check |

No `/api/datasets/import`, no `/api/datasets/{id}/validation`, no
`/api/datasets/{id}/verify`, no `/api/datasets/{id}/deprecate` — all of
those are Phase 3 scope and are not part of this deliverable.

## Design decisions worth flagging

- **PUT never touches identity fields.** `DatasetUpdate` doesn't declare
  `source_id`/`metric_definition_id`/`destination_country`/`reference_period`
  as fields at all, and sets `extra="forbid"`.
- **DELETE is a guard, not a blanket operation.** A dataset can only be
  hard-deleted if it's empty (no observations) and not `verified`.
- **`limitations` is a required, non-empty field on every dataset.**

## Tests performed vs. not performed

This sandbox has no network access, so FastAPI/SQLAlchemy/psycopg2 cannot
be installed and the actual HTTP endpoints were **not** executed end-to-end.

**Actually executed, real pass/fail results:**
1. `python3 -m py_compile` on all files — syntax valid
2. `python3 -m unittest tests.test_validation_logic` — 19/19 pass
3. `python3 backend/tests/verify_phase2_crud_behavior.py` — 8/8 pass

**Written and reviewed, but NOT executed:**
`crud.py`, `api/sources.py`, `api/datasets.py`, `main.py`, `database.py`,
`schemas.py` as FastAPI/SQLAlchemy code — no `TestClient` run, no live HTTP
request, no real Postgres connection opened.

## What you need to install/run locally

Docker path (recommended):
```
docker compose up --build
```
Then visit `http://localhost:8000/docs` and `http://localhost:8000/api/health`.
Note: the database will be schema-only — Phase 2 does not seed Postgres on
startup (that's a Phase 3 item).

Non-Docker local path:
```
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg2://nsdo:nsdo_dev_password@localhost:5432/nsdo"
psql "$DATABASE_URL" -f migrations/001_init.sql
uvicorn app.main:app --reload --port 8000
```

Running just the tests that work without any install:
```
cd backend
python3 -m unittest tests.test_validation_logic -v
python3 tests/verify_phase2_crud_behavior.py
```
