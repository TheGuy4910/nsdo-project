from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app import crud, schemas
from app.api.auth import require_admin

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[schemas.SourceRead])
def list_sources(
    reliability_tier: Optional[schemas.ReliabilityTier] = Query(
        None, description="Filter to sources at this reliability tier"
    ),
    db: Session = Depends(get_db),
):
    return crud.list_sources(db, reliability_tier=reliability_tier)


@router.get("/{source_id}", response_model=schemas.SourceRead)
def get_source(source_id: int, db: Session = Depends(get_db)):
    try:
        return crud.get_source(db, source_id)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("", response_model=schemas.SourceRead, status_code=201)
def create_source(
    payload: schemas.SourceCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        return crud.create_source(db, payload)
    except crud.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/{source_id}", response_model=schemas.SourceRead)
def update_source(
    source_id: int,
    payload: schemas.SourceUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        return crud.update_source(db, source_id, payload)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except crud.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{source_id}", status_code=204)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        crud.delete_source(db, source_id)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except crud.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
