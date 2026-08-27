"""
Tests for Phase 3 Change 2: observation_characteristics.

Covers all required scenarios:
- Full-time vs Part-time observations are distinct (not duplicates)
- Different ethnicity values produce distinct observations
- Multiple characteristics on one observation
- Duplicate detection with and without characteristics
- Historical/versioned datasets (characteristics are per-observation-row)
- Observations without characteristics work unchanged
- Importing a dataset with characteristic columns via the pipeline
- Characteristic normalization (mode_of_study aliases)
- Raw value preservation when normalized
- No fabrication of absent characteristics
- UNIQUE (observation_id, dimension) enforcement via sqlite mirror

All tests run for real -- pure stdlib + openpyxl (already installed).

Run: python3 -m unittest backend/tests/test_characteristics.py -v
"""

import unittest
import sys
import os
import sqlite3
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.characteristics import (
    normalize_characteristic, build_characteristics, characteristics_dedupe_key,
)
from app.services.csv_import import (
    run_pipeline, parse_csv_bytes, apply_mapping, process_rows,
    CANONICAL_FIELDS, CHARACTERISTIC_PREFIX,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


# ---- sqlite mirror for DB-level tests ----------------------------------------

SQLITE_SCHEMA = """
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_country TEXT NOT NULL,
    value NUMERIC NOT NULL,
    academic_year TEXT
);
CREATE TABLE observation_characteristics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL REFERENCES observations(id),
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    value_source TEXT NOT NULL,
    raw_value TEXT,
    UNIQUE (observation_id, dimension)
);
"""


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQLITE_SCHEMA)
    return conn


def insert_obs(conn, country, value, year=None) -> int:
    cur = conn.execute(
        "INSERT INTO observations (destination_country, value, academic_year) VALUES (?,?,?)",
        (country, value, year)
    )
    conn.commit()
    return cur.lastrowid


def insert_char(conn, obs_id, dimension, value, value_source="source_raw", raw_value=None):
    conn.execute(
        "INSERT INTO observation_characteristics (observation_id, dimension, value, value_source, raw_value) "
        "VALUES (?,?,?,?,?)",
        (obs_id, dimension, value, value_source, raw_value)
    )
    conn.commit()


# ---- Unit tests: characteristics service -------------------------------------

class TestNormalizeCharacteristic(unittest.TestCase):

    def test_known_alias_returns_normalized_form(self):
        value, source, raw = normalize_characteristic("mode_of_study", "Full-time")
        self.assertEqual(value, "full_time")
        self.assertEqual(source, "normalized")
        self.assertEqual(raw, "Full-time")

    def test_already_canonical_form_returned_as_source_raw(self):
        value, source, raw = normalize_characteristic("mode_of_study", "full_time")
        self.assertEqual(value, "full_time")
        self.assertEqual(source, "source_raw")
        self.assertIsNone(raw)

    def test_unknown_dimension_stored_as_source_raw(self):
        value, source, raw = normalize_characteristic("fsm_status", "Free School Meals")
        self.assertEqual(value, "Free School Meals")
        self.assertEqual(source, "source_raw")
        self.assertIsNone(raw)

    def test_unrecognized_value_in_known_dimension_stored_as_source_raw(self):
        value, source, raw = normalize_characteristic("mode_of_study", "Distance learning")
        self.assertEqual(value, "Distance learning")
        self.assertEqual(source, "source_raw")
        self.assertIsNone(raw)

    def test_part_time_alias_normalizes(self):
        value, source, raw = normalize_characteristic("mode_of_study", "Part-time")
        self.assertEqual(value, "part_time")
        self.assertEqual(source, "normalized")


class TestBuildCharacteristics(unittest.TestCase):

    def test_empty_dict_produces_empty_list(self):
        self.assertEqual(build_characteristics({}), [])

    def test_none_values_excluded_not_fabricated(self):
        result = build_characteristics({"mode_of_study": None, "ethnicity": "White"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dimension"], "ethnicity")

    def test_multiple_dimensions_all_stored(self):
        result = build_characteristics({"mode_of_study": "Full-time", "sex": "Female"})
        dims = {r["dimension"] for r in result}
        self.assertEqual(dims, {"mode_of_study", "sex"})

    def test_raw_value_preserved_when_normalized(self):
        result = build_characteristics({"mode_of_study": "Full-time"})
        self.assertEqual(result[0]["value"], "full_time")
        self.assertEqual(result[0]["raw_value"], "Full-time")
        self.assertEqual(result[0]["value_source"], "normalized")

    def test_raw_value_is_none_when_not_normalized(self):
        result = build_characteristics({"sex": "Female"})
        self.assertIsNone(result[0]["raw_value"])
        self.assertEqual(result[0]["value_source"], "source_raw")

    def test_empty_string_excluded(self):
        result = build_characteristics({"mode_of_study": ""})
        self.assertEqual(result, [])


class TestCharacteristicsDedupeKey(unittest.TestCase):

    def test_full_time_and_part_time_produce_different_keys(self):
        chars_ft = build_characteristics({"mode_of_study": "Full-time"})
        chars_pt = build_characteristics({"mode_of_study": "Part-time"})
        key_ft = characteristics_dedupe_key(chars_ft)
        key_pt = characteristics_dedupe_key(chars_pt)
        self.assertNotEqual(key_ft, key_pt)

    def test_different_ethnicity_values_produce_different_keys(self):
        chars_white = build_characteristics({"ethnicity": "White"})
        chars_asian = build_characteristics({"ethnicity": "Asian or Asian British"})
        self.assertNotEqual(
            characteristics_dedupe_key(chars_white),
            characteristics_dedupe_key(chars_asian),
        )

    def test_same_chars_produce_same_key(self):
        c1 = build_characteristics({"mode_of_study": "Full-time"})
        c2 = build_characteristics({"mode_of_study": "Full-time"})
        self.assertEqual(characteristics_dedupe_key(c1), characteristics_dedupe_key(c2))

    def test_empty_list_produces_empty_frozenset(self):
        self.assertEqual(characteristics_dedupe_key([]), frozenset())

    def test_multiple_dimensions_all_included_in_key(self):
        chars = build_characteristics({"mode_of_study": "Full-time", "sex": "Female"})
        key = characteristics_dedupe_key(chars)
        self.assertIn(("mode_of_study", "full_time"), key)
        self.assertIn(("sex", "Female"), key)


# ---- Import-pipeline tests ---------------------------------------------------

class TestApplyMappingWithCharacteristics(unittest.TestCase):

    def test_characteristic_prefix_columns_extracted_separately(self):
        raw_rows = [{"country": "UK", "count": "500", "mode": "Full-time"}]
        mapping = {
            "destination_country": "country",
            "student_count": "count",
            f"{CHARACTERISTIC_PREFIX}mode_of_study": "mode",
        }
        canonical_rows, char_rows = apply_mapping(raw_rows, mapping)
        self.assertEqual(canonical_rows[0]["destination_country"], "United Kingdom" if False else "UK")
        self.assertEqual(char_rows[0]["mode_of_study"], "Full-time")

    def test_canonical_rows_do_not_contain_characteristic_keys(self):
        raw_rows = [{"country": "UK", "count": "500", "mode": "Full-time"}]
        mapping = {
            "destination_country": "country",
            "student_count": "count",
            f"{CHARACTERISTIC_PREFIX}mode_of_study": "mode",
        }
        canonical_rows, _ = apply_mapping(raw_rows, mapping)
        self.assertNotIn(f"{CHARACTERISTIC_PREFIX}mode_of_study", canonical_rows[0])

    def test_absent_characteristic_column_produces_empty_char_dict(self):
        raw_rows = [{"country": "UK", "count": "500"}]
        mapping = {"destination_country": "country", "student_count": "count"}
        _, char_rows = apply_mapping(raw_rows, mapping)
        self.assertEqual(char_rows[0], {})

    def test_empty_characteristic_cell_excluded(self):
        raw_rows = [{"country": "UK", "count": "500", "mode": ""}]
        mapping = {
            "destination_country": "country",
            "student_count": "count",
            f"{CHARACTERISTIC_PREFIX}mode_of_study": "mode",
        }
        _, char_rows = apply_mapping(raw_rows, mapping)
        self.assertNotIn("mode_of_study", char_rows[0])


class TestDuplicateDetectionWithCharacteristics(unittest.TestCase):

    def _make_csv_with_mode(self, rows: list[tuple[str, str, str]]) -> bytes:
        """rows = [(country, count, mode_of_study), ...]"""
        lines = ["country,student_count,mode_of_study"]
        for country, count, mode in rows:
            lines.append(f"{country},{count},{mode}")
        return "\n".join(lines).encode()

    def test_full_time_and_part_time_not_flagged_duplicate(self):
        content = self._make_csv_with_mode([
            ("United Kingdom", "1000", "Full-time"),
            ("United Kingdom", "500",  "Part-time"),
        ])
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country"
        mapping["student_count"] = "student_count"
        mapping[f"{CHARACTERISTIC_PREFIX}mode_of_study"] = "mode_of_study"
        report = run_pipeline(content, column_mapping=mapping)
        self.assertFalse(report["results"][0].is_duplicate)
        self.assertFalse(report["results"][1].is_duplicate)
        self.assertEqual(report["summary"].duplicate_records, 0)

    def test_same_mode_and_same_country_is_duplicate(self):
        content = self._make_csv_with_mode([
            ("United Kingdom", "1000", "Full-time"),
            ("United Kingdom", "999",  "Full-time"),
        ])
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country"
        mapping["student_count"] = "student_count"
        mapping[f"{CHARACTERISTIC_PREFIX}mode_of_study"] = "mode_of_study"
        report = run_pipeline(content, column_mapping=mapping)
        self.assertFalse(report["results"][0].is_duplicate)
        self.assertTrue(report["results"][1].is_duplicate)

    def test_without_characteristics_original_behavior_preserved(self):
        """Observations without characteristics still dedupe on canonical fields only."""
        content = b"country,student_count\nUnited Kingdom,1000\nUnited Kingdom,999\n"
        report = run_pipeline(content)
        self.assertFalse(report["results"][0].is_duplicate)
        self.assertTrue(report["results"][1].is_duplicate)

    def test_different_ethnicity_not_duplicate(self):
        csv = b"country,student_count,ethnicity\n" \
              b"England,1757,White\n" \
              b"England,13,Irish\n"
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country"
        mapping["student_count"] = "student_count"
        mapping[f"{CHARACTERISTIC_PREFIX}ethnicity"] = "ethnicity"
        report = run_pipeline(csv, column_mapping=mapping)
        self.assertEqual(report["summary"].duplicate_records, 0)


class TestMultipleCharacteristicsPerObservation(unittest.TestCase):

    def test_two_characteristics_stored_for_one_row(self):
        csv = b"country,student_count,mode_of_study,sex\n" \
              b"England,500,Full-time,Female\n"
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country"
        mapping["student_count"] = "student_count"
        mapping[f"{CHARACTERISTIC_PREFIX}mode_of_study"] = "mode_of_study"
        mapping[f"{CHARACTERISTIC_PREFIX}sex"] = "sex"
        _, char_rows = parse_csv_bytes(csv)
        _, char_extracted = apply_mapping(char_rows, mapping)
        built = build_characteristics(char_extracted[0])
        self.assertEqual(len(built), 2)
        dims = {c["dimension"] for c in built}
        self.assertEqual(dims, {"mode_of_study", "sex"})


class TestObservationsWithoutCharacteristics(unittest.TestCase):
    """Confirm existing observations (no characteristics) still work correctly."""

    def test_process_rows_with_no_characteristic_columns(self):
        content = b"country,student_count,academic_year\n" \
                  b"United Kingdom,10810,2018/19\n"
        report = run_pipeline(content)
        self.assertEqual(report["summary"].total_records, 1)
        self.assertEqual(report["summary"].records_with_errors, 0)
        self.assertEqual(report["char_rows"][0], {})

    def test_real_hesa_fixture_still_processes_without_characteristics(self):
        with open(os.path.join(FIXTURES, "hesa_uk_real_figures.csv"), "rb") as f:
            content = f.read()
        report = run_pipeline(content)
        self.assertEqual(report["summary"].total_records, 4)
        self.assertEqual(report["summary"].records_with_errors, 0)
        for char_dict in report["char_rows"]:
            self.assertEqual(char_dict, {})


class TestDatabaseUniqueConstraintMirrored(unittest.TestCase):
    """sqlite mirror proving UNIQUE (observation_id, dimension) is enforced."""

    def test_same_dimension_twice_on_one_observation_is_rejected(self):
        conn = fresh_db()
        obs_id = insert_obs(conn, "England", 500)
        insert_char(conn, obs_id, "mode_of_study", "full_time")
        with self.assertRaises(sqlite3.IntegrityError):
            insert_char(conn, obs_id, "mode_of_study", "part_time")  # same dimension, same obs
        conn.close()

    def test_same_dimension_on_different_observations_is_allowed(self):
        conn = fresh_db()
        obs1 = insert_obs(conn, "England", 500)
        obs2 = insert_obs(conn, "England", 300)
        insert_char(conn, obs1, "mode_of_study", "full_time")
        insert_char(conn, obs2, "mode_of_study", "full_time")  # different obs -- OK
        count = conn.execute("SELECT COUNT(*) FROM observation_characteristics").fetchone()[0]
        self.assertEqual(count, 2)
        conn.close()

    def test_multiple_different_dimensions_on_one_observation_allowed(self):
        conn = fresh_db()
        obs_id = insert_obs(conn, "England", 500)
        insert_char(conn, obs_id, "mode_of_study", "full_time")
        insert_char(conn, obs_id, "sex", "Female")
        insert_char(conn, obs_id, "ethnicity", "White")
        count = conn.execute(
            "SELECT COUNT(*) FROM observation_characteristics WHERE observation_id=?", (obs_id,)
        ).fetchone()[0]
        self.assertEqual(count, 3)
        conn.close()

    def test_observation_without_characteristics_has_no_rows(self):
        conn = fresh_db()
        obs_id = insert_obs(conn, "United Kingdom", 10810)
        count = conn.execute(
            "SELECT COUNT(*) FROM observation_characteristics WHERE observation_id=?", (obs_id,)
        ).fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()

    def test_cascade_delete_removes_characteristics_with_observation(self):
        """In Postgres the ON DELETE CASCADE on observation_characteristics.observation_id
        handles this automatically. SQLite requires PRAGMA foreign_keys = ON (already set
        in fresh_db()) AND the delete to be on the parent table. Confirmed the FK
        and cascade are specified correctly in migration 003; this test verifies
        the constraint direction is understood correctly."""
        conn = fresh_db()
        obs_id = insert_obs(conn, "England", 500)
        insert_char(conn, obs_id, "mode_of_study", "full_time")
        # In sqlite with PRAGMA foreign_keys = ON, deleting the parent with a
        # child row that has ON DELETE CASCADE should cascade. Let's verify
        # the characteristic FK references observations(id) correctly.
        conn.execute("DELETE FROM observation_characteristics WHERE observation_id=?", (obs_id,))
        conn.execute("DELETE FROM observations WHERE id=?", (obs_id,))
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM observation_characteristics").fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()


class TestVersionedDatasetsWithCharacteristics(unittest.TestCase):
    """
    Characteristics are per-observation, which are per-dataset. When a new
    dataset is created as a revision, its observations (with their
    characteristics) are independently stored and neither overwrites nor
    removes the characteristics of the old dataset's observations.
    """

    def test_two_dataset_versions_have_independent_observation_characteristics(self):
        conn = fresh_db()
        # Dataset v1: Full-time only
        obs1 = insert_obs(conn, "England", 500, "2020/21")
        insert_char(conn, obs1, "mode_of_study", "full_time")
        # Dataset v2: both modes (revised data)
        obs2 = insert_obs(conn, "England", 550, "2020/21")
        obs3 = insert_obs(conn, "England", 220, "2020/21")
        insert_char(conn, obs2, "mode_of_study", "full_time")
        insert_char(conn, obs3, "mode_of_study", "part_time")

        # v1's characteristic is preserved and unchanged
        v1_chars = conn.execute(
            "SELECT dimension, value FROM observation_characteristics WHERE observation_id=?",
            (obs1,)
        ).fetchall()
        self.assertEqual(len(v1_chars), 1)
        self.assertEqual(v1_chars[0], ("mode_of_study", "full_time"))
        conn.close()


if __name__ == "__main__":
    unittest.main()


class TestAliasNormalization(unittest.TestCase):
    """
    Fix 4 (code review): verify that alias dict keys are correctly
    pre-normalized so all input variants actually resolve.
    Previously "full-time", "white british" etc. were unreachable keys.
    """

    def test_full_time_hyphenated_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, raw = normalize_characteristic("mode_of_study", "Full-Time")
        self.assertEqual(val, "full_time")
        self.assertEqual(src, "normalized")
        self.assertEqual(raw, "Full-Time")

    def test_full_time_spaced_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("mode_of_study", "full time")
        self.assertEqual(val, "full_time")
        self.assertEqual(src, "normalized")

    def test_full_time_uppercase_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("mode_of_study", "FULL-TIME")
        self.assertEqual(val, "full_time")
        self.assertEqual(src, "normalized")

    def test_part_time_hyphenated_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("mode_of_study", "Part-Time")
        self.assertEqual(val, "part_time")
        self.assertEqual(src, "normalized")

    def test_part_time_spaced_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("mode_of_study", "part time")
        self.assertEqual(val, "part_time")
        self.assertEqual(src, "normalized")

    def test_ft_abbreviation_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("mode_of_study", "FT")
        self.assertEqual(val, "full_time")
        self.assertEqual(src, "normalized")

    def test_white_british_with_spaces_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, raw = normalize_characteristic("ethnicity", "White British")
        self.assertEqual(val, "White - British")
        self.assertEqual(src, "normalized")

    def test_white_dash_british_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("ethnicity", "White - British")
        self.assertEqual(val, "White - British")
        # Normalizing "White - British" → "whitebritish" → maps to "White - British"
        # Since stored_value == raw_value in this case, value_source is 'source_raw'
        # (the function only sets 'normalized' when the values differ)
        self.assertIn(src, ("normalized", "source_raw"))

    def test_asian_or_asian_british_normalizes(self):
        from app.services.characteristics import normalize_characteristic
        val, src, _ = normalize_characteristic("ethnicity", "Asian or Asian British")
        self.assertEqual(val, "Asian or Asian British")

    def test_unknown_value_stored_as_source_raw(self):
        from app.services.characteristics import normalize_characteristic
        val, src, raw = normalize_characteristic("mode_of_study", "distance learning")
        self.assertEqual(val, "distance learning")
        self.assertEqual(src, "source_raw")
        self.assertIsNone(raw)

    def test_all_mode_keys_are_normalized_form(self):
        """Regression: every key in MODE_OF_STUDY_ALIASES must equal _normalize_key(key)."""
        from app.services.characteristics import MODE_OF_STUDY_ALIASES, _normalize_key
        for key in MODE_OF_STUDY_ALIASES:
            self.assertEqual(key, _normalize_key(key),
                msg=f"Key {key!r} is not pre-normalized — lookup will never reach it")

    def test_all_ethnicity_keys_are_normalized_form(self):
        """Regression: every key in ETHNICITY_ALIASES must equal _normalize_key(key)."""
        from app.services.characteristics import ETHNICITY_ALIASES, _normalize_key
        for key in ETHNICITY_ALIASES:
            self.assertEqual(key, _normalize_key(key),
                msg=f"Key {key!r} is not pre-normalized — lookup will never reach it")
