"""
Service module for observation_characteristics (Phase 3 Change 2).

Kept framework-free (no SQLAlchemy) for the same reason as csv_import.py:
every function here is executable and testable in this sandbox, which has
no network access to install packages. The DB-write step is in
csv_import_commit.py (untestable here), which calls build_characteristics()
to get the list to insert.

Design rules:
- Never infer a characteristic value not present in the source.
- Preserve the original source value; store normalized form separately.
- Only dimensions explicitly present in the column_mapping are stored.
- Do not encode measurement type into characteristics; that is metric_definition_id.
"""

from typing import Optional

# Dimension normalization tables.
# These are reference/nomenclature tables only -- no student counts, no
# analytical claims. A value absent from these tables is stored as-is
# (value_source='source_raw'), never silently dropped.
#
# IMPORTANT: every key must be the _normalize_key() form of the raw input
# (non-alphanumeric stripped, lowercased), because normalize_characteristic()
# applies _normalize_key() to the incoming value before looking it up here.
# Un-normalized keys (e.g. "full-time", "white british") can never match —
# they must appear as their stripped equivalents ("fulltime", "whitebritish").

MODE_OF_STUDY_ALIASES: dict[str, str] = {
    # "Full-Time", "full-time", "full time", "Full Time", "fulltime" → "fulltime"
    "fulltime": "full_time",
    # "FT", "ft" → "ft"
    "ft":       "full_time",
    # "Part-Time", "part-time", "part time", "Part Time", "parttime" → "parttime"
    "parttime": "part_time",
    # "PT", "pt" → "pt"
    "pt":       "part_time",
}

# A small set of common variants. The ethnicity vocabulary used by real sources
# (ONS 2011 census categories, HESA, etc.) is large and should not be
# fabricated here -- only genuinely observed aliases go in this table.
# All keys are the _normalize_key() form of the raw input.
ETHNICITY_ALIASES: dict[str, str] = {
    # "White - British", "White British", "white british", "White-British", "whiteBritish"
    "whitebritish":         "White - British",
    # "Asian or Asian British", "asian or asian british"
    "asianorasianbritish":  "Asian or Asian British",
    # "Black or Black British", "black or black british"
    "blackorblackbritish":  "Black or Black British",
    # "Mixed", "mixed"
    "mixed":                "Mixed",
    # "Other Ethnic Group", "other ethnic group"
    "otherethnicgroup":     "Other Ethnic Group",
    # "Not known", "not known"
    "notknown":             "Not known",
    # "Not stated", "Not Stated", "notstated"
    "notstated":            "Not stated",
}

# Which canonical dimensions have a normalization table.
# Dimensions not in this map are stored source_raw with no transformation.
_NORMALIZATION_TABLES: dict[str, dict[str, str]] = {
    "mode_of_study": MODE_OF_STUDY_ALIASES,
    "ethnicity": ETHNICITY_ALIASES,
    "ethnicity_minor": ETHNICITY_ALIASES,
}


def _normalize_key(v: str) -> str:
    """Same normalization used by csv_import's header matcher."""
    import re
    return re.sub(r"[^a-z0-9]", "", v.lower())


def normalize_characteristic(dimension: str, raw_value: str) -> tuple[str, str, Optional[str]]:
    """
    Returns (stored_value, value_source, raw_value_field).
    - If the dimension has a normalization table and the raw_value matches,
      returns (normalized_form, 'normalized', original_raw_value).
    - Otherwise returns (raw_value, 'source_raw', None).
    Never fabricates or drops a value.
    """
    table = _NORMALIZATION_TABLES.get(dimension)
    if table:
        key = _normalize_key(raw_value)
        if key in table:
            normalized = table[key]
            if normalized != raw_value:
                return normalized, "normalized", raw_value
    return raw_value, "source_raw", None


def build_characteristics(
    dimension_values: dict[str, Optional[str]],
) -> list[dict]:
    """
    Given a dict of {dimension: raw_value} (None values excluded), returns
    a list of dicts ready to be inserted as ObservationCharacteristic rows.
    Each dict has keys: dimension, value, value_source, raw_value.

    Called by csv_import_commit.py with the characteristic columns from the
    column mapping. The caller supplies only dimensions that were explicitly
    mapped and present in the source -- this function does not fabricate or
    infer any dimension.
    """
    characteristics = []
    for dimension, raw_value in dimension_values.items():
        if raw_value is None or raw_value == "":
            continue
        stored_value, value_source, raw_value_field = normalize_characteristic(dimension, raw_value)
        characteristics.append({
            "dimension": dimension,
            "value": stored_value,
            "value_source": value_source,
            "raw_value": raw_value_field,
        })
    return characteristics


def characteristics_dedupe_key(chars: list[dict]) -> frozenset:
    """
    Returns a frozenset of (dimension, value) tuples for use in the
    dedupe key, using the stored (potentially normalized) value.
    Two observations with the same canonical fields AND the same
    characteristic set are duplicates; different characteristics
    (e.g. Full-time vs Part-time) are distinct even if all canonical
    fields match.
    """
    return frozenset((c["dimension"], c["value"]) for c in chars)
