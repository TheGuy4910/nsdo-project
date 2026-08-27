"""
Integration-style verification of the CRUD behaviour described in
backend/app/crud.py, run against SQLite since SQLAlchemy/psycopg2 cannot be
installed in this sandbox. This does not execute crud.py's actual SQLAlchemy
code -- it re-implements the same operations directly in sqlite3 to prove
the *behavior* the endpoints are supposed to have: uniqueness enforcement,
filter combinations, and the delete-guard rules from validation.py (which
IS executed for real, unlike this file -- see test_validation_logic.py).

Run with: python3 backend/tests/verify_phase2_crud_behavior.py
"""

import sqlite3
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "seed"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from seed_data import SOURCES, METRIC_DEFINITIONS, DATASETS
from app.services.validation import can_delete_dataset, can_delete_source

SCHEMA = """
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_code TEXT NOT NULL UNIQUE,
    reliability_tier TEXT NOT NULL
);
CREATE TABLE metric_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE
);
CREATE TABLE datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    metric_definition_id INTEGER NOT NULL REFERENCES metric_definitions(id),
    destination_country TEXT NOT NULL,
    reference_period TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    UNIQUE (source_id, destination_country, reference_period, metric_definition_id)
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id)
);
"""


def build_seeded_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    source_ids, metric_ids = {}, {}
    for s in SOURCES:
        cur = conn.execute("INSERT INTO sources (short_code, reliability_tier) VALUES (?,?)",
                            (s["short_code"], s["reliability_tier"]))
        source_ids[s["short_code"]] = cur.lastrowid
    for m in METRIC_DEFINITIONS:
        cur = conn.execute("INSERT INTO metric_definitions (code) VALUES (?)", (m["code"],))
        metric_ids[m["code"]] = cur.lastrowid
    for d in DATASETS:
        conn.execute(
            "INSERT INTO datasets (source_id, metric_definition_id, destination_country, "
            "reference_period, status) VALUES (?,?,?,?,?)",
            (source_ids[d["source"]], metric_ids[d["metric"]], d["destination_country"],
             d["reference_period"], "validated")
        )
    conn.commit()
    return conn, source_ids, metric_ids


class TestUniquenessConstraint(unittest.TestCase):
    """Mirrors crud.create_dataset's IntegrityError -> ConflictError path."""

    def test_duplicate_identity_is_rejected_by_the_database(self):
        conn, source_ids, metric_ids = build_seeded_db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO datasets (source_id, metric_definition_id, destination_country, "
                "reference_period, status) VALUES (?,?,?,?,?)",
                (source_ids["HESA"], metric_ids["hesa_enrolled_headcount"],
                 "United Kingdom", "2021/22", "draft")
            )
        conn.close()

    def test_same_country_different_period_is_allowed(self):
        conn, source_ids, metric_ids = build_seeded_db()
        # Should not raise: 2022/23 is a new, distinct dataset identity.
        conn.execute(
            "INSERT INTO datasets (source_id, metric_definition_id, destination_country, "
            "reference_period, status) VALUES (?,?,?,?,?)",
            (source_ids["HESA"], metric_ids["hesa_enrolled_headcount"],
             "United Kingdom", "2022/23", "draft")
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE destination_country='United Kingdom'"
        ).fetchone()[0]
        self.assertEqual(count, 5)  # 4 existing UK rows + this new one
        conn.close()


class TestFiltering(unittest.TestCase):
    """Mirrors crud.list_datasets' filter combinations."""

    def setUp(self):
        self.conn, self.source_ids, self.metric_ids = build_seeded_db()

    def tearDown(self):
        self.conn.close()

    def test_filter_by_country_only(self):
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE destination_country=?", ("United States",)
        ).fetchone()[0]
        self.assertEqual(rows, 4)

    def test_filter_by_country_and_status(self):
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE destination_country=? AND status=?",
            ("United States", "validated")
        ).fetchone()[0]
        self.assertEqual(rows, 4)

    def test_filter_by_source(self):
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE source_id=?", (self.source_ids["HESA"],)
        ).fetchone()[0]
        self.assertEqual(rows, 4)

    def test_filter_by_reference_period_across_countries(self):
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE reference_period=?", ("2021/22",)
        ).fetchone()[0]
        # UK 2021/22, US 2021/22, Canada 2021/22
        self.assertEqual(rows, 3)

    def test_filter_by_metric_definition(self):
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE metric_definition_id=?",
            (self.metric_ids["unverified_market_estimate"],)
        ).fetchone()[0]
        self.assertEqual(rows, 1)  # only the Malaysia estimate


class TestDeleteGuardsAgainstRealSeedData(unittest.TestCase):
    """
    Confirms the delete rule (from validation.py, executed for real) gives
    the correct answer when applied to the actual seeded dataset shapes,
    not just synthetic status/count pairs.
    """

    def test_every_seeded_dataset_is_currently_undeletable(self):
        conn, _, _ = build_seeded_db()
        for d in DATASETS:
            row = conn.execute(
                "SELECT id, status FROM datasets WHERE destination_country=? AND reference_period=?",
                (d["destination_country"], d["reference_period"])
            ).fetchone()
            dataset_id, status = row
            obs_count = len(d["observations"])
            ok, message = can_delete_dataset(status=status, observation_count=obs_count)
            self.assertFalse(
                ok,
                f"{d['destination_country']} {d['reference_period']} should be undeletable "
                f"(status={status}, observations={obs_count}) but can_delete_dataset allowed it"
            )
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
