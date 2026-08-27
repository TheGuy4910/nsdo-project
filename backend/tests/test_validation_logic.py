"""
Unit tests for app/services/validation.py.

These run for real, right now, in this sandbox: validation.py imports
nothing beyond the Python standard library, so unlike the FastAPI/SQLAlchemy
layers, this logic is fully executable and testable without installing
anything.

Run with: python3 -m unittest backend/tests/test_validation_logic.py -v
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.validation import (
    validate_limitations,
    validate_reference_period,
    validate_short_code,
    can_delete_dataset,
    can_delete_source,
    IMMUTABLE_DATASET_FIELDS,
)


class TestValidateLimitations(unittest.TestCase):
    def test_rejects_empty_string(self):
        with self.assertRaises(ValueError):
            validate_limitations("")

    def test_rejects_whitespace_only(self):
        with self.assertRaises(ValueError):
            validate_limitations("   \n\t  ")

    def test_rejects_none(self):
        with self.assertRaises(ValueError):
            validate_limitations(None)

    def test_accepts_real_text_and_strips_it(self):
        result = validate_limitations("  Pre-dates the 2023 naira devaluation.  ")
        self.assertEqual(result, "Pre-dates the 2023 naira devaluation.")


class TestValidateReferencePeriod(unittest.TestCase):
    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_reference_period("")

    def test_accepts_academic_year_format(self):
        self.assertEqual(validate_reference_period("2021/22"), "2021/22")

    def test_accepts_calendar_year_format(self):
        self.assertEqual(validate_reference_period("2018"), "2018")


class TestValidateShortCode(unittest.TestCase):
    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_short_code("")

    def test_rejects_spaces(self):
        with self.assertRaises(ValueError):
            validate_short_code("HESA UK")

    def test_uppercases_and_strips(self):
        self.assertEqual(validate_short_code("  hesa  "), "HESA")


class TestCanDeleteDataset(unittest.TestCase):
    def test_verified_dataset_cannot_be_deleted(self):
        ok, msg = can_delete_dataset(status="verified", observation_count=0)
        self.assertFalse(ok)
        self.assertIn("deprecated", msg)

    def test_dataset_with_observations_cannot_be_deleted(self):
        ok, msg = can_delete_dataset(status="draft", observation_count=5)
        self.assertFalse(ok)
        self.assertIn("5 observation", msg)

    def test_empty_draft_can_be_deleted(self):
        ok, msg = can_delete_dataset(status="draft", observation_count=0)
        self.assertTrue(ok)

    def test_empty_validated_can_be_deleted(self):
        ok, msg = can_delete_dataset(status="validated", observation_count=0)
        self.assertTrue(ok)

    def test_verified_with_observations_still_blocked_by_verified_rule(self):
        ok, msg = can_delete_dataset(status="verified", observation_count=10)
        self.assertFalse(ok)
        self.assertIn("Verified datasets cannot be deleted", msg)


class TestCanDeleteSource(unittest.TestCase):
    def test_referenced_source_cannot_be_deleted(self):
        ok, msg = can_delete_source(referencing_dataset_count=3)
        self.assertFalse(ok)
        self.assertIn("3 dataset", msg)

    def test_unreferenced_source_can_be_deleted(self):
        ok, msg = can_delete_source(referencing_dataset_count=0)
        self.assertTrue(ok)


class TestImmutableFields(unittest.TestCase):
    def test_identity_fields_are_flagged_immutable(self):
        expected = {"source_id", "metric_definition_id", "destination_country", "reference_period"}
        self.assertEqual(IMMUTABLE_DATASET_FIELDS, expected)

    def test_title_and_status_are_not_in_immutable_set(self):
        self.assertNotIn("title", IMMUTABLE_DATASET_FIELDS)
        self.assertNotIn("status", IMMUTABLE_DATASET_FIELDS)


if __name__ == "__main__":
    unittest.main()
