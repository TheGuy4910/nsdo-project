"""
Tests for app/services/csv_import.py.

These run for real, right now: csv_import.py has zero external dependency
(stdlib csv/io/re only), so unlike the FastAPI/SQLAlchemy layers, every one
of these is a genuine executed test, not a simulation.

Run with: python3 -m unittest backend/tests/test_csv_import.py -v
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.csv_import import (
    parse_csv_bytes, suggest_column_mapping, apply_mapping,
    normalize_country, normalize_degree_level, validate_record,
    detect_duplicates, compute_summary, run_pipeline, CANONICAL_FIELDS,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


class TestCsvParsing(unittest.TestCase):
    def test_parses_simple_csv(self):
        content = b"country,student_count\nUnited Kingdom,100\n"
        headers, rows = parse_csv_bytes(content)
        self.assertEqual(headers, ["country", "student_count"])
        self.assertEqual(rows, [{"country": "United Kingdom", "student_count": "100"}])

    def test_handles_utf8_bom(self):
        content = "country,student_count\nCanada,50\n".encode("utf-8-sig")
        headers, rows = parse_csv_bytes(content)
        self.assertEqual(headers[0], "country")  # BOM stripped, not part of header
        self.assertEqual(rows[0]["country"], "Canada")

    def test_raises_on_empty_content(self):
        with self.assertRaises(ValueError):
            parse_csv_bytes(b"")

    def test_real_fixture_parses_correctly(self):
        headers, rows = parse_csv_bytes(read_fixture("hesa_uk_real_figures.csv"))
        self.assertEqual(headers, ["country", "academic_year", "student_count"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["student_count"], "10810")
        self.assertEqual(rows[3]["student_count"], "44195")


class TestColumnMapping(unittest.TestCase):
    def test_suggests_exact_synonym_matches(self):
        mapping = suggest_column_mapping(["country", "student_count"])
        self.assertEqual(mapping["destination_country"], "country")
        self.assertEqual(mapping["student_count"], "student_count")

    def test_suggests_matches_ignoring_case_and_punctuation(self):
        mapping = suggest_column_mapping(["Country ", "Student-Count"])
        self.assertEqual(mapping["destination_country"], "Country ")
        self.assertEqual(mapping["student_count"], "Student-Count")

    def test_unmatched_canonical_fields_map_to_none(self):
        mapping = suggest_column_mapping(["country", "student_count"])
        self.assertIsNone(mapping["nigerian_state"])
        self.assertIsNone(mapping["gender"])

    def test_all_canonical_fields_present_in_output(self):
        mapping = suggest_column_mapping(["country"])
        self.assertEqual(set(mapping.keys()), set(CANONICAL_FIELDS))


class TestApplyMapping(unittest.TestCase):
    def test_maps_values_to_canonical_keys(self):
        raw_rows = [{"Country": "United Kingdom", "Count": "100"}]
        mapping = {"destination_country": "Country", "student_count": "Count"}
        canonical_rows, _ = apply_mapping(raw_rows, mapping)
        self.assertEqual(canonical_rows[0]["destination_country"], "United Kingdom")
        self.assertEqual(canonical_rows[0]["student_count"], "100")

    def test_unmapped_canonical_field_is_none_not_fabricated(self):
        raw_rows = [{"Country": "United Kingdom", "Count": "100"}]
        mapping = {"destination_country": "Country", "student_count": "Count"}
        canonical_rows, _ = apply_mapping(raw_rows, mapping)
        self.assertIsNone(canonical_rows[0]["nigerian_state"])
        self.assertIsNone(canonical_rows[0]["gender"])
        self.assertIsNone(canonical_rows[0]["institution_type"])

    def test_empty_string_cell_becomes_none(self):
        raw_rows = [{"Country": "United Kingdom", "State": "  "}]
        mapping = {"destination_country": "Country", "nigerian_state": "State"}
        canonical_rows, _ = apply_mapping(raw_rows, mapping)
        self.assertIsNone(canonical_rows[0]["nigerian_state"])


class TestNormalization(unittest.TestCase):
    def test_uk_normalizes_to_united_kingdom(self):
        normalized, changed = normalize_country("UK")
        self.assertEqual(normalized, "United Kingdom")
        self.assertTrue(changed)

    def test_already_canonical_country_unchanged(self):
        normalized, changed = normalize_country("United Kingdom")
        self.assertEqual(normalized, "United Kingdom")
        self.assertFalse(changed)

    def test_unrecognized_country_passed_through_unchanged(self):
        normalized, changed = normalize_country("Ruritania")
        self.assertEqual(normalized, "Ruritania")
        self.assertFalse(changed)

    def test_msc_normalizes_to_postgraduate_taught(self):
        normalized, changed = normalize_degree_level("MSc")
        self.assertEqual(normalized, "postgraduate_taught")
        self.assertTrue(changed)

    def test_none_passes_through(self):
        self.assertEqual(normalize_country(None), (None, False))
        self.assertEqual(normalize_degree_level(None), (None, False))


class TestValidation(unittest.TestCase):
    def test_missing_destination_country_is_error(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["student_count"] = "100"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "error")
        self.assertTrue(any(i.rule == "missing_required_field" and i.field == "destination_country"
                             for i in result.issues))

    def test_missing_student_count_is_error(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["destination_country"] = "United Kingdom"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "error")

    def test_negative_student_count_is_error(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["destination_country"] = "United States"
        mapped["student_count"] = "-5"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "error")
        self.assertTrue(any(i.rule == "negative_value" for i in result.issues))

    def test_non_numeric_student_count_is_error(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["destination_country"] = "Canada"
        mapped["student_count"] = "many"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "error")
        self.assertTrue(any(i.rule == "invalid_student_count" for i in result.issues))

    def test_valid_record_has_no_errors(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["destination_country"] = "United Kingdom"
        mapped["student_count"] = "10810"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "valid")

    def test_malformed_year_is_error(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["destination_country"] = "Canada"
        mapped["student_count"] = "300"
        mapped["academic_year"] = "not-a-year"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "error")
        self.assertTrue(any(i.rule == "invalid_year_format" for i in result.issues))

    def test_implausible_year_is_warning_not_error(self):
        mapped = {f: None for f in CANONICAL_FIELDS}
        mapped["destination_country"] = "Canada"
        mapped["student_count"] = "300"
        mapped["academic_year"] = "1850"
        result = validate_record(mapped, 0)
        self.assertEqual(result.status, "warning")

    def test_valid_academic_year_formats(self):
        for year in ["2021/22", "2018"]:
            mapped = {f: None for f in CANONICAL_FIELDS}
            mapped["destination_country"] = "Canada"
            mapped["student_count"] = "300"
            mapped["academic_year"] = year
            result = validate_record(mapped, 0)
            self.assertEqual(result.status, "valid", f"year '{year}' should be valid")


class TestDuplicateDetection(unittest.TestCase):
    def test_second_identical_row_flagged_first_is_not(self):
        rows = [
            {f: None for f in CANONICAL_FIELDS},
            {f: None for f in CANONICAL_FIELDS},
        ]
        for r in rows:
            r["destination_country"] = "United Kingdom"
            r["academic_year"] = "2021/22"
            r["student_count"] = "500"
        results = [validate_record(r, i) for i, r in enumerate(rows)]
        detect_duplicates(results)
        self.assertFalse(results[0].is_duplicate)
        self.assertTrue(results[1].is_duplicate)

    def test_duplicate_ignores_student_count_differences(self):
        """Same dimensions, different count -- still flagged as a duplicate
        of dimensional identity, since the concern is 'this combination was
        already reported', not exact value matching."""
        rows = [
            {f: None for f in CANONICAL_FIELDS},
            {f: None for f in CANONICAL_FIELDS},
        ]
        rows[0]["destination_country"] = "United Kingdom"
        rows[0]["student_count"] = "500"
        rows[1]["destination_country"] = "United Kingdom"
        rows[1]["student_count"] = "999"
        results = [validate_record(r, i) for i, r in enumerate(rows)]
        detect_duplicates(results)
        self.assertTrue(results[1].is_duplicate)

    def test_country_alias_counts_as_same_key(self):
        """'UK' and 'United Kingdom' should dedupe together since
        normalization runs inside the dedupe key."""
        rows = [
            {f: None for f in CANONICAL_FIELDS},
            {f: None for f in CANONICAL_FIELDS},
        ]
        rows[0]["destination_country"] = "United Kingdom"
        rows[0]["student_count"] = "500"
        rows[1]["destination_country"] = "UK"
        rows[1]["student_count"] = "500"
        results = [validate_record(r, i) for i, r in enumerate(rows)]
        detect_duplicates(results)
        self.assertTrue(results[1].is_duplicate)

    def test_different_academic_year_not_a_duplicate(self):
        rows = [
            {f: None for f in CANONICAL_FIELDS},
            {f: None for f in CANONICAL_FIELDS},
        ]
        rows[0]["destination_country"] = "United Kingdom"
        rows[0]["academic_year"] = "2020/21"
        rows[0]["student_count"] = "500"
        rows[1]["destination_country"] = "United Kingdom"
        rows[1]["academic_year"] = "2021/22"
        rows[1]["student_count"] = "500"
        results = [validate_record(r, i) for i, r in enumerate(rows)]
        detect_duplicates(results)
        self.assertFalse(results[1].is_duplicate)


class TestRealFixtureEndToEnd(unittest.TestCase):
    """Runs the full pipeline against the real, already-verified HESA figures."""

    def test_all_four_real_records_are_valid(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        self.assertEqual(report["summary"].total_records, 4)
        self.assertEqual(report["summary"].valid_records, 4)
        self.assertEqual(report["summary"].records_with_errors, 0)
        self.assertEqual(report["summary"].duplicate_records, 0)

    def test_mapping_auto_suggested_correctly(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        self.assertEqual(report["mapping_used"]["destination_country"], "country")
        self.assertEqual(report["mapping_used"]["student_count"], "student_count")
        self.assertEqual(report["mapping_used"]["academic_year"], "academic_year")

    def test_values_match_seed_data_exactly(self):
        report = run_pipeline(read_fixture("hesa_uk_real_figures.csv"))
        counts = [r.mapped["student_count"] for r in report["results"]]
        self.assertEqual(counts, ["10810", "13020", "21305", "44195"])


class TestExternalDfeDataset(unittest.TestCase):
    """
    Regression test locking in the real external-dataset validation run
    against DfE's official 'Higher Education Students' dataset (see
    tests/fixtures/external_dfe_he_students/SOURCE.md for full provenance).
    This is genuinely external, official government data -- not created
    or seeded for this project -- used here to confirm the pipeline keeps
    behaving correctly against it as the codebase evolves.
    """

    def _run(self):
        content = read_fixture("external_dfe_he_students/source_extract.csv")
        headers, _ = parse_csv_bytes(content)
        mapping = suggest_column_mapping(headers)
        return run_pipeline(content, column_mapping=mapping)

    def test_auto_mapping_finds_the_real_columns(self):
        report = self._run()
        # mapping_used isn't returned by run_pipeline directly here since we
        # pass a pre-suggested mapping in; re-derive it the same way.
        headers, _ = parse_csv_bytes(read_fixture("external_dfe_he_students/source_extract.csv"))
        mapping = suggest_column_mapping(headers)
        self.assertEqual(mapping["destination_country"], "country_name")
        self.assertEqual(mapping["student_count"], "t_students")
        self.assertEqual(mapping["discipline"], "subject")
        self.assertEqual(mapping["degree_level"], "level")
        self.assertEqual(mapping["academic_year"], "time_period")
        self.assertEqual(mapping["gender"], "gender")
        # Fields this dataset genuinely doesn't provide -- must stay unmapped.
        self.assertIsNone(mapping["nigerian_state"])
        self.assertIsNone(mapping["institution"])
        self.assertIsNone(mapping["funding_type"])
        self.assertIsNone(mapping["institution_type"])

    def test_all_five_rows_parse_with_no_hard_errors(self):
        report = self._run()
        self.assertEqual(report["summary"].total_records, 5)
        self.assertEqual(report["summary"].records_with_errors, 0)

    def test_concatenated_year_format_is_accepted_and_flagged_informational(self):
        report = self._run()
        for r in report["results"]:
            self.assertEqual(r.mapped["academic_year"], "202223")
            self.assertTrue(any(i.rule == "concatenated_year_format" for i in r.issues))

    def test_known_limitation_mode_of_study_not_modeled_causes_duplicate_flag(self):
        """
        Documents a real, known limitation found via this external dataset:
        row 0 (Full-time, First degree) and row 4 (Part-time, First degree)
        are genuinely different records in the source, but our schema
        doesn't capture mode_of_study, so they collapse to the same
        dimensional key and row 4 is flagged a duplicate. This is not a bug
        in the duplicate-detection logic -- it's correctly finding that two
        records are identical *in every dimension we currently track*. The
        fix would be adding mode_of_study as a modeled dimension, which is
        deliberately NOT done in this phase pending approval.
        """
        report = self._run()
        self.assertFalse(report["results"][0].is_duplicate)
        self.assertTrue(report["results"][4].is_duplicate)

    def test_student_counts_match_official_values_exactly(self):
        report = self._run()
        counts = [r.mapped["student_count"] for r in report["results"]]
        self.assertEqual(counts, ["6595", "1710", "1830", "285", "340"])


class TestSyntheticFixtureCatchesEveryRule(unittest.TestCase):
    """
    Confirms the synthetic (clearly-labeled fabricated) fixture actually
    exercises every validation rule it was designed to test. This fixture
    is never treated as real data anywhere else in the codebase.
    """

    def test_summary_counts_match_expected_shape(self):
        report = run_pipeline(read_fixture("SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv"))
        s = report["summary"]
        self.assertEqual(s.total_records, 5)
        self.assertEqual(s.duplicate_records, 1)   # row 2 duplicates row 1
        self.assertGreaterEqual(s.records_with_errors, 2)  # negative count, bad year (Narnia row has 2 errors itself)

    def test_row2_flagged_as_duplicate_of_row1(self):
        report = run_pipeline(read_fixture("SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv"))
        self.assertFalse(report["results"][0].is_duplicate)
        self.assertTrue(report["results"][1].is_duplicate)

    def test_negative_count_row_is_error(self):
        report = run_pipeline(read_fixture("SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv"))
        self.assertEqual(report["results"][2].status, "error")

    def test_bad_year_row_is_error(self):
        report = run_pipeline(read_fixture("SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv"))
        self.assertEqual(report["results"][3].status, "error")

    def test_unparseable_count_row_is_error(self):
        report = run_pipeline(read_fixture("SYNTHETIC_DO_NOT_TREAT_AS_REAL.csv"))
        self.assertEqual(report["results"][4].status, "error")


if __name__ == "__main__":
    unittest.main()
