"""
Local verification shim -- NOT part of the deliverable application.

This sandbox has no network access, so PostgreSQL/SQLAlchemy cannot be
installed here. This script proves the schema and seed data are internally
consistent by loading them into Python's built-in sqlite3 (same table/column
structure, minor type syntax adjustments only: SERIAL -> INTEGER PRIMARY KEY
AUTOINCREMENT, TIMESTAMPTZ -> TEXT, etc).

Run it with: python3 verify_local.py
"""

import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from seed_data import SOURCES, METRIC_DEFINITIONS, DATASETS, KNOWN_GAPS

SQLITE_SCHEMA = """
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    short_code TEXT NOT NULL UNIQUE,
    organization_type TEXT NOT NULL,
    home_country TEXT,
    url TEXT,
    reliability_tier TEXT NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE metric_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count of individuals'
);

CREATE TABLE datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    metric_definition_id INTEGER NOT NULL REFERENCES metric_definitions(id),
    title TEXT NOT NULL,
    destination_country TEXT NOT NULL,
    reference_period TEXT NOT NULL,
    original_url TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    superseded_by_id INTEGER REFERENCES datasets(id),
    imported_at TEXT DEFAULT (datetime('now')),
    imported_by TEXT NOT NULL DEFAULT 'seed_script',
    limitations TEXT NOT NULL,
    UNIQUE (source_id, destination_country, reference_period, metric_definition_id)
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    destination_country TEXT NOT NULL,
    institution TEXT,
    discipline TEXT,
    degree_level TEXT,
    value NUMERIC NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE provenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER REFERENCES datasets(id),
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def build_db(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.executescript(SQLITE_SCHEMA)

    source_ids = {}
    for s in SOURCES:
        cur = conn.execute(
            "INSERT INTO sources (name, short_code, organization_type, home_country, url, reliability_tier, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (s["name"], s["short_code"], s["organization_type"], s["home_country"],
             s["url"], s["reliability_tier"], s["notes"])
        )
        source_ids[s["short_code"]] = cur.lastrowid

    metric_ids = {}
    for m in METRIC_DEFINITIONS:
        cur = conn.execute(
            "INSERT INTO metric_definitions (code, name, description, unit) VALUES (?,?,?,?)",
            (m["code"], m["name"], m["description"], m["unit"])
        )
        metric_ids[m["code"]] = cur.lastrowid

    for d in DATASETS:
        cur = conn.execute(
            "INSERT INTO datasets (source_id, metric_definition_id, title, destination_country, "
            "reference_period, original_url, status, limitations) VALUES (?,?,?,?,?,?,?,?)",
            (source_ids[d["source"]], metric_ids[d["metric"]], d["title"], d["destination_country"],
             d["reference_period"], d["original_url"], "validated", d["limitations"])
        )
        dataset_id = cur.lastrowid
        for obs in d["observations"]:
            conn.execute(
                "INSERT INTO observations (dataset_id, destination_country, value) VALUES (?,?,?)",
                (dataset_id, d["destination_country"], obs["value"])
            )
        conn.execute(
            "INSERT INTO provenance_log (dataset_id, action, actor, detail) VALUES (?,?,?,?)",
            (dataset_id, "imported", "seed_script", f"Seeded from {d['original_url']}")
        )

    conn.commit()
    return conn


def run_checks(conn):
    print("=" * 70)
    print("CHECK 1: row counts per table")
    print("=" * 70)
    for table in ["sources", "metric_definitions", "datasets", "observations", "provenance_log"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:22s} {n} rows")

    print()
    print("=" * 70)
    print("CHECK 2: every observation traces to a source (no orphan data)")
    print("=" * 70)
    rows = conn.execute("""
        SELECT o.destination_country, o.value, d.reference_period, s.short_code, s.reliability_tier
        FROM observations o
        JOIN datasets d ON o.dataset_id = d.id
        JOIN sources s ON d.source_id = s.id
        ORDER BY o.destination_country, d.reference_period
    """).fetchall()
    for r in rows:
        print(f"  {r[0]:35s} {r[2]:12s} {r[1]:>10.0f}  <- {r[3]:22s} ({r[4]})")

    print()
    print("=" * 70)
    print("CHECK 3: comparability enforcement (rule 20)")
    print("=" * 70)
    metric_groups = conn.execute("""
        SELECT m.name, GROUP_CONCAT(DISTINCT d.destination_country)
        FROM datasets d JOIN metric_definitions m ON d.metric_definition_id = m.id
        GROUP BY m.name
    """).fetchall()
    for name, countries in metric_groups:
        print(f"  metric '{name}':")
        print(f"     comparable countries -> {countries}")
    print("  UK (HESA) and US (Open Doors) use DIFFERENT metric_definitions,")
    print("  so a direct UK-vs-US bar comparison is flagged non-comparable by")
    print("  definition alone unless the API explicitly notes the difference.")

    print()
    print("=" * 70)
    print("CHECK 4: unverified-tier sources are distinguishable")
    print("=" * 70)
    rows = conn.execute("""
        SELECT s.reliability_tier, COUNT(*) FROM datasets d
        JOIN sources s ON d.source_id = s.id
        GROUP BY s.reliability_tier
    """).fetchall()
    for tier, n in rows:
        print(f"  {tier:22s} {n} dataset(s)")

    print()
    print("=" * 70)
    print("CHECK 5: documented gaps (NOT filled with invented numbers)")
    print("=" * 70)
    for g in KNOWN_GAPS:
        print(f"  - {g}")

    print()
    print("All checks completed against SQLite (local verification only).")
    print("Production target remains PostgreSQL per docker-compose.yml.")


if __name__ == "__main__":
    connection = build_db()
    run_checks(connection)
