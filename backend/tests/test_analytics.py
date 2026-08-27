"""
Tests for the analytics service (app/services/analytics.py).

All tests are pure-Python — no FastAPI, no SQLAlchemy, no database.
Follows the established project pattern (see test_validation_logic.py).

Rounding convention (approved in Phase 5):
  percent_change is rounded with Python's built-in round() (round-half-even)
  to the decimal_places argument (default 2).
  10810 → 13020: (13020-10810)/10810*100 = 20.4384...%  → 20.44
  13020 → 21305: (21305-13020)/13020*100 = 63.6328...%  → 63.63
  21305 → 44195: (44195-21305)/21305*100 = 107.4396...% → 107.44
"""

import sys
import os
import unittest

# Make app/ importable from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analytics import (
    assess_comparability,
    assess_multi_series_comparability,
    build_trend_series,
    build_snapshot,
    build_growth_series,
    characteristic_profile,
    sort_key_for_period,
    ComparabilityVerdict,
    GLOBAL_AGGREGATE_COUNTRY,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal dicts matching the analytics input shape
# ---------------------------------------------------------------------------

def _ds(
    dataset_id=1,
    country="United Kingdom",
    period="2021/22",
    metric_code="hesa_enrolled_headcount",
    metric_def_id=1,
    reliability_tier="official_primary",
    source_short_code="HESA",
    status="verified",
    limitations="Test limitations.",
    observations=None,
    obs=None,   # alias so call-sites can use obs= as shorthand
):
    if obs is not None:
        observations = obs
    if observations is None:
        observations = [{"value": 44195.0, "characteristics": []}]
    return {
        "dataset_id": dataset_id,
        "destination_country": country,
        "reference_period": period,
        "metric_code": metric_code,
        "metric_definition_id": metric_def_id,
        "reliability_tier": reliability_tier,
        "source_short_code": source_short_code,
        "source_name": source_short_code,
        "status": status,
        "limitations": limitations,
        "observations": observations,
    }


HESA_SERIES = [
    _ds(1, "United Kingdom", "2018/19", obs=[{"value": 10810.0, "characteristics": []}]),
    _ds(2, "United Kingdom", "2019/20", obs=[{"value": 13020.0, "characteristics": []}]),
    _ds(3, "United Kingdom", "2020/21", obs=[{"value": 21305.0, "characteristics": []}]),
    _ds(4, "United Kingdom", "2021/22", obs=[{"value": 44195.0, "characteristics": []}]),
]

US_SERIES = [
    _ds(5, "United States", "2021/22", "sevis_enrolled_headcount", 2, "official_secondary", "IIE_OPENDOORS",
        obs=[{"value": 14438.0, "characteristics": []}]),
    _ds(6, "United States", "2022/23", "sevis_enrolled_headcount", 2, "official_secondary", "IIE_OPENDOORS",
        obs=[{"value": 17640.0, "characteristics": []}]),
    _ds(7, "United States", "2023/24", "sevis_enrolled_headcount", 2, "official_secondary", "IIE_OPENDOORS",
        obs=[{"value": 20029.0, "characteristics": []}]),
]

CANADA_DS = _ds(8, "Canada", "2021/22", "press_reported_enrollment", 3, "credible_secondary", "PRESS_IRCC",
                obs=[{"value": 13745.0, "characteristics": []}])

MALAYSIA_DS = _ds(9, "Malaysia", "~2026 (undated estimate)", "unverified_market_estimate", 4,
                  "unverified", "AGGREGATOR_SCHOOLREG",
                  obs=[{"value": 10000.0, "characteristics": []}])

UNESCO_DS = _ds(10, GLOBAL_AGGREGATE_COUNTRY, "2018", "unesco_outbound_mobility", 5,
                "official_primary", "UNESCO_UIS",
                obs=[{"value": 76338.0, "characteristics": []}])

KNOWN_GAPS = [
    "UK Nigerian enrolment for 2022/23 and 2023/24: qualitative decline documented.",
    "Germany: no verifiable count found.",
]


# ---------------------------------------------------------------------------
# Period sorting
# ---------------------------------------------------------------------------

class TestSortKeyForPeriod(unittest.TestCase):

    def test_academic_year_order(self):
        periods = ["2021/22", "2018/19", "2020/21", "2019/20"]
        sorted_p = sorted(periods, key=sort_key_for_period)
        self.assertEqual(sorted_p, ["2018/19", "2019/20", "2020/21", "2021/22"])

    def test_calendar_year_sorts_correctly(self):
        key = sort_key_for_period("2018")
        self.assertEqual(key, (2018, 0))

    def test_academic_year_tuple(self):
        self.assertEqual(sort_key_for_period("2021/22"), (2021, 22))

    def test_undated_estimate_sorts_last_within_year(self):
        k1 = sort_key_for_period("~2026 (undated estimate)")
        k2 = sort_key_for_period("2026/27")
        self.assertGreater(k1, k2)

    def test_mixed_academic_and_calendar(self):
        periods = ["2021/22", "2018", "2020/21"]
        sorted_p = sorted(periods, key=sort_key_for_period)
        self.assertEqual(sorted_p[0], "2018")


# ---------------------------------------------------------------------------
# Characteristic profile
# ---------------------------------------------------------------------------

class TestCharacteristicProfile(unittest.TestCase):

    def test_empty_list_is_bare_total(self):
        result = characteristic_profile([])
        self.assertEqual(result, frozenset())

    def test_single_dimension(self):
        result = characteristic_profile([{"dimension": "mode_of_study", "value": "full_time"}])
        self.assertEqual(result, frozenset({"mode_of_study"}))

    def test_multiple_dimensions(self):
        chars = [
            {"dimension": "mode_of_study", "value": "full_time"},
            {"dimension": "ethnicity",      "value": "Black"},
        ]
        result = characteristic_profile(chars)
        self.assertEqual(result, frozenset({"mode_of_study", "ethnicity"}))

    def test_profile_ignores_value_content(self):
        """Two observations with same dimension but different values have the same profile."""
        a = characteristic_profile([{"dimension": "gender", "value": "Male"}])
        b = characteristic_profile([{"dimension": "gender", "value": "Female"}])
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# ComparabilityVerdict
# ---------------------------------------------------------------------------

class TestAssessComparability(unittest.TestCase):

    def _assess(self, code_a, code_b, tier_a="official_primary", tier_b="official_primary",
                profile_a=frozenset(), profile_b=frozenset()):
        return assess_comparability(code_a, code_b, tier_a, tier_b, profile_a, profile_b)

    def test_same_metric_same_profile_is_comparable(self):
        r = self._assess("hesa_enrolled_headcount", "hesa_enrolled_headcount")
        self.assertEqual(r["verdict"], ComparabilityVerdict.COMPARABLE)

    def test_different_headcount_metrics_is_methodology_differs(self):
        r = self._assess("hesa_enrolled_headcount", "sevis_enrolled_headcount",
                         "official_primary", "official_secondary")
        self.assertEqual(r["verdict"], ComparabilityVerdict.METHODOLOGY_DIFFERS)
        self.assertIn("hesa_enrolled_headcount", r["reason"])
        self.assertIn("sevis_enrolled_headcount", r["reason"])

    def test_unverified_source_is_incomparable(self):
        r = self._assess("hesa_enrolled_headcount", "unverified_market_estimate",
                         "official_primary", "unverified")
        self.assertEqual(r["verdict"], ComparabilityVerdict.INCOMPARABLE)

    def test_unverified_tier_b_is_incomparable_regardless_of_metric(self):
        r = self._assess("hesa_enrolled_headcount", "hesa_enrolled_headcount",
                         "official_primary", "unverified")
        self.assertEqual(r["verdict"], ComparabilityVerdict.INCOMPARABLE)

    def test_global_aggregate_metric_is_incomparable(self):
        r = self._assess("hesa_enrolled_headcount", "unesco_outbound_mobility")
        self.assertEqual(r["verdict"], ComparabilityVerdict.INCOMPARABLE)

    def test_unverified_estimate_metric_is_incomparable(self):
        r = self._assess("sevis_enrolled_headcount", "unverified_market_estimate")
        self.assertEqual(r["verdict"], ComparabilityVerdict.INCOMPARABLE)

    def test_same_metric_different_char_profiles_is_methodology_differs(self):
        profile_total = frozenset()
        profile_breakdown = frozenset({"mode_of_study"})
        r = self._assess("hesa_enrolled_headcount", "hesa_enrolled_headcount",
                         profile_a=profile_total, profile_b=profile_breakdown)
        self.assertEqual(r["verdict"], ComparabilityVerdict.METHODOLOGY_DIFFERS)
        self.assertIsNotNone(r["characteristic_note"])
        self.assertIn("mode_of_study", r["characteristic_note"])

    def test_different_profile_note_describes_both_sides(self):
        profile_a = frozenset({"gender"})
        profile_b = frozenset({"mode_of_study"})
        r = self._assess("hesa_enrolled_headcount", "hesa_enrolled_headcount",
                         profile_a=profile_a, profile_b=profile_b)
        self.assertEqual(r["verdict"], ComparabilityVerdict.METHODOLOGY_DIFFERS)
        # Note must mention what is only in A and only in B
        self.assertIn("gender", r["characteristic_note"])
        self.assertIn("mode_of_study", r["characteristic_note"])

    def test_bare_total_vs_breakdown_noted_in_characteristic_note(self):
        profile_bare = frozenset()
        profile_breakdown = frozenset({"mode_of_study"})
        r = self._assess("hesa_enrolled_headcount", "hesa_enrolled_headcount",
                         profile_a=profile_bare, profile_b=profile_breakdown)
        self.assertIn("bare total", r["characteristic_note"].lower())

    def test_verdict_has_all_required_keys(self):
        r = self._assess("hesa_enrolled_headcount", "hesa_enrolled_headcount")
        self.assertIn("verdict", r)
        self.assertIn("reason", r)
        self.assertIn("characteristic_note", r)
        self.assertIsInstance(r["reason"], str)
        self.assertGreater(len(r["reason"]), 0)


# ---------------------------------------------------------------------------
# Multi-series comparability (dashboard warning)
# ---------------------------------------------------------------------------

class TestAssessMultiSeriesComparability(unittest.TestCase):

    def _series(self, metric_code, country="UK"):
        return {"country": country, "metric_code": metric_code, "metric_definition_id": 1}

    def test_single_series_is_comparable(self):
        r = assess_multi_series_comparability([self._series("hesa_enrolled_headcount")])
        self.assertTrue(r["all_comparable"])
        self.assertEqual(r["verdict"], ComparabilityVerdict.COMPARABLE)

    def test_two_series_same_metric_comparable(self):
        r = assess_multi_series_comparability([
            self._series("hesa_enrolled_headcount", "UK"),
            self._series("hesa_enrolled_headcount", "Ireland"),
        ])
        self.assertTrue(r["all_comparable"])

    def test_hesa_vs_open_doors_is_methodology_differs(self):
        r = assess_multi_series_comparability([
            self._series("hesa_enrolled_headcount"),
            self._series("sevis_enrolled_headcount"),
        ])
        self.assertFalse(r["all_comparable"])
        self.assertEqual(r["verdict"], ComparabilityVerdict.METHODOLOGY_DIFFERS)

    def test_includes_incomparable_metric_is_incomparable(self):
        r = assess_multi_series_comparability([
            self._series("hesa_enrolled_headcount"),
            self._series("unverified_market_estimate"),
        ])
        self.assertFalse(r["all_comparable"])
        self.assertEqual(r["verdict"], ComparabilityVerdict.INCOMPARABLE)

    def test_metric_codes_present_listed(self):
        r = assess_multi_series_comparability([
            self._series("hesa_enrolled_headcount"),
            self._series("sevis_enrolled_headcount"),
        ])
        self.assertIn("hesa_enrolled_headcount", r["metric_codes_present"])
        self.assertIn("sevis_enrolled_headcount", r["metric_codes_present"])

    def test_empty_series_list_returns_comparable(self):
        r = assess_multi_series_comparability([])
        self.assertTrue(r["all_comparable"])


# ---------------------------------------------------------------------------
# Trend series
# ---------------------------------------------------------------------------

class TestBuildTrendSeries(unittest.TestCase):

    def test_basic_happy_path(self):
        trend = build_trend_series("United Kingdom", HESA_SERIES, [])
        self.assertEqual(trend["country"], "United Kingdom")
        self.assertEqual(trend["metric_code"], "hesa_enrolled_headcount")
        self.assertEqual(len(trend["points"]), 4)

    def test_points_sorted_oldest_first(self):
        # Pass in reverse order
        reversed_series = list(reversed(HESA_SERIES))
        trend = build_trend_series("United Kingdom", reversed_series, [])
        periods = [p["period"] for p in trend["points"]]
        self.assertEqual(periods, ["2018/19", "2019/20", "2020/21", "2021/22"])

    def test_values_match_observations(self):
        trend = build_trend_series("United Kingdom", HESA_SERIES, [])
        values = [p["value"] for p in trend["points"]]
        self.assertEqual(values, [10810.0, 13020.0, 21305.0, 44195.0])

    def test_mixed_metric_codes_raises_valueerror(self):
        mixed = [HESA_SERIES[0], US_SERIES[0]]
        with self.assertRaises(ValueError) as ctx:
            build_trend_series("Mixed", mixed, [])
        self.assertIn("mixed metric", str(ctx.exception).lower())

    def test_empty_input_returns_no_points(self):
        trend = build_trend_series("United Kingdom", [], [])
        self.assertEqual(trend["points"], [])
        self.assertIsNotNone(trend["series_note"])

    def test_gap_is_none_not_zero(self):
        """A period with no observations must produce value=None, not 0."""
        ds_no_obs = _ds(99, "United Kingdom", "2022/23", obs=[])
        trend = build_trend_series("United Kingdom", [ds_no_obs], [])
        pt = trend["points"][0]
        self.assertIsNone(pt["value"])
        self.assertTrue(pt["is_gap"])

    def test_gap_never_interpolated(self):
        """Gap period between two real values stays None."""
        series_with_gap = [
            _ds(1, "United Kingdom", "2021/22", obs=[{"value": 44195.0, "characteristics": []}]),
            _ds(2, "United Kingdom", "2022/23", obs=[]),
            _ds(3, "United Kingdom", "2023/24", obs=[{"value": 40000.0, "characteristics": []}]),
        ]
        trend = build_trend_series("United Kingdom", series_with_gap, [])
        pts = trend["points"]
        self.assertIsNotNone(pts[0]["value"])
        self.assertIsNone(pts[1]["value"])
        self.assertIsNotNone(pts[2]["value"])

    def test_known_gap_annotated_in_gap_note(self):
        ds_no_obs = _ds(99, "United Kingdom", "2022/23", obs=[])
        trend = build_trend_series("United Kingdom", [ds_no_obs], KNOWN_GAPS)
        pt = trend["points"][0]
        self.assertIsNotNone(pt["gap_note"])
        self.assertIn("2022/23", pt["gap_note"])

    def test_clean_series_comparability(self):
        trend = build_trend_series("United Kingdom", HESA_SERIES, [])
        self.assertEqual(trend["series_comparability"], "clean")
        self.assertIsNone(trend["series_note"])

    def test_profile_varies_when_some_have_characteristics(self):
        ds_total = _ds(1, "United Kingdom", "2020/21", obs=[{"value": 21305.0, "characteristics": []}])
        ds_breakdown = _ds(2, "United Kingdom", "2021/22", obs=[
            {"value": 44195.0, "characteristics": [{"dimension": "mode_of_study", "value": "full_time"}]}
        ])
        trend = build_trend_series("United Kingdom", [ds_total, ds_breakdown], [])
        self.assertEqual(trend["series_comparability"], "profile_varies")
        self.assertIsNotNone(trend["series_note"])

    def test_characteristic_profile_returned_per_point(self):
        ds = _ds(1, "United Kingdom", "2021/22", obs=[
            {"value": 44195.0, "characteristics": [
                {"dimension": "mode_of_study", "value": "full_time"}
            ]}
        ])
        trend = build_trend_series("United Kingdom", [ds], [])
        pt = trend["points"][0]
        self.assertEqual(pt["characteristic_profile"], ["mode_of_study"])

    def test_bare_total_profile_is_empty_list(self):
        trend = build_trend_series("United Kingdom", [HESA_SERIES[0]], [])
        pt = trend["points"][0]
        self.assertEqual(pt["characteristic_profile"], [])

    def test_reliability_tier_preserved_in_points(self):
        trend = build_trend_series("United Kingdom", HESA_SERIES, [])
        for pt in trend["points"]:
            self.assertEqual(pt["reliability_tier"], "official_primary")

    def test_dataset_id_preserved_in_points(self):
        trend = build_trend_series("United Kingdom", [HESA_SERIES[0]], [])
        self.assertEqual(trend["points"][0]["dataset_id"], HESA_SERIES[0]["dataset_id"])

    def test_global_aggregate_accepted_if_caller_passes_it(self):
        """The service does not filter global aggregate — the API router does.
        Service builds whatever it's given; exclusion is the router's job."""
        ds = _ds(10, GLOBAL_AGGREGATE_COUNTRY, "2018", "unesco_outbound_mobility", 5,
                 obs=[{"value": 76338.0, "characteristics": []}])
        trend = build_trend_series(GLOBAL_AGGREGATE_COUNTRY, [ds], [])
        self.assertEqual(len(trend["points"]), 1)
        self.assertEqual(trend["points"][0]["value"], 76338.0)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class TestBuildSnapshot(unittest.TestCase):

    def _all_datasets(self):
        return HESA_SERIES + US_SERIES + [CANADA_DS, MALAYSIA_DS, UNESCO_DS]

    def test_global_aggregate_excluded_from_snapshot(self):
        snap = build_snapshot(self._all_datasets())
        countries = [e["country"] for e in snap]
        self.assertNotIn(GLOBAL_AGGREGATE_COUNTRY, countries)

    def test_all_non_global_countries_present(self):
        snap = build_snapshot(self._all_datasets())
        countries = {e["country"] for e in snap}
        self.assertIn("United Kingdom", countries)
        self.assertIn("United States", countries)
        self.assertIn("Canada", countries)
        self.assertIn("Malaysia", countries)

    def test_latest_period_selected_per_country(self):
        snap = build_snapshot(self._all_datasets())
        uk = next(e for e in snap if e["country"] == "United Kingdom")
        self.assertEqual(uk["period"], "2021/22")
        us = next(e for e in snap if e["country"] == "United States")
        self.assertEqual(us["period"], "2023/24")

    def test_unverified_source_marked_excluded(self):
        snap = build_snapshot(self._all_datasets())
        malaysia = next(e for e in snap if e["country"] == "Malaysia")
        self.assertTrue(malaysia["excluded_from_comparison"])
        self.assertIsNotNone(malaysia["exclusion_reason"])

    def test_verified_sources_not_excluded(self):
        snap = build_snapshot(self._all_datasets())
        uk = next(e for e in snap if e["country"] == "United Kingdom")
        self.assertFalse(uk["excluded_from_comparison"])
        self.assertIsNone(uk["exclusion_reason"])

    def test_comparable_to_same_metric_countries_only(self):
        """UK (HESA) and US (Open Doors) have different metric codes — not in each other's comparable_to."""
        snap = build_snapshot(self._all_datasets())
        uk = next(e for e in snap if e["country"] == "United Kingdom")
        us = next(e for e in snap if e["country"] == "United States")
        # Different metric codes
        self.assertNotIn("United States", uk["comparable_to"])
        self.assertNotIn("United Kingdom", us["comparable_to"])

    def test_deprecated_datasets_excluded(self):
        deprecated = _ds(99, "Germany", "2021/22", status="deprecated",
                         obs=[{"value": 5000.0, "characteristics": []}])
        snap = build_snapshot([deprecated] + HESA_SERIES)
        countries = [e["country"] for e in snap]
        self.assertNotIn("Germany", countries)

    def test_dataset_id_in_snapshot_entry(self):
        snap = build_snapshot([HESA_SERIES[-1]])
        self.assertEqual(snap[0]["dataset_id"], HESA_SERIES[-1]["dataset_id"])

    def test_metric_code_in_snapshot_entry(self):
        snap = build_snapshot([HESA_SERIES[-1]])
        self.assertEqual(snap[0]["metric_code"], "hesa_enrolled_headcount")

    def test_provenance_fields_present(self):
        snap = build_snapshot([HESA_SERIES[-1]])
        entry = snap[0]
        self.assertIn("reliability_tier", entry)
        self.assertIn("source_short_code", entry)
        self.assertIn("metric_definition_id", entry)


# ---------------------------------------------------------------------------
# Growth series
# ---------------------------------------------------------------------------

class TestBuildGrowthSeries(unittest.TestCase):

    def _uk_trend(self):
        return build_trend_series("United Kingdom", HESA_SERIES, [])

    def test_first_point_has_null_percent_change(self):
        growth = build_growth_series(self._uk_trend())
        self.assertIsNone(growth[0]["percent_change"])
        self.assertIsNone(growth[0]["absolute_change"])

    def test_known_growth_value_2018_to_2019(self):
        """10810 → 13020: (13020-10810)/10810 * 100 = 20.4384...% → 20.44"""
        growth = build_growth_series(self._uk_trend(), decimal_places=2)
        pt = next(p for p in growth if p["period"] == "2019/20")
        self.assertAlmostEqual(pt["percent_change"], 20.44, places=2)
        self.assertAlmostEqual(pt["absolute_change"], 2210.0, places=1)

    def test_known_growth_value_2019_to_2020(self):
        """13020 → 21305: (21305-13020)/13020 * 100 = 63.6328...% → 63.63"""
        growth = build_growth_series(self._uk_trend(), decimal_places=2)
        pt = next(p for p in growth if p["period"] == "2020/21")
        self.assertAlmostEqual(pt["percent_change"], 63.63, places=2)

    def test_known_growth_value_2020_to_2021(self):
        """21305 → 44195: (44195-21305)/21305 * 100 = 107.4396...% → 107.44"""
        growth = build_growth_series(self._uk_trend(), decimal_places=2)
        pt = next(p for p in growth if p["period"] == "2021/22")
        self.assertAlmostEqual(pt["percent_change"], 107.44, places=2)

    def test_gap_period_produces_null_growth(self):
        series = [
            _ds(1, "UK", "2020/21", obs=[{"value": 21305.0, "characteristics": []}]),
            _ds(2, "UK", "2021/22", obs=[]),
            _ds(3, "UK", "2022/23", obs=[{"value": 40000.0, "characteristics": []}]),
        ]
        trend = build_trend_series("UK", series, [])
        growth = build_growth_series(trend)
        gap = next(p for p in growth if p["period"] == "2021/22")
        self.assertIsNone(gap["percent_change"])
        self.assertIsNone(gap["absolute_change"])

    def test_gap_never_interpolated_in_growth(self):
        """After a gap, the next real value is compared to the last real value, not interpolated."""
        series = [
            _ds(1, "UK", "2020/21", obs=[{"value": 21305.0, "characteristics": []}]),
            _ds(2, "UK", "2021/22", obs=[]),   # gap
            _ds(3, "UK", "2022/23", obs=[{"value": 40000.0, "characteristics": []}]),
        ]
        trend = build_trend_series("UK", series, [])
        growth = build_growth_series(trend)
        post_gap = next(p for p in growth if p["period"] == "2022/23")
        # Should be (40000-21305)/21305 * 100 = 87.75...%
        expected = round((40000 - 21305) / 21305 * 100, 2)
        self.assertAlmostEqual(post_gap["percent_change"], expected, places=2)

    def test_decimal_places_respected(self):
        growth = build_growth_series(self._uk_trend(), decimal_places=4)
        pt = next(p for p in growth if p["period"] == "2019/20")
        raw = (13020 - 10810) / 10810 * 100
        expected = round(raw, 4)
        self.assertAlmostEqual(pt["percent_change"], expected, places=4)

    def test_length_matches_trend_points(self):
        trend = self._uk_trend()
        growth = build_growth_series(trend)
        self.assertEqual(len(growth), len(trend["points"]))

    def test_single_period_series_first_point_null(self):
        trend = build_trend_series("United Kingdom", [HESA_SERIES[0]], [])
        growth = build_growth_series(trend)
        self.assertIsNone(growth[0]["percent_change"])

    def test_reliability_tier_preserved_in_growth(self):
        growth = build_growth_series(self._uk_trend())
        for pt in growth:
            self.assertEqual(pt["reliability_tier"], "official_primary")


# ---------------------------------------------------------------------------
# Seed runtime tests
# ---------------------------------------------------------------------------

class TestSeedRuntime(unittest.TestCase):
    """
    Tests for seed_runtime.py using in-memory SQLite via SQLAlchemy.
    These tests require SQLAlchemy to be importable. If it isn't (sandbox
    environment), the tests are skipped with an explicit message rather
    than failing.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from app.models.models import Base
            cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
            # Enable FK support in SQLite (needed for cascade tests)
            from sqlalchemy import event
            @event.listens_for(cls.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
            Base.metadata.create_all(cls.engine)
            cls.Session = sessionmaker(bind=cls.engine)
            cls.sqlalchemy_available = True
        except ImportError:
            cls.sqlalchemy_available = False

    def setUp(self):
        if not self.sqlalchemy_available:
            self.skipTest("SQLAlchemy not installed — seed runtime tests skipped.")
        from app.models.models import Base
        # Drop and recreate all tables for a clean state each test
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()

    def tearDown(self):
        if self.sqlalchemy_available:
            self.db.close()

    def _make_seed(self, sources=None, metrics=None, datasets=None):
        """Create a minimal fake seed_data-like module."""
        import types
        m = types.SimpleNamespace()
        m.SOURCES = sources or [{
            "short_code": "HESA",
            "name": "Higher Education Statistics Agency",
            "organization_type": "national_statistics_agency",
            "home_country": "United Kingdom",
            "url": "https://www.hesa.ac.uk",
            "reliability_tier": "official_primary",
            "notes": "Test source.",
        }]
        m.METRIC_DEFINITIONS = metrics or [{
            "code": "hesa_enrolled_headcount",
            "name": "HESA enrolled student headcount",
            "description": "Test metric description.",
            "unit": "count of individuals",
        }]
        m.DATASETS = datasets or [{
            "source": "HESA",
            "metric": "hesa_enrolled_headcount",
            "title": "Test dataset",
            "destination_country": "United Kingdom",
            "reference_period": "2021/22",
            "original_url": "https://example.com",
            "limitations": "Test limitations.",
            "observations": [{"value": 44195}],
        }]
        return m

    def test_fresh_db_inserts_all_rows(self):
        from app.services.seed_runtime import run_seed
        seed = self._make_seed()
        result = run_seed(self.db, seed)
        self.db.commit()
        self.assertEqual(result["sources"]["inserted"], 1)
        self.assertEqual(result["metric_definitions"]["inserted"], 1)
        self.assertEqual(result["datasets"]["inserted"], 1)
        self.assertEqual(result["observations"]["inserted"], 1)
        self.assertFalse(result["has_conflicts"])

    def test_second_run_skips_all_rows(self):
        from app.services.seed_runtime import run_seed
        seed = self._make_seed()
        run_seed(self.db, seed)
        self.db.commit()
        # Second run
        result2 = run_seed(self.db, seed)
        self.db.commit()
        self.assertEqual(result2["sources"]["inserted"], 0)
        self.assertEqual(result2["sources"]["skipped"], 1)
        self.assertEqual(result2["datasets"]["inserted"], 0)
        self.assertEqual(result2["datasets"]["skipped"], 1)
        self.assertFalse(result2["has_conflicts"])

    def test_source_name_conflict_detected(self):
        from app.services.seed_runtime import run_seed
        original = self._make_seed()
        run_seed(self.db, original)
        self.db.commit()

        # Second seed with different name
        conflicting = self._make_seed(sources=[{
            "short_code": "HESA",
            "name": "WRONG NAME",   # differs from original
            "organization_type": "national_statistics_agency",
            "home_country": "United Kingdom",
            "url": "https://www.hesa.ac.uk",
            "reliability_tier": "official_primary",
            "notes": "Test source.",
        }])
        result = run_seed(self.db, conflicting)
        self.assertTrue(result["has_conflicts"])
        self.assertGreater(len(result["sources"]["conflicts"]), 0)
        self.assertIn("HESA", result["sources"]["conflicts"][0])

    def test_reliability_tier_conflict_detected(self):
        from app.services.seed_runtime import run_seed
        original = self._make_seed()
        run_seed(self.db, original)
        self.db.commit()

        conflicting = self._make_seed(sources=[{
            "short_code": "HESA",
            "name": "Higher Education Statistics Agency",
            "organization_type": "national_statistics_agency",
            "home_country": "United Kingdom",
            "url": "https://www.hesa.ac.uk",
            "reliability_tier": "unverified",  # wrong tier
            "notes": "Test source.",
        }])
        result = run_seed(self.db, conflicting)
        self.assertTrue(result["has_conflicts"])
        self.assertIn("reliability_tier", result["sources"]["conflicts"][0])

    def test_conflict_does_not_overwrite_data(self):
        from app.services.seed_runtime import run_seed
        from app.models.models import Source
        original = self._make_seed()
        run_seed(self.db, original)
        self.db.commit()

        conflicting = self._make_seed(sources=[{
            "short_code": "HESA",
            "name": "WRONG NAME",
            "organization_type": "national_statistics_agency",
            "home_country": "United Kingdom",
            "url": "https://www.hesa.ac.uk",
            "reliability_tier": "official_primary",
            "notes": "Test.",
        }])
        run_seed(self.db, conflicting)
        # Do NOT commit — caller should rollback on conflict

        # Name in DB must still be original
        src = self.db.query(Source).filter_by(short_code="HESA").first()
        self.assertEqual(src.name, "Higher Education Statistics Agency")

    def test_observation_value_conflict_detected(self):
        from app.services.seed_runtime import run_seed
        original = self._make_seed()
        run_seed(self.db, original)
        self.db.commit()

        # Re-seed with different observation value for same dataset identity
        conflicting = self._make_seed(datasets=[{
            "source": "HESA",
            "metric": "hesa_enrolled_headcount",
            "title": "Test dataset",
            "destination_country": "United Kingdom",
            "reference_period": "2021/22",
            "original_url": "https://example.com",
            "limitations": "Test limitations.",
            "observations": [{"value": 99999}],  # wrong value
        }])
        result = run_seed(self.db, conflicting)
        self.assertTrue(result["has_conflicts"])
        self.assertGreater(len(result["observations"]["conflicts"]), 0)

    def test_metric_description_conflict_detected(self):
        from app.services.seed_runtime import run_seed
        original = self._make_seed()
        run_seed(self.db, original)
        self.db.commit()

        conflicting = self._make_seed(metrics=[{
            "code": "hesa_enrolled_headcount",
            "name": "HESA enrolled student headcount",
            "description": "DIFFERENT DESCRIPTION",
            "unit": "count of individuals",
        }])
        result = run_seed(self.db, conflicting)
        self.assertTrue(result["has_conflicts"])
        self.assertIn("description", result["metric_definitions"]["conflicts"][0])

    def test_result_dict_has_all_required_keys(self):
        from app.services.seed_runtime import run_seed
        result = run_seed(self.db, self._make_seed())
        for table in ["sources", "metric_definitions", "datasets", "observations"]:
            self.assertIn(table, result)
            self.assertIn("inserted", result[table])
            self.assertIn("skipped", result[table])
            self.assertIn("conflicts", result[table])
        self.assertIn("has_conflicts", result)


if __name__ == "__main__":
    unittest.main()
