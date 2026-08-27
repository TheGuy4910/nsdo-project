"""
API surface for Phase 3B XLSX import. Deliberately mirrors
app/api/import_csv.py's shape (preview + commit endpoints) as closely as
possible -- the only genuinely new concern here is workbook/sheet
selection; mapping, validation, dedup, and commit are the exact same code
CSV uses (app.services.csv_import.process_rows and
app.services.csv_import_commit.commit_csv_import), not reimplemented.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app import schemas
from app.crud import NotFoundError, ConflictError
from app.services.xlsx_import import run_pipeline, list_sheet_names, XlsxParseError
from app.services.csv_import import ValidationIssue, MappingAmbiguity
from app.services.csv_import_commit import commit_csv_import
from app.api.auth import require_admin

router = APIRouter(prefix="/api/datasets/import/xlsx", tags=["xlsx-import"])


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


@router.post("/sheets")
async def list_workbook_sheets(file: UploadFile = File(...)):
    """
    Lets a caller discover what sheets exist before choosing one to
    preview/import -- no database access, no validation, just workbook
    introspection.
    """
    content = await file.read()
    try:
        return {"filename": file.filename, "sheets": list_sheet_names(content)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read workbook: {e}")


@router.post("/preview")
async def preview_xlsx(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None, description="Sheet to preview; omit to use the first sheet"),
    column_mapping: str | None = Form(None, description="JSON object: canonical_field -> source column name, or omit to auto-suggest"),
):
    """No database access -- parses the selected sheet, maps, validates,
    and returns a report for a human to review before anything commits."""
    content = await file.read()
    mapping = json.loads(column_mapping) if column_mapping else None
    try:
        report = run_pipeline(content, sheet_name=sheet_name, column_mapping=mapping)
    except (XlsxParseError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    all_issues = [i for r in report["results"] for i in r.issues]
    return {
        "filename": file.filename,
        "sheet_name": report["sheet_name"],
        "available_sheets": report["available_sheets"],
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
async def commit_xlsx(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    source_id: int = Form(...),
    metric_definition_id: int = Form(...),
    title: str = Form(...),
    reference_period: str = Form(...),
    limitations: str = Form(...),
    column_mapping: str = Form(..., description="JSON object: canonical_field -> source column name; confirm before committing"),
    original_url: str | None = Form(None),
    original_filename: str | None = Form(None),
    include_warnings: bool = Form(True),
    include_duplicates: bool = Form(False),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Re-parses and re-validates the selected sheet server-side, then writes
    to Postgres via the exact same commit_csv_import() function CSV uses --
    not a parallel implementation. Same error-never-inserted, same
    duplicate/warning opt-in flags, same never-overwrite dataset identity
    enforcement as the CSV path.
    """
    content = await file.read()
    mapping = json.loads(column_mapping)
    try:
        report = run_pipeline(content, sheet_name=sheet_name, column_mapping=mapping)
    except (XlsxParseError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if report["summary"].total_records == 0:
        raise HTTPException(status_code=400, detail="Selected sheet contained no data rows")

    unresolved = report["unresolved_required_ambiguities"]
    if unresolved:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "unresolved_mapping_ambiguity",
                "message": (
                    "This XLSX sheet cannot be committed because one or more required "
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
        original_url=original_url,
        original_filename=original_filename or f"{file.filename}#{report['sheet_name']}",
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
            imported_by="xlsx_import",
            char_rows=report.get("char_rows"),
        )
    except NotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    result["sheet_name"] = report["sheet_name"]
    return result
