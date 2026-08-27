"""
Minimal API surface for Phase 3A: a preview endpoint (no DB writes) and a
commit endpoint (writes to Postgres). This is the entry point needed for
the "safe insertion into PostgreSQL" requirement -- without it, the CSV
pipeline (fully built and tested in csv_import.py) would have no way to be
invoked in an API-based system. No admin UI, no dataset listing/browsing
beyond what already exists on /api/datasets from Phase 2, no verify/
deprecate endpoints -- those remain out of scope for 3A.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app import schemas
from app.crud import NotFoundError, ConflictError
from app.services.csv_import import run_pipeline, ValidationIssue, MappingAmbiguity
from app.services.csv_import_commit import commit_csv_import
from app.api.auth import require_admin

router = APIRouter(prefix="/api/datasets/import/csv", tags=["csv-import"])


def _issue_to_dict(issue: ValidationIssue) -> dict:
    return {
        "row_index": issue.row_index, "field": issue.field, "rule": issue.rule,
        "severity": issue.severity, "message": issue.message,
    }


def _ambiguity_to_dict(amb: MappingAmbiguity) -> dict:
    return {
        "canonical_field": amb.canonical_field,
        "required": amb.required,
        "candidates": [{"column": c.column, "match_type": c.match_type} for c in amb.candidates],
        "reason": amb.reason,
        "resolution_required": amb.resolution_required,
    }


@router.post("/preview")
async def preview_csv(
    file: UploadFile = File(...),
    column_mapping: str | None = Form(None, description="JSON object: canonical_field -> source column name, or omit to auto-suggest"),
):
    """No database access at all -- parses, maps, validates, and returns a
    report for a human to review before anything is committed."""
    content = await file.read()
    mapping = json.loads(column_mapping) if column_mapping else None
    try:
        report = run_pipeline(content, column_mapping=mapping)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    all_issues = [i for r in report["results"] for i in r.issues]
    return {
        "filename": file.filename,
        "detected_columns": report["headers"],
        "suggested_mapping": report["suggested_mapping"],
        "mapping_used": report["mapping_used"],
        "ambiguities": [_ambiguity_to_dict(a) for a in report["ambiguities"]],
        "unresolved_required_ambiguities": [_ambiguity_to_dict(a) for a in report["unresolved_required_ambiguities"]],
        "summary": vars(report["summary"]),
        "issues": [_issue_to_dict(i) for i in all_issues],
        "sample_rows": [r.mapped for r in report["results"][:20]],
        "total_rows_parsed": len(report["results"]),
    }


@router.post("")
async def commit_csv(
    file: UploadFile = File(...),
    source_id: int = Form(...),
    metric_definition_id: int = Form(...),
    title: str = Form(...),
    reference_period: str = Form(...),
    limitations: str = Form(...),
    column_mapping: str = Form(..., description="JSON object: canonical_field -> source column name; confirm before committing"),
    _admin=Depends(require_admin),
    original_url: str | None = Form(None),
    original_filename: str | None = Form(None),
    include_warnings: bool = Form(True),
    include_duplicates: bool = Form(False),
    db: Session = Depends(get_db),
):
    """
    Re-parses and re-validates the file server-side (never trusts a
    client-supplied 'this is fine, just insert it' summary), then writes
    to Postgres. Errors are never inserted, ever. Duplicates and warnings
    are excluded unless explicitly opted into via the include_* flags,
    satisfying 'do not automatically discard questionable records without
    an explicit decision' -- the decision here is the caller's flags, made
    after seeing the /preview report.
    """
    content = await file.read()
    mapping = json.loads(column_mapping)
    try:
        report = run_pipeline(content, column_mapping=mapping)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if report["summary"].total_records == 0:
        raise HTTPException(status_code=400, detail="CSV contained no data rows")

    # Block commit if any required canonical field has unresolved ambiguity.
    # An ambiguity is unresolved when the caller's column_mapping still has
    # None for a required field that multiple source columns matched.
    unresolved = report["unresolved_required_ambiguities"]
    if unresolved:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "unresolved_mapping_ambiguity",
                "message": (
                    "This dataset cannot be committed because one or more required "
                    "canonical fields have multiple plausible source columns and no "
                    "explicit selection was made. Re-submit with a column_mapping "
                    "that explicitly resolves each ambiguous required field."
                ),
                "unresolved_required_ambiguities": [_ambiguity_to_dict(a) for a in unresolved],
            },
        )

    validated_meta = schemas.CsvImportCommitRequest(
        source_id=source_id, metric_definition_id=metric_definition_id, title=title,
        reference_period=reference_period, limitations=limitations,
        original_url=original_url, original_filename=original_filename or file.filename,
        column_mapping=mapping, include_warnings=include_warnings,
        include_duplicates=include_duplicates,
    )

    try:
        result = commit_csv_import(
            db,
            source_id=validated_meta.source_id,
            metric_definition_id=validated_meta.metric_definition_id,
            title=validated_meta.title,
            reference_period=validated_meta.reference_period,
            limitations=validated_meta.limitations,
            results=report["results"],
            summary=report["summary"],
            original_url=validated_meta.original_url,
            original_filename=validated_meta.original_filename,
            include_warnings=validated_meta.include_warnings,
            include_duplicates=validated_meta.include_duplicates,
            char_rows=report.get("char_rows"),
        )
    except NotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result
