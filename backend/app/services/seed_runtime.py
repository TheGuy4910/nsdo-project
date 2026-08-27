"""
Integrity-checking idempotent database seeder for NSDO.

Behavior per approved Phase 5 decision B:
  - missing expected seed row → INSERT, count as 'inserted'
  - existing identical row    → skip, count as 'skipped'
  - existing row with values that conflict with seed → count as 'conflict',
    raise SeedConflictError — never silently overwrite
  - never overwrites existing data under any circumstances

The same function is used both by the startup lifespan event and by the
POST /api/admin/seed endpoint, ensuring consistent behaviour.

Conflict definition for each table:
  sources:
    Key: short_code. Conflict if name or reliability_tier differs.
  metric_definitions:
    Key: code. Conflict if name or description differs.
  datasets:
    Key: (source.short_code, destination_country, reference_period, metric.code).
    Conflict if title or limitations differ from seed expectation.
  observations:
    Key: (dataset_id, value). No conflict check — if the dataset identity
    matches and the observation value matches, skip. Extra observations in
    the DB beyond what seed expects are ignored (user may have imported more).

Returned result dict:
  {
    "sources":            {"inserted": int, "skipped": int, "conflicts": list[str]},
    "metric_definitions": {"inserted": int, "skipped": int, "conflicts": list[str]},
    "datasets":           {"inserted": int, "skipped": int, "conflicts": list[str]},
    "observations":       {"inserted": int, "skipped": int, "conflicts": list[str]},
    "has_conflicts":      bool,
  }
"""

from __future__ import annotations
from typing import Any
from sqlalchemy.orm import Session

from app.models.models import Source, MetricDefinition, Dataset, Observation, ProvenanceLog


class SeedConflictError(Exception):
    """Raised when an existing DB row conflicts with seed data expectations."""
    def __init__(self, conflicts: list[str]):
        self.conflicts = conflicts
        super().__init__(
            f"Seed conflict detected ({len(conflicts)} issue(s)). "
            "Existing data in the database does not match seed expectations. "
            "Inspect the database manually before re-seeding. "
            "Details: " + "; ".join(conflicts)
        )


def run_seed(db: Session, seed_data: Any) -> dict:
    """
    Run the idempotent seed against the provided database session.

    seed_data: the module or object exposing SOURCES, METRIC_DEFINITIONS,
               DATASETS lists (same structure as backend/seed/seed_data.py).

    Does NOT commit the session — caller commits so the lifespan event and
    the admin endpoint can both control transaction boundaries.
    """
    result = {
        "sources":            {"inserted": 0, "skipped": 0, "conflicts": []},
        "metric_definitions": {"inserted": 0, "skipped": 0, "conflicts": []},
        "datasets":           {"inserted": 0, "skipped": 0, "conflicts": []},
        "observations":       {"inserted": 0, "skipped": 0, "conflicts": []},
        "has_conflicts":      False,
    }

    # ---- Sources --------------------------------------------------------
    for s in seed_data.SOURCES:
        existing = db.query(Source).filter(Source.short_code == s["short_code"]).first()
        if existing is None:
            db.add(Source(
                short_code=s["short_code"],
                name=s["name"],
                organization_type=s["organization_type"],
                home_country=s.get("home_country"),
                url=s.get("url"),
                reliability_tier=s["reliability_tier"],
                notes=s.get("notes"),
            ))
            result["sources"]["inserted"] += 1
        else:
            conflicts = _check_source_conflicts(existing, s)
            if conflicts:
                result["sources"]["conflicts"].extend(conflicts)
                result["has_conflicts"] = True
            else:
                result["sources"]["skipped"] += 1

    # Flush so sources have IDs for the dataset FK
    try:
        db.flush()
    except Exception as exc:
        raise SeedConflictError([f"Database flush failed during source seeding: {exc}"])

    # Build short_code → id map
    src_map = {s.short_code: s.id for s in db.query(Source).all()}

    # ---- Metric definitions ---------------------------------------------
    for m in seed_data.METRIC_DEFINITIONS:
        existing = db.query(MetricDefinition).filter(MetricDefinition.code == m["code"]).first()
        if existing is None:
            db.add(MetricDefinition(
                code=m["code"],
                name=m["name"],
                description=m["description"],
                unit=m.get("unit", "count of individuals"),
            ))
            result["metric_definitions"]["inserted"] += 1
        else:
            conflicts = _check_metric_conflicts(existing, m)
            if conflicts:
                result["metric_definitions"]["conflicts"].extend(conflicts)
                result["has_conflicts"] = True
            else:
                result["metric_definitions"]["skipped"] += 1

    try:
        db.flush()
    except Exception as exc:
        raise SeedConflictError([f"Database flush failed during metric seeding: {exc}"])

    metric_map = {m.code: m.id for m in db.query(MetricDefinition).all()}

    # ---- Datasets + observations ----------------------------------------
    for d in seed_data.DATASETS:
        source_id = src_map.get(d["source"])
        metric_id = metric_map.get(d["metric"])

        if source_id is None:
            result["datasets"]["conflicts"].append(
                f"Dataset '{d['title']}': source '{d['source']}' not found in DB after seeding sources."
            )
            result["has_conflicts"] = True
            continue
        if metric_id is None:
            result["datasets"]["conflicts"].append(
                f"Dataset '{d['title']}': metric '{d['metric']}' not found in DB after seeding metrics."
            )
            result["has_conflicts"] = True
            continue

        existing_ds = db.query(Dataset).filter(
            Dataset.source_id == source_id,
            Dataset.destination_country == d["destination_country"],
            Dataset.reference_period == d["reference_period"],
            Dataset.metric_definition_id == metric_id,
        ).first()

        if existing_ds is None:
            new_ds = Dataset(
                source_id=source_id,
                metric_definition_id=metric_id,
                title=d["title"],
                destination_country=d["destination_country"],
                reference_period=d["reference_period"],
                original_url=d.get("original_url"),
                limitations=d["limitations"],
                status="verified",
                imported_by="seed_runtime",
            )
            db.add(new_ds)
            db.flush()  # get ID for observations

            for obs_spec in d.get("observations", []):
                db.add(Observation(
                    dataset_id=new_ds.id,
                    destination_country=d["destination_country"],
                    value=obs_spec["value"],
                ))
                result["observations"]["inserted"] += 1

            db.add(ProvenanceLog(
                dataset_id=new_ds.id,
                source_id=source_id,
                action="imported",
                actor="seed_runtime",
                detail="Seeded from seed_data.py via run_seed()",
            ))
            result["datasets"]["inserted"] += 1

        else:
            # Dataset exists — check for value conflicts in key fields
            conflicts = _check_dataset_conflicts(existing_ds, d)
            if conflicts:
                result["datasets"]["conflicts"].extend(conflicts)
                result["has_conflicts"] = True
            else:
                result["datasets"]["skipped"] += 1

            # Check observations — skip if value already present, conflict if mismatched
            for obs_spec in d.get("observations", []):
                expected_val = float(obs_spec["value"])
                existing_obs = db.query(Observation).filter(
                    Observation.dataset_id == existing_ds.id,
                ).all()
                if any(abs(float(o.value) - expected_val) < 0.01 for o in existing_obs):
                    result["observations"]["skipped"] += 1
                elif existing_obs:
                    # Observations exist but none match the expected value
                    found_vals = [float(o.value) for o in existing_obs]
                    result["observations"]["conflicts"].append(
                        f"Dataset '{d['title']}' ({d['destination_country']} {d['reference_period']}): "
                        f"expected observation value {expected_val}, found {found_vals}."
                    )
                    result["has_conflicts"] = True
                else:
                    # Dataset exists but has no observations — insert
                    db.add(Observation(
                        dataset_id=existing_ds.id,
                        destination_country=d["destination_country"],
                        value=obs_spec["value"],
                    ))
                    result["observations"]["inserted"] += 1

    return result


# ---------------------------------------------------------------------------
# Conflict checkers — compare DB row against seed spec
# ---------------------------------------------------------------------------

def _check_source_conflicts(existing: Source, spec: dict) -> list[str]:
    conflicts = []
    if existing.name != spec["name"]:
        conflicts.append(
            f"Source '{spec['short_code']}': name mismatch. "
            f"DB='{existing.name}', seed='{spec['name']}'."
        )
    if existing.reliability_tier != spec["reliability_tier"]:
        conflicts.append(
            f"Source '{spec['short_code']}': reliability_tier mismatch. "
            f"DB='{existing.reliability_tier}', seed='{spec['reliability_tier']}'."
        )
    return conflicts


def _check_metric_conflicts(existing: MetricDefinition, spec: dict) -> list[str]:
    conflicts = []
    if existing.name != spec["name"]:
        conflicts.append(
            f"MetricDefinition '{spec['code']}': name mismatch. "
            f"DB='{existing.name}', seed='{spec['name']}'."
        )
    if existing.description != spec["description"]:
        conflicts.append(
            f"MetricDefinition '{spec['code']}': description mismatch. "
            f"(truncated) DB='{existing.description[:60]}...', "
            f"seed='{spec['description'][:60]}...'."
        )
    return conflicts


def _check_dataset_conflicts(existing: Dataset, spec: dict) -> list[str]:
    conflicts = []
    if existing.title != spec["title"]:
        conflicts.append(
            f"Dataset identity ({spec['destination_country']} {spec['reference_period']}): "
            f"title mismatch. DB='{existing.title}', seed='{spec['title']}'."
        )
    if existing.limitations != spec["limitations"]:
        conflicts.append(
            f"Dataset identity ({spec['destination_country']} {spec['reference_period']}): "
            f"limitations mismatch. "
            f"DB='{existing.limitations[:60]}...', seed='{spec['limitations'][:60]}...'."
        )
    return conflicts
