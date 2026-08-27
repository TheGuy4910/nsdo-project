"""
Analytics endpoints — Phase 5.

All business logic lives in app/services/analytics.py (framework-free).
This router is responsible only for:
  - reading from the database
  - assembling the dicts that analytics.py expects
  - calling analytics.py functions
  - shaping the response

No analytical logic lives in this file. No data is fabricated here.
Provenance (source, metric_definition, reliability_tier, dataset_id) is
preserved in every response object.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from app.database import get_db
from app.models.models import Dataset, Observation, ObservationCharacteristic, MetricDefinition
from app.services.analytics import (
    build_trend_series,
    build_snapshot,
    build_growth_series,
    assess_comparability,
    assess_multi_series_comparability,
    ComparabilityVerdict,
    GLOBAL_AGGREGATE_COUNTRY,
)

# Import KNOWN_GAPS for gap annotation — imported here so the service function
# stays pure (no seed_data dependency); the router injects them as a parameter.
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'seed'))
try:
    from seed_data import KNOWN_GAPS
except ImportError:
    KNOWN_GAPS = []

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Helpers — assemble the dict shape that analytics.py expects
# ---------------------------------------------------------------------------

def _dataset_to_dict(ds: Dataset) -> dict:
    """Convert ORM Dataset + loaded relationships to the analytics input shape."""
    return {
        "dataset_id": ds.id,
        "destination_country": ds.destination_country,
        "reference_period": ds.reference_period,
        "metric_definition_id": ds.metric_definition_id,
        "metric_code": ds.metric_definition.code,
        "metric_name": ds.metric_definition.name,
        "reliability_tier": ds.source.reliability_tier,
        "source_short_code": ds.source.short_code,
        "source_name": ds.source.name,
        "status": ds.status,
        "limitations": ds.limitations,
        "observations": [
            {
                "value": float(o.value),
                "characteristics": [
                    {"dimension": c.dimension, "value": c.value, "value_source": c.value_source}
                    for c in o.characteristics
                ],
            }
            for o in ds.observations
        ],
    }


def _load_datasets(db: Session, exclude_deprecated: bool = True) -> list[Dataset]:
    q = (
        db.query(Dataset)
        .options(
            joinedload(Dataset.source),
            joinedload(Dataset.metric_definition),
            joinedload(Dataset.observations).joinedload(Observation.characteristics),
        )
    )
    if exclude_deprecated:
        q = q.filter(Dataset.status != "deprecated")
    return q.all()


# ---------------------------------------------------------------------------
# GET /api/analytics/snapshot
# ---------------------------------------------------------------------------

@router.get("/snapshot")
def get_snapshot(db: Session = Depends(get_db)):
    """
    Latest available observation per destination country.

    Global aggregate (UNESCO) is excluded — it is available via
    GET /api/observations directly.

    Unverified sources are included but flagged with
    excluded_from_comparison=true and an exclusion_reason.

    Each entry includes a comparable_to list of other countries sharing the
    same metric_definition, and a comparability assessment for any pair.
    """
    datasets = _load_datasets(db)
    ds_dicts = [_dataset_to_dict(d) for d in datasets]
    snapshot = build_snapshot(ds_dicts)
    return {"snapshot": snapshot, "excluded_country": GLOBAL_AGGREGATE_COUNTRY}


# ---------------------------------------------------------------------------
# GET /api/analytics/trend
# ---------------------------------------------------------------------------

@router.get("/trend")
def get_trend(
    country: str = Query(..., description="Destination country (exact match)"),
    metric_definition_id: Optional[int] = Query(
        None,
        description=(
            "Restrict to this metric_definition_id. "
            "Required when the country has datasets from multiple metrics. "
            "If omitted and only one metric exists for the country, that metric is used. "
            "If omitted and multiple metrics exist, a 409 is returned with the available options."
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Time series of observations for one country.

    Returns sorted points (oldest first), null values for documented gaps,
    characteristic profile per point, and a series_comparability assessment.

    The response includes a multi_series_comparability field even for a
    single country so the caller knows whether it is safe to overlay this
    series with another country's series on one chart.
    """
    if country == GLOBAL_AGGREGATE_COUNTRY:
        raise HTTPException(
            status_code=400,
            detail=(
                "The global aggregate country is excluded from trend analysis. "
                "Use GET /api/observations to access UNESCO figures directly."
            ),
        )

    datasets = _load_datasets(db)
    country_datasets = [d for d in datasets if d.destination_country == country]

    if not country_datasets:
        raise HTTPException(status_code=404, detail=f"No datasets found for country: {country!r}")

    # Resolve metric
    available_metric_ids = list({d.metric_definition_id for d in country_datasets})
    if metric_definition_id is not None:
        filtered = [d for d in country_datasets if d.metric_definition_id == metric_definition_id]
        if not filtered:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No datasets for {country!r} with metric_definition_id={metric_definition_id}. "
                    f"Available metric_definition_ids: {available_metric_ids}"
                ),
            )
        country_datasets = filtered
    elif len(available_metric_ids) > 1:
        metric_info = []
        for ds in country_datasets:
            if ds.metric_definition_id not in [m["id"] for m in metric_info]:
                metric_info.append({
                    "id": ds.metric_definition_id,
                    "code": ds.metric_definition.code,
                    "name": ds.metric_definition.name,
                })
        raise HTTPException(
            status_code=409,
            detail={
                "error": "multiple_metrics_available",
                "message": (
                    f"Country {country!r} has datasets from {len(available_metric_ids)} "
                    "different metric definitions. Specify metric_definition_id to select one."
                ),
                "available_metrics": metric_info,
            },
        )

    ds_dicts = [_dataset_to_dict(d) for d in country_datasets]
    try:
        trend = build_trend_series(country, ds_dicts, KNOWN_GAPS)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"trend": trend}


# ---------------------------------------------------------------------------
# GET /api/analytics/growth
# ---------------------------------------------------------------------------

@router.get("/growth")
def get_growth(
    country: str = Query(..., description="Destination country"),
    metric_definition_id: Optional[int] = Query(None),
    decimal_places: int = Query(2, ge=0, le=6, description="Rounding precision for percent_change"),
    db: Session = Depends(get_db),
):
    """
    Period-over-period growth within a single metric series.

    The first point always has percent_change=null (no predecessor).
    Gap periods also have null values — they are never interpolated or
    filled with estimates.

    decimal_places: explicit rounding precision (default 2).
    Example: 10810 → 13020 = (13020-10810)/10810*100 = 20.4384...%
    Rounded to 2dp with round-half-even = 20.44%.
    """
    # Reuse the trend endpoint logic
    trend_response = get_trend(
        country=country,
        metric_definition_id=metric_definition_id,
        db=db,
    )
    trend = trend_response["trend"]
    growth = build_growth_series(trend, decimal_places=decimal_places)

    return {
        "country": country,
        "metric_code": trend["metric_code"],
        "metric_definition_id": trend["metric_definition_id"],
        "series_comparability": trend["series_comparability"],
        "series_note": trend["series_note"],
        "growth": growth,
    }


# ---------------------------------------------------------------------------
# GET /api/analytics/comparison
# ---------------------------------------------------------------------------

@router.get("/comparison")
def get_comparison(
    country_a: str = Query(...),
    country_b: str = Query(...),
    metric_definition_id_a: Optional[int] = Query(None),
    metric_definition_id_b: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Explicit side-by-side of two countries' latest snapshot values.

    Always returns a ComparabilityVerdict and a human-readable reason.
    Never silently presents cross-metric numbers as like-for-like.

    If the verdict is INCOMPARABLE, the 'value' fields are still returned
    so the caller can show both numbers — but the verdict and reason make
    it unambiguous that direct subtraction or ratio is not meaningful.
    """
    if country_a == country_b:
        raise HTTPException(status_code=400, detail="country_a and country_b must be different.")

    datasets = _load_datasets(db)

    def _latest_for(country: str, metric_id: Optional[int]) -> Optional[dict]:
        cds = [d for d in datasets if d.destination_country == country]
        if not cds:
            return None
        if metric_id is not None:
            cds = [d for d in cds if d.metric_definition_id == metric_id]
        if not cds:
            return None
        # Return the most recent by reference_period
        from app.services.analytics import sort_key_for_period
        cds_sorted = sorted(cds, key=lambda d: sort_key_for_period(d.reference_period), reverse=True)
        return _dataset_to_dict(cds_sorted[0])

    ds_a = _latest_for(country_a, metric_definition_id_a)
    ds_b = _latest_for(country_b, metric_definition_id_b)

    if ds_a is None:
        raise HTTPException(status_code=404, detail=f"No datasets found for country_a: {country_a!r}")
    if ds_b is None:
        raise HTTPException(status_code=404, detail=f"No datasets found for country_b: {country_b!r}")

    from app.services.analytics import characteristic_profile
    profile_a = frozenset()
    profile_b = frozenset()
    for obs in ds_a["observations"]:
        profile_a = characteristic_profile(obs.get("characteristics", []))
        break
    for obs in ds_b["observations"]:
        profile_b = characteristic_profile(obs.get("characteristics", []))
        break

    verdict = assess_comparability(
        metric_code_a=ds_a["metric_code"],
        metric_code_b=ds_b["metric_code"],
        reliability_tier_a=ds_a["reliability_tier"],
        reliability_tier_b=ds_b["reliability_tier"],
        char_profile_a=profile_a,
        char_profile_b=profile_b,
    )

    def _entry(ds: dict) -> dict:
        obs = ds["observations"]
        total = sum(o["value"] for o in obs) if obs else None
        return {
            "country": ds["destination_country"],
            "period": ds["reference_period"],
            "value": total,
            "dataset_id": ds["dataset_id"],
            "metric_code": ds["metric_code"],
            "metric_definition_id": ds["metric_definition_id"],
            "reliability_tier": ds["reliability_tier"],
            "source_short_code": ds["source_short_code"],
            "limitations": ds["limitations"],
        }

    return {
        "a": _entry(ds_a),
        "b": _entry(ds_b),
        "comparability": verdict,
    }


# ---------------------------------------------------------------------------
# GET /api/analytics/dashboard-comparability
# ---------------------------------------------------------------------------

@router.get("/dashboard-comparability")
def get_dashboard_comparability(db: Session = Depends(get_db)):
    """
    Returns a comparability assessment for the set of series currently
    visible on the dashboard overview chart (all non-deprecated, non-global,
    non-unverified country-level datasets).

    Used by the frontend to decide whether to show the amber warning banner.
    This endpoint never changes the chart data — it only provides the
    metadata needed to annotate it honestly.
    """
    datasets = _load_datasets(db)
    # Dashboard chart series: non-deprecated, not global aggregate
    chart_datasets = [
        d for d in datasets
        if d.destination_country != GLOBAL_AGGREGATE_COUNTRY
        and d.source.reliability_tier != "unverified"
        and d.status != "deprecated"
    ]

    if not chart_datasets:
        return {
            "comparability": {
                "all_comparable": True,
                "verdict": ComparabilityVerdict.COMPARABLE,
                "reason": "No data to compare.",
                "metric_codes_present": [],
            }
        }

    # One series per unique (country, metric_code) pair
    seen = {}
    for d in chart_datasets:
        key = (d.destination_country, d.metric_definition.code)
        if key not in seen:
            seen[key] = {
                "country": d.destination_country,
                "metric_code": d.metric_definition.code,
                "metric_definition_id": d.metric_definition_id,
            }

    series_list = list(seen.values())
    assessment = assess_multi_series_comparability(series_list)
    return {"comparability": assessment, "series": series_list}
