"""
Admin endpoints — Phase 5/6.

The seed endpoint uses integrity-checking idempotence (Decision B):
  - missing row → insert
  - identical row → skip
  - conflicting row → report error, never overwrite

Authentication: all endpoints here require an admin Bearer token
(via require_admin — Phase 6, Decision C). Unauthenticated callers
receive 401; authenticated non-admins receive 403.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.seed_runtime import run_seed, SeedConflictError
from app.api.auth import require_admin

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'seed'))
try:
    import seed_data
except ImportError:
    seed_data = None

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/seed")
def trigger_seed(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """
    Idempotent seed from seed_data.py.

    Returns counts of inserted/skipped/conflicted rows per table.
    A conflict means an existing DB row disagrees with the seed expectation
    on a key field (name, reliability_tier, limitations, etc.).

    Conflicts are returned as a 409 with a detailed message — they are never
    silently ignored. The operator must inspect the database manually if a
    conflict is detected.

    This endpoint is safe to call multiple times; it will not insert
    duplicate rows or overwrite existing data.
    """
    if seed_data is None:
        raise HTTPException(
            status_code=503,
            detail="seed_data module not found. Ensure backend/seed/seed_data.py exists.",
        )

    try:
        result = run_seed(db, seed_data)
        if result["has_conflicts"]:
            db.rollback()
            all_conflicts = (
                result["sources"]["conflicts"]
                + result["metric_definitions"]["conflicts"]
                + result["datasets"]["conflicts"]
                + result["observations"]["conflicts"]
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "seed_conflict",
                    "message": (
                        "One or more existing rows in the database conflict with "
                        "the seed data expectations. No data was written. "
                        "Inspect the database manually."
                    ),
                    "conflicts": all_conflicts,
                    "counts": {
                        "sources":            result["sources"],
                        "metric_definitions": result["metric_definitions"],
                        "datasets":           result["datasets"],
                        "observations":       result["observations"],
                    },
                },
            )
        db.commit()
        return {
            "status": "ok",
            "counts": {
                "sources":            result["sources"],
                "metric_definitions": result["metric_definitions"],
                "datasets":           result["datasets"],
                "observations":       result["observations"],
            },
        }
    except SeedConflictError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "error": "seed_conflict",
            "message": str(e),
            "conflicts": e.conflicts,
        })
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Seed failed: {e}")
