"""
Analytics service for the Nigerian Student Diaspora Observatory.

All functions here are pure: they accept plain Python dicts/lists and return
plain Python dicts/lists. No FastAPI, no SQLAlchemy, no database dependency.
This matches the pattern established in validation.py and csv_import.py,
making every rule testable without infrastructure.

Comparability rules enforced here (from Phase 5 approval):
  1. metric_definition_id must match for a valid direct comparison.
  2. Characteristic/dimension profile must be considered — a bare total and
     a mode_of_study breakdown are not silently aggregable even if
     metric_definition_id matches.
  3. Geographic/measurement scope: global aggregates are excluded from
     country-level analytics.
  4. Source reliability: unverified sources are flagged and excluded from
     comparisons.

These rules are not suggestions. An analytics response that violates them
would be a data integrity failure, not a UX shortcut.
"""

from __future__ import annotations
from typing import Optional
import re


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GLOBAL_AGGREGATE_COUNTRY = "All destinations (global aggregate)"
UNVERIFIED_TIER = "unverified"

# metric_definition_ids that are genuine enrolled-headcount metrics.
# Used to produce METHODOLOGY_DIFFERS (rather than INCOMPARABLE) when two
# headcount instruments are compared against each other.
# The actual codes come from seed_data.py; we match on code strings since
# IDs are DB-assigned. The API layer resolves IDs → codes before calling here.
HEADCOUNT_METRIC_CODES = {
    "hesa_enrolled_headcount",
    "sevis_enrolled_headcount",
    "press_reported_enrollment",
}

INCOMPARABLE_METRIC_CODES = {
    "unverified_market_estimate",
    "unesco_outbound_mobility",    # global aggregate; incomparable to country counts
}


# ---------------------------------------------------------------------------
# ComparabilityVerdict
# ---------------------------------------------------------------------------

class ComparabilityVerdict:
    """
    Three-valued verdict on whether two datasets can be directly compared.

    COMPARABLE          — same metric_definition_id, same characteristic profile.
                          Direct numerical comparison is valid.
    METHODOLOGY_DIFFERS — different metric_definition_ids but both are
                          enrolled-headcount instruments. Comparison is possible
                          with a prominent caveat; the numbers are not identical
                          in meaning.
    INCOMPARABLE        — at least one dataset uses a metric that should never
                          be charted against an official enrolled-headcount
                          figure (unverified estimate, global aggregate, or a
                          press figure where counting basis is unconfirmed).
    """
    COMPARABLE = "comparable"
    METHODOLOGY_DIFFERS = "methodology_differs"
    INCOMPARABLE = "incomparable"


def assess_comparability(
    metric_code_a: str,
    metric_code_b: str,
    reliability_tier_a: str,
    reliability_tier_b: str,
    char_profile_a: frozenset,
    char_profile_b: frozenset,
) -> dict:
    """
    Return a comparability assessment dict:
      {
        "verdict":   ComparabilityVerdict.*,
        "reason":    str (plain English, always present),
        "characteristic_note": str | None (set when profiles differ),
      }

    Rules applied in order (first match wins):
      1. Either metric is INCOMPARABLE_METRIC_CODES → INCOMPARABLE
      2. Either source is unverified → INCOMPARABLE
      3. Same metric_code, compatible characteristic profiles → depends on profiles
      4. Both are HEADCOUNT_METRIC_CODES but codes differ → METHODOLOGY_DIFFERS
      5. Otherwise → INCOMPARABLE
    """
    char_note = None

    # Rule 1: intrinsically incomparable metric
    for code, label in [(metric_code_a, "A"), (metric_code_b, "B")]:
        if code in INCOMPARABLE_METRIC_CODES:
            return {
                "verdict": ComparabilityVerdict.INCOMPARABLE,
                "reason": (
                    f"Dataset {label} uses metric '{code}', which is not "
                    "comparable to enrolled-headcount figures. It must not be "
                    "plotted on the same axis without explicit separation."
                ),
                "characteristic_note": None,
            }

    # Rule 2: unverified reliability tier
    for tier, label in [(reliability_tier_a, "A"), (reliability_tier_b, "B")]:
        if tier == UNVERIFIED_TIER:
            return {
                "verdict": ComparabilityVerdict.INCOMPARABLE,
                "reason": (
                    f"Dataset {label} comes from an unverified source "
                    "(no disclosed methodology). It must never be compared "
                    "directly against official or credible figures."
                ),
                "characteristic_note": None,
            }

    # Rules 3–4: both are headcount-class metrics
    if metric_code_a == metric_code_b:
        # Same instrument — now check characteristic profiles
        if char_profile_a == char_profile_b:
            verdict = ComparabilityVerdict.COMPARABLE
            reason = "Same metric definition and same characteristic profile."
        else:
            # Same metric_definition_id but different breakdown dimensions —
            # not silently aggregable. Report the profile difference.
            only_in_a = char_profile_a - char_profile_b
            only_in_b = char_profile_b - char_profile_a
            parts = []
            if only_in_a:
                parts.append(f"Dataset A has dimensions not in B: {sorted(only_in_a)}")
            if only_in_b:
                parts.append(f"Dataset B has dimensions not in A: {sorted(only_in_b)}")
            char_note = (
                "Characteristic profiles differ. " + "; ".join(parts) + ". "
                "A bare total and a breakdown by the same metric are not "
                "directly aggregable — the total may already include all slices."
            )
            verdict = ComparabilityVerdict.METHODOLOGY_DIFFERS
            reason = (
                "Same metric definition but different characteristic profiles. "
                "Aggregating these without accounting for the profile difference "
                "risks double-counting or misrepresentation."
            )
        return {"verdict": verdict, "reason": reason, "characteristic_note": char_note}

    if metric_code_a in HEADCOUNT_METRIC_CODES and metric_code_b in HEADCOUNT_METRIC_CODES:
        return {
            "verdict": ComparabilityVerdict.METHODOLOGY_DIFFERS,
            "reason": (
                f"Both datasets count enrolled students, but use different "
                f"instruments: '{metric_code_a}' vs '{metric_code_b}'. "
                "The two figures measure similar but not identical populations "
                "using different data collection methods. Comparison is "
                "informative but not like-for-like."
            ),
            "characteristic_note": None,
        }

    # Catch-all
    return {
        "verdict": ComparabilityVerdict.INCOMPARABLE,
        "reason": (
            f"Metrics '{metric_code_a}' and '{metric_code_b}' are not "
            "compatible for direct comparison."
        ),
        "characteristic_note": None,
    }


# ---------------------------------------------------------------------------
# Period sorting
# ---------------------------------------------------------------------------

def sort_key_for_period(period: str) -> tuple:
    """
    Sort reference_period strings correctly.

    Handles:
      '2018/19' → (2018, 19)
      '2021/22' → (2021, 22)
      '2024'    → (2024, 0)
      '~2026 (undated estimate)' → (2026, 99)  [sorted last within year]
    """
    # Extract leading 4-digit year
    m = re.search(r'(\d{4})', period)
    if not m:
        return (9999, 99)
    year = int(m.group(1))
    # Extract trailing 2-digit suffix if academic year format
    m2 = re.search(r'/(\d{2})', period)
    suffix = int(m2.group(1)) if m2 else (99 if '~' in period or 'undated' in period else 0)
    return (year, suffix)


# ---------------------------------------------------------------------------
# Characteristic profile
# ---------------------------------------------------------------------------

def characteristic_profile(characteristics: list[dict]) -> frozenset:
    """
    Return the frozenset of dimension names for a set of characteristics.

    An empty frozenset means 'bare total' — no sub-dimensions recorded.
    This is distinct from None (unknown) and must be preserved as such.

    characteristics: list of dicts with at least a 'dimension' key.
    """
    return frozenset(c["dimension"] for c in characteristics)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def build_trend_series(
    country: str,
    datasets_with_obs: list[dict],
    known_gaps: list[str],
) -> dict:
    """
    Build a time-ordered trend series for one country.

    datasets_with_obs: list of dicts, each:
      {
        "dataset_id": int,
        "reference_period": str,
        "metric_definition_id": int,
        "metric_code": str,
        "reliability_tier": str,
        "observations": [{"value": float, "characteristics": [{"dimension": str, ...}]}],
      }

    All items MUST share the same metric_code; raises ValueError if not.
    (The caller — the API layer — is responsible for filtering to one metric
    before calling here. Mixing metrics here would be a logic error.)

    Returns:
      {
        "country": str,
        "metric_code": str,
        "metric_definition_id": int,
        "points": [
          {
            "period": str,
            "value": float | None,
            "dataset_id": int | None,
            "reliability_tier": str | None,
            "characteristic_profile": list[str],
            "characteristic_note": str | None,
            "is_gap": bool,
            "gap_note": str | None,
          }
        ],
        "series_comparability": str,   # "clean" | "profile_varies"
        "series_note": str | None,
      }
    """
    if not datasets_with_obs:
        return {
            "country": country,
            "metric_code": None,
            "metric_definition_id": None,
            "points": [],
            "series_comparability": "clean",
            "series_note": "No data available for this country and metric.",
        }

    # Validate homogeneous metric
    codes = {d["metric_code"] for d in datasets_with_obs}
    if len(codes) > 1:
        raise ValueError(
            f"build_trend_series received datasets with mixed metric codes: {codes}. "
            "Filter to a single metric_code before calling this function."
        )

    metric_code = codes.pop()
    metric_def_id = datasets_with_obs[0]["metric_definition_id"]

    # Sort by period
    sorted_ds = sorted(datasets_with_obs, key=lambda d: sort_key_for_period(d["reference_period"]))

    # Compute characteristic profiles per dataset
    points = []
    profiles_seen = set()
    profile_varies = False

    for ds in sorted_ds:
        obs = ds["observations"]
        profile = frozenset()
        char_note = None

        if obs:
            # All observations for one dataset should have the same characteristic profile
            # (they come from one import run). Take the union; flag if they differ internally.
            profiles_in_ds = {characteristic_profile(o.get("characteristics", [])) for o in obs}
            if len(profiles_in_ds) > 1:
                char_note = (
                    "This dataset contains observations with mixed characteristic profiles "
                    "(some have sub-dimensions, some do not). Summing them may double-count."
                )
            profile = profiles_in_ds.pop() if len(profiles_in_ds) == 1 else frozenset()

            total = sum(o["value"] for o in obs)
        else:
            total = None

        profiles_seen.add(profile)
        if len(profiles_seen) > 1:
            profile_varies = True

        points.append({
            "period": ds["reference_period"],
            "value": total,
            "dataset_id": ds["dataset_id"],
            "reliability_tier": ds["reliability_tier"],
            "characteristic_profile": sorted(profile),
            "characteristic_note": char_note,
            "is_gap": total is None,
            "gap_note": None,
        })

    # Annotate known gaps from seed_data.py KNOWN_GAPS
    for pt in points:
        if pt["is_gap"]:
            for gap_text in known_gaps:
                period_key = pt["period"][:7]  # e.g. '2022/23'
                if period_key in gap_text or country.lower() in gap_text.lower():
                    pt["gap_note"] = gap_text
                    break

    series_note = None
    if profile_varies:
        series_note = (
            "Characteristic profiles vary across periods in this series. "
            "Some periods report bare totals; others report breakdowns. "
            "Do not aggregate across periods without accounting for this."
        )

    return {
        "country": country,
        "metric_code": metric_code,
        "metric_definition_id": metric_def_id,
        "points": points,
        "series_comparability": "profile_varies" if profile_varies else "clean",
        "series_note": series_note,
    }


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def build_snapshot(
    datasets_with_obs: list[dict],
) -> list[dict]:
    """
    Return the most recent non-deprecated observation per country,
    with comparability annotations.

    datasets_with_obs: same shape as build_trend_series input, but ALL
    countries (not filtered to one). Each dict also has 'destination_country'.

    Exclusions (never appear in snapshot):
      - destination_country == GLOBAL_AGGREGATE_COUNTRY
      - reliability_tier == 'unverified'  (shown but flagged separately)

    Returns list of dicts:
      {
        "country": str,
        "period": str,
        "value": float,
        "dataset_id": int,
        "metric_code": str,
        "metric_definition_id": int,
        "reliability_tier": str,
        "source_short_code": str,
        "characteristic_profile": list[str],
        "excluded_from_comparison": bool,
        "exclusion_reason": str | None,
        "comparable_to": list[str],   # other countries with same metric_code
      }
    """
    # Group by country, keep latest by sort_key
    by_country: dict[str, dict] = {}
    for ds in datasets_with_obs:
        country = ds["destination_country"]
        if country == GLOBAL_AGGREGATE_COUNTRY:
            continue
        if ds["status"] == "deprecated":
            continue
        if not ds["observations"]:
            continue
        prev = by_country.get(country)
        if prev is None or (
            sort_key_for_period(ds["reference_period"])
            > sort_key_for_period(prev["reference_period"])
        ):
            by_country[country] = ds

    entries = []
    for country, ds in sorted(by_country.items()):
        obs = ds["observations"]
        total = sum(o["value"] for o in obs)
        profiles = {characteristic_profile(o.get("characteristics", [])) for o in obs}
        profile = profiles.pop() if len(profiles) == 1 else frozenset()

        excluded = ds["reliability_tier"] == UNVERIFIED_TIER
        excl_reason = (
            "Unverified source — no disclosed methodology. "
            "Excluded from cross-country comparisons."
        ) if excluded else None

        entries.append({
            "country": country,
            "period": ds["reference_period"],
            "value": total,
            "dataset_id": ds["dataset_id"],
            "metric_code": ds["metric_code"],
            "metric_definition_id": ds["metric_definition_id"],
            "reliability_tier": ds["reliability_tier"],
            "source_short_code": ds.get("source_short_code", ""),
            "characteristic_profile": sorted(profile),
            "excluded_from_comparison": excluded,
            "exclusion_reason": excl_reason,
            "comparable_to": [],   # filled in below
        })

    # Fill comparable_to: countries sharing the same metric_code, both non-excluded
    eligible = [e for e in entries if not e["excluded_from_comparison"]]
    for entry in entries:
        if entry["excluded_from_comparison"]:
            continue
        entry["comparable_to"] = [
            e["country"] for e in eligible
            if e["country"] != entry["country"]
            and e["metric_code"] == entry["metric_code"]
        ]

    return entries


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------

def build_growth_series(
    trend: dict,
    decimal_places: int = 2,
) -> list[dict]:
    """
    Compute period-over-period growth from a trend series.

    Only operates on non-gap points. First point in the series always has
    percent_change = None (no predecessor). Subsequent gaps produce None.

    decimal_places: rounding precision for percent_change.
        10810 → 13020: (13020 - 10810) / 10810 * 100 = 20.4384...%
        Rounded to 2dp → 20.44%. The rounding rule is round-half-even
        (Python default), applied explicitly here so tests can assert the
        exact value without ambiguity.

    Returns list of dicts:
      {
        "period": str,
        "value": float | None,
        "absolute_change": float | None,
        "percent_change": float | None,   # rounded to decimal_places
        "reliability_tier": str | None,
        "note": str | None,
      }
    """
    points = trend.get("points", [])
    result = []
    prev_value = None

    for pt in points:
        val = pt["value"]
        note = pt.get("characteristic_note")

        if val is None or prev_value is None:
            absolute_change = None
            percent_change = None
            if pt["is_gap"]:
                note = pt.get("gap_note") or "No data for this period."
        else:
            absolute_change = val - prev_value
            raw_pct = (absolute_change / prev_value) * 100
            # Explicit rounding with round-half-even (Python default for round())
            percent_change = round(raw_pct, decimal_places)

        result.append({
            "period": pt["period"],
            "value": val,
            "absolute_change": absolute_change,
            "percent_change": percent_change,
            "reliability_tier": pt.get("reliability_tier"),
            "note": note,
        })

        if val is not None:
            prev_value = val

    return result


# ---------------------------------------------------------------------------
# Multi-series comparability (for the dashboard warning)
# ---------------------------------------------------------------------------

def assess_multi_series_comparability(
    series_list: list[dict],
) -> dict:
    """
    Given a list of trend series (as returned by build_trend_series),
    assess whether they can be shown on one chart without a warning.

    Returns:
      {
        "all_comparable": bool,
        "verdict": ComparabilityVerdict.*,
        "reason": str,
        "metric_codes_present": list[str],
      }
    """
    codes = [s["metric_code"] for s in series_list if s.get("metric_code")]
    unique_codes = list(dict.fromkeys(codes))  # deduplicated, order-preserving

    if len(unique_codes) <= 1:
        return {
            "all_comparable": True,
            "verdict": ComparabilityVerdict.COMPARABLE,
            "reason": "All series use the same metric definition.",
            "metric_codes_present": unique_codes,
        }

    # Check if any series is intrinsically incomparable
    for code in unique_codes:
        if code in INCOMPARABLE_METRIC_CODES:
            return {
                "all_comparable": False,
                "verdict": ComparabilityVerdict.INCOMPARABLE,
                "reason": (
                    f"Series includes metric '{code}', which is not comparable "
                    "to enrolled-headcount figures. These should not share a chart axis."
                ),
                "metric_codes_present": unique_codes,
            }

    # All are headcount-class but with different codes
    if all(c in HEADCOUNT_METRIC_CODES for c in unique_codes):
        return {
            "all_comparable": False,
            "verdict": ComparabilityVerdict.METHODOLOGY_DIFFERS,
            "reason": (
                "This chart shows data from different measurement instruments "
                "(" + ", ".join(f"'{c}'" for c in unique_codes) + "). "
                "Both count enrolled students, but use different data collection "
                "methods and may not capture identical populations. "
                "Treat differences as indicative, not precise."
            ),
            "metric_codes_present": unique_codes,
        }

    return {
        "all_comparable": False,
        "verdict": ComparabilityVerdict.INCOMPARABLE,
        "reason": (
            "Multiple incompatible metrics present: "
            + ", ".join(f"'{c}'" for c in unique_codes)
        ),
        "metric_codes_present": unique_codes,
    }
