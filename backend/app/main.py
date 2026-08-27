"""
FastAPI application entrypoint.

Run with: uvicorn app.main:app --reload --port 8000
(from inside backend/, with DATABASE_URL set -- see docs/PHASE_2_NOTES.md)

Interactive API docs: http://localhost:8000/docs

Phase 5 additions:
  - Lifespan event: idempotency-checked seed on startup
  - Analytics, metric-definitions, admin routers registered
  - Observations router extended with /characteristics endpoint
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api import sources, datasets, import_csv, import_xlsx, observations
from app.api import analytics, metric_definitions, admin, auth
from app.api.auth import oauth2_scheme  # noqa: F401 — imported so FastAPI registers the scheme

logger = logging.getLogger("nsdo.startup")


# ---------------------------------------------------------------------------
# Lifespan: integrity-checked database seed on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup. Seeds the database from seed_data.py using the
    integrity-checking idempotent seeder (Phase 5, Decision B):
      - missing rows → inserted
      - identical rows → skipped
      - conflicting rows → logged as ERROR (never silently overwritten)

    The application starts regardless of seed outcome so the API remains
    available even if the seed encounters conflicts (those must be resolved
    manually by inspecting the database).
    """
    try:
        import sys
        seed_path = os.path.join(os.path.dirname(__file__), "..", "seed")
        sys.path.insert(0, seed_path)
        import seed_data
        from app.database import SessionLocal
        from app.services.seed_runtime import run_seed, SeedConflictError
        db = SessionLocal()
        try:
            result = run_seed(db, seed_data)
            if result["has_conflicts"]:
                all_conflicts = (
                    result["sources"]["conflicts"]
                    + result["metric_definitions"]["conflicts"]
                    + result["datasets"]["conflicts"]
                    + result["observations"]["conflicts"]
                )
                logger.error(
                    "SEED CONFLICT on startup — existing DB rows disagree with seed_data.py. "
                    "No seed data was written. Conflicts: %s",
                    "; ".join(all_conflicts),
                )
                db.rollback()
            else:
                db.commit()
                ins = sum(result[t]["inserted"] for t in ["sources","metric_definitions","datasets","observations"])
                skp = sum(result[t]["skipped"]  for t in ["sources","metric_definitions","datasets","observations"])
                logger.info("Startup seed complete: %d inserted, %d skipped.", ins, skp)
        except SeedConflictError as e:
            logger.error("Startup seed raised SeedConflictError: %s", e)
            db.rollback()
        finally:
            db.close()
    except Exception as exc:
        logger.warning(
            "Startup seed skipped (seed_data not importable or DB not ready): %s", exc
        )

    yield
    # shutdown: nothing to do


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Nigerian Student Diaspora Observatory API",
    description=(
        "Source-backed, provenance-tracked data on Nigerian students studying "
        "abroad. Every dataset is linked to a named source, a precise metric "
        "definition, and a stated set of limitations. Datasets are never "
        "overwritten -- revisions are new rows linked via superseded_by_id."
    ),
    version="0.6.0-phase6",
    lifespan=lifespan,
)

# Permissive CORS: the existing frontend is a static HTML file that may be
# opened directly from disk (origin "null") or served from any local port
# during development. Tighten this to a specific origin before any public
# deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers — all /api/* routes registered before static file mount
app.include_router(sources.router)
app.include_router(datasets.router)
app.include_router(import_csv.router)
app.include_router(import_xlsx.router)
app.include_router(observations.router)
app.include_router(analytics.router)
app.include_router(metric_definitions.router)
app.include_router(admin.router)
app.include_router(auth.router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static frontend — served from /app/static inside the container.
# The docker-compose.yml volume mounts ./frontend to /app/static.
# This must come after all /api/* routers so API routes are not shadowed.
# If the static directory does not exist (e.g. running backend only without
# the compose volume), the mount is skipped gracefully so the API still works.
# ---------------------------------------------------------------------------
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

if os.path.isdir(_STATIC_DIR):
    @app.get("/", include_in_schema=False)
    def serve_root():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
