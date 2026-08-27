# Nigerian Student Diaspora Observatory (NSDO)

A data-driven system for analysing and visualising the academic distribution of Nigerian students in foreign institutions. Built as a final-year Computer Science capstone project, NSDO tracks where Nigerian students are studying abroad — aggregated by destination country, institution type, and academic year — with full provenance on every figure. No data is fabricated; every number traces to a named source, a stated metric definition, and an explicit limitations record.

---

## Tech stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 |
| API | FastAPI 0.115 + Pydantic v2 |
| Import pipeline | Python stdlib `csv`/`io` + openpyxl |
| Analytics | Pure Python (no framework dependency) |
| Auth | passlib/bcrypt + python-jose JWT |
| Tests | Python stdlib `unittest` (236 tests) |
| Frontend | Vanilla HTML/CSS/JS — no framework |
| Runtime | Python 3.12, Uvicorn |
| Container | Docker + Docker Compose |

---

## Run locally with Docker

```bash
# 1. Copy the environment template and set a real JWT secret
cp .env.example .env
# Edit .env and replace JWT_SECRET_KEY with a strong random value:
# python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. Start the stack (builds the API image, starts Postgres, seeds DB on first boot)
docker compose up --build

# 3. Open in your browser
#    Frontend:   http://localhost:8000/
#    API docs:   http://localhost:8000/docs

# 4. Register the first admin user (bootstrap — no token required for the first account)
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'

# 5. Seed the reference data via the admin panel in the UI, or directly:
curl -s -X POST http://localhost:8000/api/admin/seed \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/api/auth/token \
    -d 'username=admin&password=your-password' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')"
```

All GET (read) endpoints are public — no login required to view or export data.

---

## Run the test suite

```bash
# Inside Docker (authoritative — 236/236, 0 skipped):
docker compose exec api python3 -m unittest discover -s tests -p "test_*.py" -v

# In the sandbox / without Docker (208/236 run, 28 skipped — missing passlib/jose/SQLAlchemy):
cd nsdo-project
python3 -m unittest discover -s backend/tests -p "test_*.py" -v
python3 backend/tests/verify_phase2_crud_behavior.py
python3 backend/tests/verify_phase3a_commit_behavior.py
python3 backend/seed/verify_local.py
```

---

## Project structure

```
nsdo-project/
├── backend/
│   ├── app/
│   │   ├── api/          — FastAPI routers (sources, datasets, observations,
│   │   │                   analytics, import_csv, import_xlsx, auth, admin)
│   │   ├── services/     — Pure Python business logic (csv_import, xlsx_import,
│   │   │                   analytics, characteristics, auth, seed_runtime,
│   │   │                   validation)
│   │   ├── models/       — SQLAlchemy ORM models
│   │   └── schemas.py    — Pydantic v2 request/response contracts
│   ├── migrations/       — Plain SQL: 001 (base schema), 002 (dimensions),
│   │                        003 (characteristics)
│   ├── seed/             — Reference data (11 verified datasets) + verify script
│   └── tests/            — 236 tests across 8 suites + 3 verify scripts
├── frontend/
│   ├── index.html        — Dashboard (trend chart, country cards, comparability warning)
│   ├── datasets.html     — Paginated dataset inventory with detail modal
│   ├── analytics.html    — Trend explorer, snapshot table, growth rates
│   ├── sources.html      — Sources by reliability tier
│   ├── import.html       — 4-step CSV/XLSX import wizard
│   ├── admin.html        — Admin panel (seed trigger, auth-gated)
│   ├── login.html        — Authentication form
│   ├── docs.html         — Full methodology writeup
│   ├── nsdo.css          — Shared design system
│   └── nsdo.js           — Shared API client, auth helpers, nav, formatters
├── docs/
│   ├── ARCHITECTURE.md   — Data model, request flow, auth model
│   ├── DOCKER_VERIFY.sh  — Integration smoke test script
│   └── PHASE_*.md        — Development phase notes
├── .env.example          — Environment variable documentation
└── docker-compose.yml
```

---

## Data integrity

Every number in the system traces to a named source, a metric definition, and a stated set of limitations. The analytics layer enforces this with a three-valued comparability verdict (Comparable / Methodology differs / Incomparable) on every cross-dataset operation. Gaps in data are represented as `null`, never zero or interpolated.

See [`frontend/docs.html`](frontend/docs.html) for the full methodology and data-integrity writeup (viewable at `http://localhost:8000/docs.html` when running).

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the data model relationships, CSV import request flow, and authentication model.
