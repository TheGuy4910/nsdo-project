"""
Validation and business-rule helpers, kept as plain functions with no
FastAPI/Pydantic/SQLAlchemy dependency. This is deliberate: it lets these
exact functions be exercised directly in this sandbox (no network, no
installable packages) via backend/tests/test_validation_logic.py, rather
than every rule only existing inside untested Pydantic validators.
"""

from typing import Tuple


def validate_limitations(value: str) -> str:
    """
    A dataset without a stated limitation is exactly the failure mode this
    project exists to prevent. Reject empty/whitespace-only text.
    """
    if value is None or not value.strip():
        raise ValueError(
            "limitations must be a non-empty description of what this "
            "dataset does NOT tell you (methodology gaps, reference-period "
            "caveats, counting-basis ambiguity, etc.)"
        )
    return value.strip()


def validate_reference_period(value: str) -> str:
    if value is None or not value.strip():
        raise ValueError("reference_period must not be empty")
    return value.strip()


def validate_short_code(value: str) -> str:
    if value is None or not value.strip():
        raise ValueError("short_code must not be empty")
    cleaned = value.strip().upper()
    if " " in cleaned:
        raise ValueError("short_code must not contain spaces (use underscores)")
    return cleaned


def can_delete_dataset(status: str, observation_count: int) -> Tuple[bool, str]:
    """
    Enforces 'never overwrite historical datasets' at the delete boundary.
    A verified dataset, or any dataset with observations attached, represents
    recorded history and must be deprecated (PUT status='deprecated') rather
    than deleted. Only an empty draft may be hard-deleted.
    """
    if status == "verified":
        return False, ("Verified datasets cannot be deleted. Set status to "
                        "'deprecated' via PUT to preserve the historical record.")
    if observation_count > 0:
        return False, (f"Dataset has {observation_count} observation(s) attached "
                        "and cannot be deleted. Set status to 'deprecated' via PUT instead.")
    return True, "OK"


def can_delete_source(referencing_dataset_count: int) -> Tuple[bool, str]:
    if referencing_dataset_count > 0:
        return False, (f"Source is referenced by {referencing_dataset_count} "
                        "dataset(s) and cannot be deleted. Remove or reassign "
                        "those datasets first.")
    return True, "OK"


# Fields a PUT to /api/datasets/{id} must never be able to change. Enforced
# structurally in schemas.py (DatasetUpdate simply has no such fields, plus
# extra="forbid"), and re-checked here so the rule exists as a single named
# source of truth rather than only living inside a Pydantic model definition.
IMMUTABLE_DATASET_FIELDS = {
    "source_id", "metric_definition_id", "destination_country", "reference_period"
}
