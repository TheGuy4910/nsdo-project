# Phase 1 — database schema and seed data

## What this phase delivers

- `backend/migrations/001_init.sql` — authoritative PostgreSQL schema (7 tables)
- `backend/app/models/models.py` — matching SQLAlchemy 2.0 ORM models
- `backend/seed/seed_data.py` — every seed record with its source, definition, and
  stated limitations. **No fabricated values.** A `KNOWN_GAPS` list documents what
  is deliberately left empty rather than invented.
- `backend/seed/verify_local.py` — proof-of-correctness script, executed in this
  sandbox against SQLite, confirming:
  1. row counts land where expected
  2. every observation traces to a source with a reliability tier
  3. the metric_definition foreign key genuinely separates HESA counts from
     Open Doors counts from press-derived counts
  4. the one `unverified`-tier dataset (Malaysia) is queryable and
     distinguishable from `official_primary`/`official_secondary` ones
  5. the gap list is present and non-empty

## Honesty note on execution environment

This sandbox cannot install PostgreSQL, SQLAlchemy, or FastAPI (no network
access). `models.py` is written and reviewed but not executed here.
`verify_local.py` proves the *schema and seed logic* are sound using
Python's built-in `sqlite3` as a stand-in.

## Data currently seeded (11 datasets, 11 observations)

| Country | Period | Value | Source | Reliability |
|---|---|---|---|---|
| United Kingdom | 2018/19 | 10,810 | HESA | official_primary |
| United Kingdom | 2019/20 | 13,020 | HESA | official_primary |
| United Kingdom | 2020/21 | 21,305 | HESA | official_primary |
| United Kingdom | 2021/22 | 44,195 | HESA | official_primary |
| United States | 2021/22 | 14,438 | IIE Open Doors | official_secondary |
| United States | 2022/23 | 17,640 | IIE Open Doors | official_secondary |
| United States | 2023/24 | 20,029 | IIE Open Doors | official_secondary |
| United States | 2024/25 | ~22,000 | IIE Open Doors (press-reported) | official_secondary |
| Canada | 2021/22 | 13,745 | Press citing IRCC | credible_secondary |
| Malaysia | undated | ~10,000 | Secondary aggregator | **unverified** |
| Global (all destinations) | 2018 | 76,338 | UNESCO / World Bank | official_primary |
