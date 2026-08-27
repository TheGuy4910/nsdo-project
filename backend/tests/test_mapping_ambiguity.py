"""
Tests for the mapping ambiguity detection system (Phase 3B change 1).

Covers: detection function, the real-world case that motivated this change
(number_of_students vs number_of_he_students), required vs optional field
behavior, process_rows output, and the commit-block enforcement.

All tests run for real -- no FastAPI/SQLAlchemy dependency, pure stdlib.

Run with: python3 -m unittest backend/tests/test_mapping_ambiguity.py -v
"""

import unittest
import sys
import os
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.csv_import import (
    detect_mapping_ambiguities, has_unresolved_required_ambiguities,
    process_rows, parse_csv_bytes, suggest_column_mapping,
    REQUIRED_FIELDS, CANONICAL_FIELDS,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


class TestDetectMappingAmbiguities(unittest.TestCase):

    def test_no_ambiguity_when_each_header_matches_only_one_canonical_field(self):
        headers = ["country", "academic_year", "student_count"]
        result = detect_mapping_ambiguities(headers)
        self.assertEqual(result, [])

    def test_real_world_case_number_of_students_vs_number_of_he_students(self):
        """This is the exact real-world case that motivated this entire change:
        both 'number_of_students' and 'number_of_he_students' match
        student_count (the required field), and the old code silently picked
        one. Now it must produce an unambiguous, structured ambiguity report."""
        headers = [
            "country_name", "time_period", "gender", "level",
            "number_of_he_students", "number_of_high_tariff_he_students",
            "number_of_students",
        ]
        ambiguities = detect_mapping_ambiguities(headers)
        student_count_ambs = [a for a in ambiguities if a.canonical_field == "student_count"]
        self.assertEqual(len(student_count_ambs), 1)
        amb = student_count_ambs[0]
        self.assertTrue(amb.required)
        self.assertTrue(amb.resolution_required)
        candidate_columns = {c.column for c in amb.candidates}
        self.assertIn("number_of_students", candidate_columns)
        self.assertIn("number_of_he_students", candidate_columns)

    def test_ambiguity_includes_match_type_for_each_candidate(self):
        # 'students' is an exact synonym for student_count
        # 'number_of_students' would be a substring match
        # Both present -> ambiguity with distinct match_types
        headers = ["country", "students", "number_of_students"]
        ambiguities = detect_mapping_ambiguities(headers)
        sc_ambs = [a for a in ambiguities if a.canonical_field == "student_count"]
        self.assertEqual(len(sc_ambs), 1)
        types = {c.match_type for c in sc_ambs[0].candidates}
        self.assertIn("exact_synonym", types)

    def test_optional_field_ambiguity_resolution_not_required(self):
        # institution is optional (not in REQUIRED_FIELDS). Two columns
        # both match it -> ambiguity reported, but resolution_required=False.
        headers = ["country", "student_count", "institution", "university"]
        ambiguities = detect_mapping_ambiguities(headers)
        inst_ambs = [a for a in ambiguities if a.canonical_field == "institution"]
        self.assertEqual(len(inst_ambs), 1)
        self.assertFalse(inst_ambs[0].required)
        self.assertFalse(inst_ambs[0].resolution_required)

    def test_required_field_ambiguity_resolution_required_true(self):
        self.assertIn("student_count", REQUIRED_FIELDS)
        headers = ["country", "students", "number_of_students"]
        ambiguities = detect_mapping_ambiguities(headers)
        sc_ambs = [a for a in ambiguities if a.canonical_field == "student_count"]
        self.assertTrue(sc_ambs[0].resolution_required)

    def test_ambiguity_reason_includes_all_candidate_names(self):
        headers = ["country", "students", "number_of_students"]
        ambiguities = detect_mapping_ambiguities(headers)
        sc = [a for a in ambiguities if a.canonical_field == "student_count"][0]
        self.assertIn("students", sc.reason)
        self.assertIn("number_of_students", sc.reason)


class TestHasUnresolvedRequiredAmbiguities(unittest.TestCase):

    def _ambiguous_headers(self):
        return [
            "country_name", "time_period",
            "number_of_he_students", "number_of_students",
        ]

    def test_unresolved_when_mapping_has_none_for_ambiguous_required_field(self):
        headers = self._ambiguous_headers()
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country_name"
        # student_count left as None
        unresolved = has_unresolved_required_ambiguities(headers, mapping)
        sc_unresolved = [a for a in unresolved if a.canonical_field == "student_count"]
        self.assertEqual(len(sc_unresolved), 1)

    def test_resolved_when_mapping_explicitly_picks_one(self):
        headers = self._ambiguous_headers()
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country_name"
        mapping["student_count"] = "number_of_he_students"  # explicit choice
        unresolved = has_unresolved_required_ambiguities(headers, mapping)
        sc_unresolved = [a for a in unresolved if a.canonical_field == "student_count"]
        self.assertEqual(len(sc_unresolved), 0)

    def test_no_ambiguity_headers_always_produce_empty_unresolved_list(self):
        headers = ["country", "student_count", "academic_year"]
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country"
        mapping["student_count"] = "student_count"
        self.assertEqual(has_unresolved_required_ambiguities(headers, mapping), [])


class TestProcessRowsAmbiguityOutput(unittest.TestCase):

    def test_ambiguous_dataset_returns_ambiguities_in_output(self):
        csv = b"country_name,number_of_he_students,number_of_students\nEngland,1757,25794\n"
        headers, raw_rows = parse_csv_bytes(csv)
        report = process_rows(headers, raw_rows)
        sc_ambs = [a for a in report["ambiguities"] if a.canonical_field == "student_count"]
        self.assertEqual(len(sc_ambs), 1)

    def test_unambiguous_dataset_has_empty_ambiguity_lists(self):
        csv = b"country,student_count\nUnited Kingdom,10810\n"
        headers, raw_rows = parse_csv_bytes(csv)
        report = process_rows(headers, raw_rows)
        self.assertEqual(report["ambiguities"], [])
        self.assertEqual(report["unresolved_required_ambiguities"], [])

    def test_unresolved_required_ambiguity_present_when_auto_suggested(self):
        """When no mapping is given and headers are ambiguous, the auto-suggested
        mapping will have None for the conflicted required field, so
        unresolved_required_ambiguities should be non-empty."""
        csv = b"country_name,number_of_he_students,number_of_students\nEngland,1757,25794\n"
        headers, raw_rows = parse_csv_bytes(csv)
        report = process_rows(headers, raw_rows)
        unresolved_fields = {a.canonical_field for a in report["unresolved_required_ambiguities"]}
        self.assertIn("student_count", unresolved_fields)

    def test_resolved_mapping_removes_field_from_unresolved_list(self):
        csv = b"country_name,number_of_he_students,number_of_students\nEngland,1757,25794\n"
        headers, raw_rows = parse_csv_bytes(csv)
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country_name"
        mapping["student_count"] = "number_of_he_students"
        report = process_rows(headers, raw_rows, column_mapping=mapping)
        unresolved_fields = {a.canonical_field for a in report["unresolved_required_ambiguities"]}
        self.assertNotIn("student_count", unresolved_fields)

    def test_data_still_processes_with_unresolved_ambiguity(self):
        """The pipeline still runs and produces results even with unresolved
        ambiguity -- so the preview can show the human what the rows would
        look like. Only the commit is blocked, not the preview itself."""
        csv = b"country_name,number_of_he_students,number_of_students\nEngland,1757,25794\n"
        headers, raw_rows = parse_csv_bytes(csv)
        report = process_rows(headers, raw_rows)
        self.assertEqual(len(report["results"]), 1)
        self.assertGreater(len(report["unresolved_required_ambiguities"]), 0)


class TestRealExternalDatasetAmbiguityBehavior(unittest.TestCase):
    """Integration: runs the real external XLSX dataset through the improved
    pipeline and confirms the ambiguity is correctly reported and structured."""

    def test_widening_participation_sheet_produces_ambiguity_for_student_count(self):
        from app.services.xlsx_import import run_pipeline
        with open(os.path.join(FIXTURES,
                "external_xlsx_dfe_widening_participation/workbook_source.xlsx"), "rb") as f:
            content = f.read()
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity")
        sc_ambs = [a for a in report["ambiguities"] if a.canonical_field == "student_count"]
        self.assertEqual(len(sc_ambs), 1)
        candidates = {c.column for c in sc_ambs[0].candidates}
        self.assertIn("number_of_students", candidates)
        self.assertIn("number_of_he_students", candidates)

    def test_unresolved_required_ambiguity_blocks_implied_commit(self):
        from app.services.xlsx_import import run_pipeline
        with open(os.path.join(FIXTURES,
                "external_xlsx_dfe_widening_participation/workbook_source.xlsx"), "rb") as f:
            content = f.read()
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity")
        unresolved_fields = {a.canonical_field for a in report["unresolved_required_ambiguities"]}
        self.assertIn("student_count", unresolved_fields)

    def test_explicit_override_to_number_of_he_students_resolves_ambiguity(self):
        from app.services.xlsx_import import run_pipeline
        with open(os.path.join(FIXTURES,
                "external_xlsx_dfe_widening_participation/workbook_source.xlsx"), "rb") as f:
            content = f.read()
        mapping = {f: None for f in CANONICAL_FIELDS}
        mapping["destination_country"] = "country_name"
        mapping["student_count"] = "number_of_he_students"
        mapping["academic_year"] = "time_period"
        mapping["gender"] = "sex"
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity", column_mapping=mapping)
        self.assertEqual(report["unresolved_required_ambiguities"], [])
        # And the counts now reflect the HE-specific column, not the pupil denominator
        self.assertEqual(report["results"][0].mapped["student_count"], "1757")


if __name__ == "__main__":
    unittest.main()
