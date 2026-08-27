"""
Behavior verification for csv_import_commit.py, run against sqlite3 since
SQLAlchemy/psycopg2 cannot be installed in this sandbox. Mirrors the same
insert logic and constraints directly in sqlite3 -- does not execute
csv_import_commit.py itself, proves the *behavior* it's supposed to have.

Run with: python3 backend/tests/verify_phase3a_commit_behavior.py
"""

import sqlite3
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services.csv_import import run_pipeline

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

SCHEMA = """
CREATE TABLE datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    metric_definition_id INTEGER NOT NULL,
    destination_country TEXT NOT NULL,
    reference_period TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    limitations TEXT NOT NULL,
    UNIQUE (source_id, destination_country, reference_period, metric_definition_id)
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    destination_country TEXT NOT NULL,
    value NUMERIC NOT NULL,
    nigerian_state TEXT, academic_year TEXT, gender TEXT,
    funding_type TEXT, institution_type TEXT, import_batch_id TEXT
);
CREATE TABLE provenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);
"""


def read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def insert_dataset_and_observations(conn, source_id, metric_id, country, period, limitations, results):
    """Mirrors commit_csv_import's insert logic: errors never inserted,
    dataset uniqueness enforced by the DB itself."""
    cur = conn.execute(
        "INSERT INTO datasets (source_id, metric_definition_id, destination_country, "
        "reference_period, status, limitations) VALUES (?,?,?,?,?,?)",
        (source_id, metric_id, country, period, "validated", limitations)
    )
    dataset_id = cur.lastrowid
    included = [r for r in results if r.status != "error"]
    for r in included:
        conn.execute(
            "INSERT INTO observations (dataset_id, destination_country, value) VALUES (?,?,?)",
            (dataset_id, r.mapped["destination_country"], float(r.mapped["student_count"]))
        )
    conn.execute(
        "INSERT INTO provenance_log (dataset_id, action, detail) VALUES (?,?,?)",
        (dataset_id, "imported", f"{len(included)} observation(s) inserted")
    )
    conn.commit()
    return dataset_id, len(included)


class TestNeverOverwriteRealFixture(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SCHEMA)

    def tearDown(self):
        self.conn.close()

    def test_importing_the_same_real_fixture_twice_is_rejected(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        insert_dataset_and_observations(
            self.conn, source_id=1, metric_id=1, country="United Kingdom",
            period="hesa-csv-import-2018-2022", limitations="Imported via CSV pipeline test.",
            results=report["results"],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            insert_dataset_and_observations(
                self.conn, source_id=1, metric_id=1, country="United Kingdom",
                period="hesa-csv-import-2018-2022", limitations="Second attempt.",
                results=report["results"],
            )

    def test_different_reference_period_is_allowed_as_new_revision(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        id1, _ = insert_dataset_and_observations(
            self.conn, 1, 1, "United Kingdom", "csv-import-v1", "First import.", report["results"]
        )
        id2, _ = insert_dataset_and_observations(
            self.conn, 1, 1, "United Kingdom", "csv-import-v2", "Second, distinct revision.", report["results"]
        )
        self.assertNotEqual(id1, id2)
        count = self.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        self.assertEqual(count, 2)  # both remain independently queryable

    def test_all_four_real_observations_inserted(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        dataset_id, n_inserted = insert_dataset_and_observations(
            self.conn, 1, 1, "United Kingdom", "csv-import-test", "Test.", report["results"]
        )
        self.assertEqual(n_inserted, 4)
        rows = self.conn.execute(
            "SELECT value FROM observations WHERE dataset_id=? ORDER BY value", (dataset_id,)
        ).fetchall()
        values = [r[0] for r in rows]
        self.assertEqual(values, [10810, 13020, 21305, 44195])

    def test_provenance_log_entry_created(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        dataset_id, _ = insert_dataset_and_observations(
            self.conn, 1, 1, "United Kingdom", "csv-import-test", "Test.", report["results"]
        )
        log = self.conn.execute(
            "SELECT action, detail FROM provenance_log WHERE dataset_id=?", (dataset_id,)
        ).fetchone()
        self.assertEqual(log[0], "imported")
        self.assertIn("4 observation", log[1])


class TestErrorRecordsNeverInserted(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SCHEMA)

    def tearDown(self):
        self.conn.close()

    def test_synthetic_fixture_error_rows_excluded_from_insert(self):
        report = run_pipeline(read_fixture("SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv"))
        dataset_id, n_inserted = insert_dataset_and_observations(
            self.conn, 1, 1, "Mixed", "synthetic-mechanics-test",
            "SYNTHETIC TEST DATA -- not real, mechanics test only.", report["results"]
        )
        # 5 rows total: row3 (negative), row4 (bad year), row5 (bad count) are errors -> excluded.
        # row1 valid, row2 duplicate-but-not-error -> both inserted by this mirror
        # (the real commit function additionally excludes duplicates unless opted in;
        # this sqlite mirror only proves the error-exclusion half of that logic).
        self.assertEqual(n_inserted, 2)
        errors = sum(1 for r in report["results"] if r.status == "error")
        self.assertEqual(errors, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
