"""
Metric definitions — read-only endpoint.

Fixes the Phase 4 known limitation where the import wizard had to harvest
metric definitions by scanning existing datasets. This endpoint exposes them
directly so the import wizard dropdown is always correct even on an empty DB.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import MetricDefinition
from app import schemas

router = APIRouter(prefix="/api/metric-definitions", tags=["metric-definitions"])


@router.get("", response_model=list[schemas.MetricDefinitionRead])
def list_metric_definitions(db: Session = Depends(get_db)):
    """
    All registered metric definitions, ordered by code.
    These are seeded at startup and are not user-editable via the API.
    """
    return db.query(MetricDefinition).order_by(MetricDefinition.code).all()
