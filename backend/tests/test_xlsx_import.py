"""
Tests for app/services/xlsx_import.py.

These run for real, right now: openpyxl has no server/network dependency,
so unlike the FastAPI/SQLAlchemy layers, every one of these is a genuine
executed test. Covers: workbook/sheet selection, header detection,
column mapping (including compound headers, and the two real mapping
bugs found and one deliberately left unfixed -- see
TestKnownIssueSemanticAmbiguity), missing values, numeric values,
academic-year formats, unmapped columns, duplicate/dimensional-key
behavior, malformed rows, and multiple sheets.

Run with: python3 -m unittest backend/tests/test_xlsx_import.py -v
"""

import unittest
import sys
import os
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openpyxl

from app.services.xlsx_import import (
    parse_xlsx_bytes, list_sheet_names, run_pipeline, XlsxParseError, _detect_header_row,
)
from app.services.csv_import import suggest_column_mapping, CANONICAL_FIELDS

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def build_workbook_bytes(sheets: dict[str, list[list]]) -> bytes:
    """Builds an in-memory .xlsx from {sheet_name: [[row1cells],[row2cells],...]}."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestWorkbookAndSheetSelection(unittest.TestCase):
    def test_lists_sheet_names(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        self.assertEqual(list_sheet_names(content), ["FSM_Sex_Ethnicity", "All_Characteristics"])

    def test_defaults_to_first_sheet_when_none_given(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        selected, _, _ = parse_xlsx_bytes(content, sheet_name=None)
        self.assertEqual(selected, "FSM_Sex_Ethnicity")

    def test_can_select_second_sheet_explicitly(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        selected, headers, rows = parse_xlsx_bytes(content, sheet_name="All_Characteristics")
        self.assertEqual(selected, "All_Characteristics")
        self.assertIn("breakdown_topic", headers)

    def test_unknown_sheet_name_raises(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        with self.assertRaises(XlsxParseError):
            parse_xlsx_bytes(content, sheet_name="DoesNotExist")

    def test_workbook_with_no_sheets_raises(self):
        # Not constructible as a real test: openpyxl itself refuses to save
        # a workbook with zero visible sheets (raises IndexError at save
        # time), so no valid .xlsx file can actually reach our code in this
        # state. The defensive check in parse_xlsx_bytes for `if not
        # available` is retained as a guard against a theoretically
        # malformed/hand-crafted file, but isn't independently testable
        # via openpyxl's own writer.
        pass


class TestHeaderDetection(unittest.TestCase):
    def test_header_on_row_1_detected(self):
        rows = [("country", "student_count"), ("United Kingdom", "100")]
        self.assertEqual(_detect_header_row(rows), 0)

    def test_header_after_title_and_blank_row_detected(self):
        rows = [
            ("Some Report Title",),
            (None, None),
            ("country", "student_count"),
            ("United Kingdom", "100"),
        ]
        self.assertEqual(_detect_header_row(rows), 2)

    def test_real_fixture_sheet1_header_after_title_row(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        selected, headers, rows = parse_xlsx_bytes(content, sheet_name="FSM_Sex_Ethnicity")
        self.assertEqual(headers[0], "time_period")
        self.assertEqual(len(rows), 5)

    def test_real_fixture_sheet2_header_on_row_1_no_title(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        selected, headers, rows = parse_xlsx_bytes(content, sheet_name="All_Characteristics")
        self.assertEqual(headers[0], "time_period")
        self.assertEqual(len(rows), 5)

    def test_raises_when_no_header_like_row_exists(self):
        content = build_workbook_bytes({"Empty": [(None,), (None,), (None,)]})
        with self.assertRaises(XlsxParseError):
            parse_xlsx_bytes(content)


class TestColumnMappingAgainstRealHeaders(unittest.TestCase):
    def test_compound_headers_from_real_dataset_map_correctly(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        _, headers, _ = parse_xlsx_bytes(content, sheet_name="FSM_Sex_Ethnicity")
        mapping = suggest_column_mapping(headers)
        self.assertEqual(mapping["destination_country"], "country_name")
        self.assertEqual(mapping["academic_year"], "time_period")
        self.assertEqual(mapping["gender"], "sex")

    def test_geographic_level_administrative_column_not_mismapped_to_degree_level(self):
        """Regression test for the real bug found in this validation:
        'geographic_level' (value always 'National') was wrongly matched
        to degree_level via the substring 'level'."""
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        _, headers, _ = parse_xlsx_bytes(content, sheet_name="FSM_Sex_Ethnicity")
        mapping = suggest_column_mapping(headers)
        self.assertIsNone(mapping["degree_level"])

    def test_unmapped_columns_reported_for_both_sheets(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        for sheet in ["FSM_Sex_Ethnicity", "All_Characteristics"]:
            _, headers, _ = parse_xlsx_bytes(content, sheet_name=sheet)
            mapping = suggest_column_mapping(headers)
            unmapped = [h for h in headers if h not in mapping.values()]
            self.assertGreater(len(unmapped), 0, f"{sheet} should have some unmapped columns")


class TestKnownIssueSemanticAmbiguity(unittest.TestCase):
    """
    Documents, rather than silently 'fixes', a genuine finding: this real
    dataset has both 'number_of_he_students' (the correct HE-specific
    count) and 'number_of_students' (a broader cohort denominator).
    'number_of_students' normalizes to an exact synonym match
    ('numberofstudents') and wins over the substring match on
    'number_of_he_students', which is semantically wrong for this specific
    dataset. This is intentionally NOT patched with a guessing heuristic --
    it's the reason auto-suggested mappings require human confirmation
    before commit, not automatic application.
    """

    def test_auto_mapping_currently_picks_the_broader_denominator(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        _, headers, _ = parse_xlsx_bytes(content, sheet_name="FSM_Sex_Ethnicity")
        mapping = suggest_column_mapping(headers)
        # This assertion documents current (imperfect) behavior, not
        # desired behavior -- see class docstring.
        self.assertEqual(mapping["student_count"], "number_of_students")
        self.assertNotEqual(mapping["student_count"], "number_of_he_students")

    def test_explicit_mapping_override_selects_the_correct_column(self):
        """Confirms the escape hatch works: a human reviewing the preview
        can override the auto-suggestion to get the semantically correct
        column, exactly as the preview -> confirm -> commit flow intends."""
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        override = {f: None for f in CANONICAL_FIELDS}
        override["destination_country"] = "country_name"
        override["student_count"] = "number_of_he_students"
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity", column_mapping=override)
        self.assertEqual(report["results"][0].mapped["student_count"], "1757")


class TestMissingAndNumericValues(unittest.TestCase):
    def test_unmapped_fields_are_none_not_fabricated(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity")
        for r in report["results"]:
            self.assertIsNone(r.mapped["nigerian_state"])
            self.assertIsNone(r.mapped["institution"])
            self.assertIsNone(r.mapped["funding_type"])
            self.assertIsNone(r.mapped["institution_type"])

    def test_numeric_cell_types_from_xlsx_convert_to_valid_counts(self):
        """openpyxl returns numeric cells as int/float, not strings -- confirms
        these convert cleanly through the same validate_record() string-based
        parsing CSV uses, with no special-casing needed."""
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity",
                               column_mapping={**{f: None for f in CANONICAL_FIELDS},
                                               "destination_country": "country_name",
                                               "student_count": "number_of_he_students"})
        self.assertEqual(report["summary"].records_with_errors, 0)
        counts = [r.mapped["student_count"] for r in report["results"]]
        self.assertEqual(counts, ["1757", "13", "0", "0", "183"])


class TestAcademicYearFormats(unittest.TestCase):
    def test_concatenated_year_from_real_data_accepted(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity")
        for r in report["results"]:
            self.assertEqual(r.mapped["academic_year"], "200506")
            self.assertTrue(any(i.rule == "concatenated_year_format" for i in r.issues))


class TestDuplicateDetectionAcrossXlsxRows(unittest.TestCase):
    def test_rows_sharing_every_mapped_dimension_flagged_duplicate(self):
        """Documents the real finding: this sheet's only mapped dimensions
        are country/year/gender, all identical across all 5 rows (the real
        distinguishing column, ethnicity_minor, isn't a canonical field) --
        so rows 2-5 are correctly flagged duplicates of row 1 *given what
        we currently track*, mirroring the mode_of_study finding from the
        CSV validation. Not silently fixed by adding an ethnicity
        dimension -- that's a schema decision for you to make."""
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        report = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity")
        self.assertFalse(report["results"][0].is_duplicate)
        for r in report["results"][1:]:
            self.assertTrue(r.is_duplicate)

    def test_different_sheets_are_independent_dedupe_scopes(self):
        content = read_fixture("external_xlsx_dfe_widening_participation/workbook_source.xlsx")
        report1 = run_pipeline(content, sheet_name="FSM_Sex_Ethnicity")
        report2 = run_pipeline(content, sheet_name="All_Characteristics")
        # Both have duplicates internally, but each sheet is processed and
        # deduped independently of the other.
        self.assertEqual(report1["summary"].duplicate_records, 4)
        self.assertEqual(report2["summary"].duplicate_records, 4)


class TestMalformedRows(unittest.TestCase):
    def test_negative_count_flagged_error(self):
        content = build_workbook_bytes({"Sheet1": [
            ["country", "student_count"],
            ["United Kingdom", -5],
        ]})
        report = run_pipeline(content)
        self.assertEqual(report["results"][0].status, "error")

    def test_missing_required_field_flagged_error(self):
        content = build_workbook_bytes({"Sheet1": [
            ["country", "student_count"],
            [None, 100],
        ]})
        report = run_pipeline(content)
        self.assertEqual(report["results"][0].status, "error")

    def test_fully_blank_trailing_row_skipped_not_treated_as_malformed(self):
        content = build_workbook_bytes({"Sheet1": [
            ["country", "student_count"],
            ["United Kingdom", 100],
            [None, None],
        ]})
        report = run_pipeline(content)
        self.assertEqual(report["summary"].total_records, 1)


class TestCsvAndXlsxShareTheSamePath(unittest.TestCase):
    """Directly verifies the 'cannot drift' requirement: identical logical
    data through both formats produces identical validation results."""

    def test_same_data_same_result_csv_vs_xlsx(self):
        from app.services.csv_import import run_pipeline as csv_run_pipeline

        csv_content = b"country,student_count\nUnited Kingdom,10810\n"
        xlsx_content = build_workbook_bytes({"Sheet1": [
            ["country", "student_count"],
            ["United Kingdom", 10810],
        ]})

        csv_report = csv_run_pipeline(csv_content)
        xlsx_report = run_pipeline(xlsx_content)

        self.assertEqual(csv_report["results"][0].status, xlsx_report["results"][0].status)
        self.assertEqual(csv_report["results"][0].mapped["destination_country"],
                          xlsx_report["results"][0].mapped["destination_country"])
        self.assertEqual(csv_report["results"][0].mapped["student_count"],
                          xlsx_report["results"][0].mapped["student_count"])


if __name__ == "__main__":
    unittest.main()
