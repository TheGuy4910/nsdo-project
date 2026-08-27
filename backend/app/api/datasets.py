from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import csv, io

from app.database import get_db
from app import crud, schemas
from app.api.auth import require_admin

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("", response_model=list[schemas.DatasetRead])
def list_datasets(
    source_id: Optional[int] = Query(None),
    destination_country: Optional[str] = Query(None),
    reference_period: Optional[str] = Query(None),
    metric_definition_id: Optional[int] = Query(None),
    status: Optional[schemas.DatasetStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return crud.list_datasets(
        db,
        source_id=source_id,
        destination_country=destination_country,
        reference_period=reference_period,
        metric_definition_id=metric_definition_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get("/{dataset_id}", response_model=schemas.DatasetRead)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    try:
        return crud.get_dataset(db, dataset_id)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("", response_model=schemas.DatasetRead, status_code=201)
def create_dataset(
    payload: schemas.DatasetCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        return crud.create_dataset(db, payload)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except crud.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/{dataset_id}", response_model=schemas.DatasetRead)
def update_dataset(
    dataset_id: int,
    payload: schemas.DatasetUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        return crud.update_dataset(db, dataset_id, payload)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except crud.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Hard-deletes only an empty, non-verified dataset.
    Verified or non-empty datasets → 409.
    Decision C: write operation → admin required.
    """
    try:
        crud.delete_dataset(db, dataset_id)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except crud.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/datasets/{id}/export.csv  (Decision D: provenance headers)
# ---------------------------------------------------------------------------

@router.get("/{dataset_id}/export.csv")
def export_dataset_csv(dataset_id: int, db: Session = Depends(get_db)):
    """
    Export all observations for one dataset as a CSV file.

    Decision D: provenance header rows prefixed with '#' are included at the
    top of the file, making it self-documenting. These rows follow the same
    convention as the project's real fixture files.

    This is a public GET endpoint (Decision C: reads are open).
    """
    try:
        ds = crud.get_dataset(db, dataset_id)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    observations = crud.list_observations(db, dataset_id=dataset_id, limit=2000)

    def generate():
        # Provenance header block (Decision D)
        yield f"# NSDO Export — {ds.title}\n"
        yield f"# Dataset ID: {ds.id}\n"
        yield f"# Source: {ds.source.name} ({ds.source.short_code})\n"
        yield f"# Reliability tier: {ds.source.reliability_tier}\n"
        yield f"# Metric: {ds.metric_definition.name} ({ds.metric_definition.code})\n"
        yield f"# Reference period: {ds.reference_period}\n"
        yield f"# Destination country: {ds.destination_country}\n"
        yield f"# Status: {ds.status}\n"
        yield f"# Limitations: {ds.limitations}\n"
        if ds.original_url:
            yield f"# Original URL: {ds.original_url}\n"
        yield f"# Exported from NSDO API — not for redistribution without attribution.\n"
        yield "#\n"

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "observation_id", "destination_country", "value",
            "academic_year", "degree_level", "institution",
            "discipline", "gender", "funding_type", "institution_type",
            "nigerian_state",
        ])
        yield buf.getvalue()
        buf.truncate(0); buf.seek(0)

        for obs in observations:
            writer.writerow([
                obs.id,
                obs.destination_country,
                obs.value,
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

    filename = f"nsdo-dataset-{dataset_id}-{ds.destination_country.replace(' ', '_')}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
