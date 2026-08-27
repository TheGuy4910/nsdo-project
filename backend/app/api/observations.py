"""
Read-only observations endpoint (Phase 4 + Phase 5).

Observations are written exclusively by the import pipeline
(csv_import_commit.py). This router exposes them for the frontend
dashboard so the chart can read actual database values rather than
relying on frontend-side constants that duplicate seed_data.py.

Phase 5 addition: GET /api/observations/{id}/characteristics — the
deferred Phase 3 endpoint for reading characteristic breakdowns on a
single observation.

No write endpoints here — all writes go through /api/datasets/import/csv
and /api/datasets/import/xlsx.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from typing import Optional
import csv, io

from app.database import get_db
from app import crud, schemas
from app.models.models import Observation, ObservationCharacteristic

router = APIRouter(prefix="/api/observations", tags=["observations"])


@router.get("", response_model=list[schemas.ObservationRead])
def list_observations(
    dataset_id: Optional[int] = Query(None, description="Filter by dataset"),
    destination_country: Optional[str] = Query(None, description="Filter by destination country (exact)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """
    Returns observations from the database. Used by the dashboard trend
    chart to display real values from the import pipeline rather than
    frontend-hardcoded constants.
    """
    return crud.list_observations(
        db,
        dataset_id=dataset_id,
        destination_country=destination_country,
        skip=skip,
        limit=limit,
    )


@router.get("/{observation_id}/characteristics",
            response_model=list[schemas.CharacteristicRead])
def get_observation_characteristics(
    observation_id: int,
    db: Session = Depends(get_db),
):
    """
    Characteristics (dimension breakdowns) for one observation.

    Returns an empty list when the observation has no sub-dimensions recorded
    (i.e. it is a bare total). Bare total is a valid and common state —
    most seed data observations have no characteristics.

    404 if the observation_id does not exist.
    """
    obs = (
        db.query(Observation)
        .options(joinedload(Observation.characteristics))
        .filter(Observation.id == observation_id)
        .first()
    )
    if obs is None:
        raise HTTPException(status_code=404, detail=f"Observation {observation_id} not found.")
    return obs.characteristics


@router.get("/export.csv")
def export_observations_csv(
    dataset_id: Optional[int] = Query(None),
    destination_country: Optional[str] = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    """
    Export filtered observations as a provenance-annotated CSV file.

    Decision C: public GET endpoint — reads are open.
    Decision D: provenance header block prefixed with '#'.

    Filters are the same as GET /api/observations.
    """
    observations = crud.list_observations(
        db, dataset_id=dataset_id,
        destination_country=destination_country,
        limit=limit,
    )

    def generate():
        yield "# NSDO Observation Export\n"
        if dataset_id:
            yield f"# dataset_id filter: {dataset_id}\n"
        if destination_country:
            yield f"# destination_country filter: {destination_country}\n"
        yield f"# row count: {len(observations)}\n"
        yield "# Values are sourced from named datasets with stated limitations.\n"
        yield "# Check each dataset's source and reliability_tier before citing.\n"
        yield "#\n"

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "observation_id", "dataset_id", "destination_country", "value",
            "academic_year", "degree_level", "institution",
            "discipline", "gender", "funding_type", "institution_type",
            "nigerian_state",
        ])
        yield buf.getvalue()
        buf.truncate(0); buf.seek(0)

        for obs in observations:
            writer.writerow([
                obs.id, obs.dataset_id,
                obs.destination_country, obs.value,
                obs.academic_year or "",
                obs.degree_level or "",
                obs.institution or "",
                obs.discipline or "",
                obs.gender or "",
                obs.funding_type or "",
                obs.institution_type or "",
                obs.nigerian_state or "",
            ])
            yield buf.getvalue()
            buf.truncate(0); buf.seek(0)

    fname = "nsdo-observations-export.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
