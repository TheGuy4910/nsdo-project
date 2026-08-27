"""
Commits a validated CSV import into the database. Separated from
csv_import.py (which is pure/testable) because this module necessarily
touches the SQLAlchemy session and therefore can't be executed in this
sandbox (no network access to install sqlalchemy/psycopg2). Reviewed
carefully; its *behavior* (uniqueness enforcement, never-overwrite,
provenance logging) is proven separately in
tests/verify_phase3a_commit_behavior.py against sqlite3.
"""

import uuid
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.models import Source, MetricDefinition, Dataset, Observation, ObservationCharacteristic, ProvenanceLog, ValidationReport
from app.crud import NotFoundError, ConflictError
from app.services.csv_import import RecordResult, ImportSummary
from app.services.characteristics import build_characteristics


def _dataset_destination_country(results: list[RecordResult]) -> str:
    """
    A Dataset row needs a single destination_country. If every included
    row agrees, use that value. If a CSV genuinely spans multiple
    countries in one file, we don't force a fake single value -- we record
    that explicitly instead, and the real per-row country is preserved on
    every Observation regardless.
    """
    countries = {r.mapped.get("destination_country") for r in results if r.mapped.get("destination_country")}
    if len(countries) == 1:
        return next(iter(countries))
    return "Multiple destinations (see individual observations)"


def commit_csv_import(
    db: Session,
    source_id: int,
    metric_definition_id: int,
    title: str,
    reference_period: str,
    limitations: str,
    results: list[RecordResult],
    summary: ImportSummary,
    original_url: str | None = None,
    original_filename: str | None = None,
    include_warnings: bool = True,
    include_duplicates: bool = False,
    imported_by: str = "csv_import",
    char_rows: list[dict] | None = None,   # parallel to results, from process_rows()
) -> dict:
    if db.get(Source, source_id) is None:
        raise NotFoundError(f"source_id {source_id} does not exist")
    if db.get(MetricDefinition, metric_definition_id) is None:
        raise NotFoundError(f"metric_definition_id {metric_definition_id} does not exist")

    included = []
    for r in results:
        if r.status == "error":
            continue  # errors are never inserted, no override available
        if r.is_duplicate and not include_duplicates:
            continue
        if r.status == "warning" and not include_warnings:
            continue
        included.append(r)

    destination_country = _dataset_destination_country(included) if included else "Unknown"

    dataset = Dataset(
        source_id=source_id,
        metric_definition_id=metric_definition_id,
        title=title,
        destination_country=destination_country,
        reference_period=reference_period,
        original_url=original_url,
        original_filename=original_filename,
        status="validated",
        imported_by=imported_by,
        limitations=limitations,
    )
    db.add(dataset)
    try:
        db.flush()  # surfaces the uniqueness IntegrityError without committing yet
    except IntegrityError as e:
        db.rollback()
        raise ConflictError(
            "A dataset already exists for this exact (source, destination_country, "
            "reference_period, metric_definition) combination. This CSV's rows span "
            f"'{destination_country}' -- if this is a genuine revision, use a new "
            "reference_period or link supersession explicitly; this endpoint never "
            "overwrites an existing dataset."
        ) from e

    import_batch_id = str(uuid.uuid4())
    observations_imported = 0
    for r in included:
        m = r.mapped
        obs = Observation(
            dataset_id=dataset.id,
            destination_country=m.get("destination_country"),
            institution=m.get("institution"),
            discipline=m.get("discipline"),
            degree_level=m.get("degree_level"),
            value=float(m["student_count"]),
            raw_source_row=r.row_index,
            nigerian_state=m.get("nigerian_state"),
            academic_year=m.get("academic_year"),
            gender=m.get("gender"),
            funding_type=m.get("funding_type"),
            institution_type=m.get("institution_type"),
            import_batch_id=import_batch_id,
        )
        db.add(obs)
        db.flush()  # get obs.id for characteristics

        # Insert characteristics if any were mapped for this row.
        # char_rows is parallel to the original results list; find this
        # row's index in the original (r.row_index) to look it up.
        if char_rows and r.row_index < len(char_rows):
            char_dict = char_rows[r.row_index]
            for char in build_characteristics(char_dict):
                db.add(ObservationCharacteristic(
                    observation_id=obs.id,
                    dimension=char["dimension"],
                    value=char["value"],
                    value_source=char["value_source"],
                    raw_value=char["raw_value"],
                ))

        observations_imported += 1

    db.add(ProvenanceLog(
        dataset_id=dataset.id,
        source_id=source_id,
        action="imported",
        actor=imported_by,
        detail=(
            f"CSV import batch {import_batch_id}: {observations_imported} observation(s) "
            f"inserted from {summary.total_records} parsed record(s) "
            f"({summary.records_with_errors} rejected as errors, "
            f"{summary.duplicate_records} duplicate(s) detected, "
            f"include_duplicates={include_duplicates}, include_warnings={include_warnings})."
        ),
    ))

    rule_counts: dict[str, int] = {}
    for r in results:
        for issue in r.issues:
            rule_counts[issue.rule] = rule_counts.get(issue.rule, 0) + 1
    for rule_name, count in rule_counts.items():
        db.add(ValidationReport(
            dataset_id=dataset.id,
            rule_name=rule_name,
            status="fail" if "error" in rule_name or rule_name in (
                "missing_required_field", "invalid_student_count", "negative_value",
                "invalid_year_format") else "warning",
            message=f"{count} record(s) triggered rule '{rule_name}'",
            affected_rows=count,
        ))
    db.add(ValidationReport(
        dataset_id=dataset.id,
        rule_name="import_summary",
        status="pass" if summary.records_with_errors == 0 else "warning",
        message=(
            f"{summary.total_records} total, {summary.valid_records} valid, "
            f"{summary.records_with_warnings} warning(s), {summary.records_with_errors} error(s), "
            f"{summary.duplicate_records} duplicate(s)"
        ),
        affected_rows=summary.total_records,
    ))

    db.commit()
    db.refresh(dataset)

    return {
        "dataset_id": dataset.id,
        "import_batch_id": import_batch_id,
        "observations_imported": observations_imported,
        "observations_rejected_error": summary.records_with_errors,
        "observations_skipped_as_duplicate": sum(1 for r in results if r.is_duplicate and not include_duplicates),
        "destination_country": destination_country,
    }
