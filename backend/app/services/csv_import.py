"""
CSV import pipeline for Phase 3A.

Deliberately framework-free (stdlib csv/io only, no pandas, no
FastAPI/SQLAlchemy) for two reasons: (1) this sandbox has no network access
to install packages, so anything with a hard external dependency can't be
executed here, and (2) parsing/validating a CSV genuinely doesn't need a
DataFrame -- csv.DictReader is sufficient and keeps this module testable
end-to-end with zero installs. Excel/JSON parsing (Phase 3B/3C) will need
pandas/openpyxl and are deliberately NOT implemented here.

This module does not touch a database. It takes bytes in and returns plain
dataclasses/dicts out. The DB-writing step lives in csv_import_commit.py,
which is untestable here (needs SQLAlchemy) and is kept separate so that
everything that CAN be tested is isolated from what can't.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Optional

CANONICAL_FIELDS = [
    "nigerian_state", "destination_country", "institution", "discipline",
    "degree_level", "academic_year", "gender", "funding_type",
    "institution_type", "student_count",
]

# Characteristic column mappings use this prefix in column_mapping keys to
# distinguish them from canonical fields: e.g.
#   {"characteristic:mode_of_study": "Full-time / Part-time", ...}
# means "map source column 'Full-time / Part-time' to the characteristic
# dimension 'mode_of_study'". This prefix makes the mapping self-describing
# and allows an arbitrary number of characteristic dimensions without
# pre-defining them all in CANONICAL_FIELDS.
CHARACTERISTIC_PREFIX = "characteristic:"

# A record needs at least these two to mean anything at all: some
# destination and some count. Everything else is genuinely optional,
# since real sources rarely report every dimension.
REQUIRED_FIELDS = ["destination_country", "student_count"]

# Header-matching synonyms for suggest_column_mapping. Not exhaustive --
# it's a starting suggestion for a human to confirm/correct, not an
# auto-commit. Matching is on a normalized (lowercased, non-alnum stripped)
# version of both the synonym and the actual header.
FIELD_SYNONYMS: dict[str, list[str]] = {
    "nigerian_state": ["state", "stateoforigin", "homestate", "originstate"],
    "destination_country": ["country", "destination", "hostcountry", "studycountry",
                             "destinationcountry", "countryname"],
    "institution": ["university", "school", "institution", "institutionname", "provider"],
    "discipline": ["subject", "fieldofstudy", "course", "discipline", "programme", "program"],
    "degree_level": ["level", "qualification", "degree", "degreelevel", "studylevel"],
    "academic_year": ["year", "period", "academicyear", "session", "cohortyear", "timeperiod"],
    "gender": ["sex", "gender"],
    "funding_type": ["funding", "scholarship", "sponsor", "fundingtype", "fundingsource"],
    "institution_type": ["institutiontype", "ownership", "publicprivate", "sector"],
    "student_count": ["students", "numberofstudents", "headcount",
                       "studentcount", "value", "tstudents"],
}

# Real-world country name normalization. This is reference nomenclature
# (how countries are commonly abbreviated/spelled), not analytical data --
# no student counts or claims about reality live in this table.
COUNTRY_ALIASES: dict[str, str] = {
    "uk": "United Kingdom", "u.k.": "United Kingdom", "unitedkingdom": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom",
    "usa": "United States", "u.s.a.": "United States", "us": "United States",
    "u.s.": "United States", "unitedstatesofamerica": "United States",
    "unitedstates": "United States",
    "canada": "Canada",
}

DEGREE_LEVEL_ALIASES: dict[str, str] = {
    "bsc": "undergraduate", "ba": "undergraduate", "bachelors": "undergraduate",
    "bachelor": "undergraduate", "undergraduate": "undergraduate", "ug": "undergraduate",
    "msc": "postgraduate_taught", "ma": "postgraduate_taught", "masters": "postgraduate_taught",
    "master": "postgraduate_taught", "pgt": "postgraduate_taught",
    "mres": "postgraduate_research", "mphil": "postgraduate_research",
    "phd": "doctoral", "doctorate": "doctoral", "dphil": "doctoral", "doctoral": "doctoral",
    # Added after validating against a real external dataset (DfE "Higher
    # Education Students", see tests/fixtures/external_dfe_he_students/) --
    # this is the actual vocabulary official UK government exports use,
    # which differs from the abbreviations above.
    "firstdegree": "undergraduate", "otherundergraduate": "undergraduate",
    "mastersandothers": "postgraduate_taught", "phdandequivalent": "doctoral",
}

_YEAR_PATTERN = re.compile(r"^(\d{4})(/(\d{2}))?$")
# Government/DfE exports commonly use a concatenated YYYYYY form (e.g.
# '202223' for 2022/23) rather than HESA's slash form. Found via real
# external dataset validation -- see tests/fixtures/external_dfe_he_students/.
_CONCATENATED_YEAR_PATTERN = re.compile(r"^(\d{4})(\d{2})$")

# Columns commonly present in real government/statistical exports that are
# structural/administrative metadata, not data a canonical field should
# ever bind to -- 'geographic_level' (e.g. 'National') is not a degree
# level just because it contains the substring 'level'. Found via real
# XLSX dataset validation (tests/fixtures/external_xlsx_dfe_widening_participation/).
# Excluded from substring-fallback candidacy only; an exact match (unlikely
# for these) would still be honored.
_ADMINISTRATIVE_COLUMNS = {"geographiclevel", "timeidentifier", "countrycode"}


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


@dataclass
class ValidationIssue:
    row_index: int
    field: Optional[str]
    rule: str
    severity: str  # 'error' | 'warning' | 'info'
    message: str


@dataclass
class MappingCandidate:
    column: str      # the source column name, as it appears in the file
    match_type: str  # 'exact_synonym' | 'substring_match'


@dataclass
class MappingAmbiguity:
    """
    Produced when more than one source column plausibly maps to the same
    canonical field. The pipeline never silently picks one -- instead it
    surfaces every candidate here so a human can make an explicit, auditable
    choice and supply it as a resolved column_mapping in the commit request.
    """
    canonical_field: str
    required: bool       # True if this field is in REQUIRED_FIELDS
    candidates: list     # list[MappingCandidate]
    reason: str
    resolution_required: bool  # True when required=True; always requires action before commit


@dataclass
class RecordResult:
    row_index: int
    raw_row: dict
    mapped: dict
    status: str  # 'valid' | 'warning' | 'error'
    issues: list = field(default_factory=list)
    is_duplicate: bool = False


@dataclass
class ImportSummary:
    total_records: int = 0
    valid_records: int = 0
    records_with_warnings: int = 0
    records_with_errors: int = 0
    duplicate_records: int = 0
    missing_value_counts: dict = field(default_factory=dict)


def parse_csv_bytes(content: bytes) -> tuple[list[str], list[dict]]:
    """
    Parses raw CSV bytes into (header list, list of raw row dicts).
    Handles a UTF-8 BOM (common in exports from Excel/government portals).
    Raises ValueError on completely unparseable input (e.g. no header row).
    """
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row / could not be parsed")
    rows = list(reader)
    return list(reader.fieldnames), rows


def suggest_column_mapping(headers: list[str]) -> dict[str, Optional[str]]:
    """
    Best-guess mapping from canonical field -> source column name, based on
    normalized header matching against FIELD_SYNONYMS. Tries an exact match
    first, then falls back to substring containment in either direction --
    real-world exports commonly prefix/suffix a field ('country_name',
    'time_period', 't_students') rather than using the bare synonym, and
    exact-only matching misses all of those. Still returns None for any
    canonical field with no plausible match at all -- this is a suggestion
    for a human to confirm or correct, never applied automatically to a
    commit.
    """
    normalized_headers = {_normalize_header(h): h for h in headers}
    mapping: dict[str, Optional[str]] = {}
    for canonical, synonyms in FIELD_SYNONYMS.items():
        match = None
        # Pass 1: exact normalized match (most confident).
        for syn in synonyms:
            if syn in normalized_headers:
                match = normalized_headers[syn]
                break
        # Pass 2: synonym-as-substring-of-header only. The reverse direction
        # (header inside synonym) caused accidental matches: 'country' appearing
        # inside the synonym 'studentcount' -- a completely wrong binding.
        # Only checking syn-in-header catches the intended cases like
        # 'students' matching 'numberofstudents' without the false positives.
        if match is None:
            for syn in sorted(synonyms, key=len, reverse=True):
                for norm_header, original_header in normalized_headers.items():
                    if norm_header.endswith("code") or norm_header.endswith("id"):
                        continue
                    if norm_header in _ADMINISTRATIVE_COLUMNS:
                        continue
                    if syn in norm_header:
                        match = original_header
                        break
                if match:
                    break
        mapping[canonical] = match
    return mapping


def detect_mapping_ambiguities(headers: list[str]) -> list:
    """
    Returns a list[MappingAmbiguity] for every canonical field where more
    than one source column is a plausible match. Runs the same matching
    logic as suggest_column_mapping but collects ALL candidates rather than
    picking the first one. A canonical field with zero or one candidate
    produces no ambiguity entry.

    This function is deliberately separate from suggest_column_mapping --
    the latter still returns a single best guess (for the preview UI to
    pre-populate), while this one returns the full ambiguity picture (for
    the UI to flag conflicts that require explicit resolution).
    """
    normalized_headers = {_normalize_header(h): h for h in headers}
    ambiguities = []

    for canonical, synonyms in FIELD_SYNONYMS.items():
        candidates = []

        # Pass 1: exact normalized matches.
        for syn in synonyms:
            if syn in normalized_headers:
                candidates.append(MappingCandidate(
                    column=normalized_headers[syn],
                    match_type="exact_synonym",
                ))

        # Pass 2: same rule as suggest_column_mapping — synonym-in-header only,
        # not header-in-synonym, to avoid accidental cross-field containment.
        exact_originals = {c.column for c in candidates}
        for syn in sorted(synonyms, key=len, reverse=True):
            for norm_header, original_header in normalized_headers.items():
                if original_header in exact_originals:
                    continue
                if norm_header.endswith("code") or norm_header.endswith("id"):
                    continue
                if norm_header in _ADMINISTRATIVE_COLUMNS:
                    continue
                if syn in norm_header:
                    candidates.append(MappingCandidate(
                        column=original_header,
                        match_type="substring_match",
                    ))

        if len(candidates) > 1:
            is_required = canonical in REQUIRED_FIELDS
            ambiguities.append(MappingAmbiguity(
                canonical_field=canonical,
                required=is_required,
                candidates=candidates,
                reason=(
                    f"{len(candidates)} source columns all plausibly match "
                    f"canonical field '{canonical}': "
                    + ", ".join(f"'{c.column}' ({c.match_type})" for c in candidates)
                ),
                resolution_required=is_required,
            ))

    return ambiguities


def has_unresolved_required_ambiguities(
    headers: list[str],
    column_mapping: dict,
) -> list:
    """
    Given a caller-supplied column_mapping, returns any MappingAmbiguity
    objects that are still unresolved (i.e. the mapping has None for a
    required field that has multiple candidates). Called by the commit
    endpoints before allowing any data to be written.

    An ambiguity is considered resolved if the caller has explicitly chosen
    one column for that field (mapping[canonical] is not None).
    """
    all_ambiguities = detect_mapping_ambiguities(headers)
    unresolved = []
    for amb in all_ambiguities:
        if amb.resolution_required and column_mapping.get(amb.canonical_field) is None:
            unresolved.append(amb)
    return unresolved


def apply_mapping(raw_rows: list[dict], mapping: dict[str, Optional[str]]) -> tuple[list[dict], list[dict]]:
    """
    Produces (canonical_rows, characteristic_rows) -- one entry per source row in each.

    canonical_rows: dict keyed by canonical field names (CANONICAL_FIELDS).
    characteristic_rows: dict of {dimension: raw_value} for each
        'characteristic:*' key in the mapping, where the value is not empty.
        None/empty values are excluded -- never stored as absent characteristics.

    A canonical field with mapping=None, or whose source cell is empty/whitespace,
    becomes None (NULL) -- never fabricated, never defaulted to a guess.
    """
    canonical_rows = []
    characteristic_rows = []
    for raw in raw_rows:
        # Canonical fields
        out = {}
        for canonical in CANONICAL_FIELDS:
            source_col = mapping.get(canonical)
            value = raw.get(source_col) if source_col else None
            if value is not None:
                value = str(value).strip()
                if value == "":
                    value = None
            out[canonical] = value
        canonical_rows.append(out)

        # Characteristic fields (prefixed keys in the mapping)
        char_out = {}
        for key, source_col in mapping.items():
            if not key.startswith(CHARACTERISTIC_PREFIX):
                continue
            dimension = key[len(CHARACTERISTIC_PREFIX):]
            if not dimension or not source_col:
                continue
            raw_val = raw.get(source_col)
            if raw_val is not None:
                raw_val = str(raw_val).strip()
                if raw_val == "":
                    raw_val = None
            if raw_val is not None:
                char_out[dimension] = raw_val
        characteristic_rows.append(char_out)

    return canonical_rows, characteristic_rows


def normalize_country(value: Optional[str]) -> tuple[Optional[str], bool]:
    """Returns (normalized_value, was_changed)."""
    if value is None:
        return None, False
    key = _normalize_header(value)
    if key in COUNTRY_ALIASES:
        normalized = COUNTRY_ALIASES[key]
        return normalized, (normalized != value)
    return value, False


def normalize_degree_level(value: Optional[str]) -> tuple[Optional[str], bool]:
    if value is None:
        return None, False
    key = _normalize_header(value)
    if key in DEGREE_LEVEL_ALIASES:
        normalized = DEGREE_LEVEL_ALIASES[key]
        return normalized, (normalized != value)
    return value, False


def _parse_count(raw: str) -> Optional[float]:
    try:
        cleaned = raw.replace(",", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def validate_record(mapped: dict, row_index: int) -> RecordResult:
    issues: list[ValidationIssue] = []

    # --- required fields ---
    if not mapped.get("destination_country"):
        issues.append(ValidationIssue(row_index, "destination_country", "missing_required_field",
                                       "error", "destination_country is required but missing/empty"))
    if not mapped.get("student_count"):
        issues.append(ValidationIssue(row_index, "student_count", "missing_required_field",
                                       "error", "student_count is required but missing/empty"))

    # --- student_count validity ---
    if mapped.get("student_count"):
        parsed = _parse_count(mapped["student_count"])
        if parsed is None:
            issues.append(ValidationIssue(row_index, "student_count", "invalid_student_count",
                                           "error", f"'{mapped['student_count']}' is not a valid number"))
        elif parsed < 0:
            issues.append(ValidationIssue(row_index, "student_count", "negative_value",
                                           "error", f"student_count cannot be negative ({parsed})"))
        elif parsed != int(parsed):
            issues.append(ValidationIssue(row_index, "student_count", "non_integer_count",
                                           "warning", f"student_count {parsed} is not a whole number"))

    # --- country normalization + unknown-country check ---
    country = mapped.get("destination_country")
    if country:
        normalized, changed = normalize_country(country)
        if changed:
            issues.append(ValidationIssue(row_index, "destination_country", "country_name_normalized",
                                           "info", f"'{country}' normalized to '{normalized}'"))
        # A short, deliberately small list of known countries -- this is
        # NOT meant to be exhaustive world geography, only enough to flag
        # values that look like a typo/garbage rather than a real country.
        # An unrecognized value is a warning, not an error: it may simply
        # not be in this list, and we don't want to reject real data over
        # an incomplete reference table.
        pass  # unknown-country detection is a warning, applied at commit stage per row list.

    # --- academic_year format check ---
    year = mapped.get("academic_year")
    if year:
        m = _YEAR_PATTERN.match(year)
        y = None
        if m:
            y = int(m.group(1))
        else:
            m2 = _CONCATENATED_YEAR_PATTERN.match(year)
            if m2:
                y = int(m2.group(1))
                issues.append(ValidationIssue(row_index, "academic_year", "concatenated_year_format",
                                               "info", f"'{year}' interpreted as concatenated YYYYYY "
                                               f"for {m2.group(1)}/{m2.group(2)} -- stored as given, not rewritten"))
            else:
                issues.append(ValidationIssue(row_index, "academic_year", "invalid_year_format",
                                               "error", f"'{year}' does not match YYYY, YYYY/YY, or YYYYYY format"))
        if y is not None and (y < 1990 or y > 2035):
            issues.append(ValidationIssue(row_index, "academic_year", "implausible_year",
                                           "warning", f"year {y} is outside the plausible 1990-2035 range"))

    # --- degree_level normalization (informational only) ---
    degree = mapped.get("degree_level")
    if degree:
        normalized, changed = normalize_degree_level(degree)
        if changed:
            issues.append(ValidationIssue(row_index, "degree_level", "degree_level_normalized",
                                           "info", f"'{degree}' normalized to '{normalized}'"))

    has_error = any(i.severity == "error" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)
    status = "error" if has_error else ("warning" if has_warning else "valid")

    return RecordResult(row_index=row_index, raw_row={}, mapped=mapped, status=status, issues=issues)


def _dedupe_key(mapped: dict, char_dict: Optional[dict] = None) -> tuple:
    """
    Builds the deduplication key for one observation. Two observations are
    considered duplicates only if ALL of the following match:
    1. Every canonical field (normalized where applicable).
    2. The full set of characteristics (dimension, normalized_value pairs).

    Rule 2 means Full-time and Part-time are DISTINCT even if all canonical
    fields match, as long as mode_of_study is included in both rows'
    characteristic mappings. An observation with no characteristics and one
    with characteristics are never duplicates (different information).
    """
    from app.services.characteristics import characteristics_dedupe_key, build_characteristics
    country, _ = normalize_country(mapped.get("destination_country"))
    degree, _ = normalize_degree_level(mapped.get("degree_level"))
    canonical_part = (
        country,
        mapped.get("institution"),
        mapped.get("discipline"),
        degree,
        mapped.get("academic_year"),
        mapped.get("nigerian_state"),
        mapped.get("gender"),
        mapped.get("funding_type"),
        mapped.get("institution_type"),
    )
    # Build the characteristic frozenset using the same normalization as the
    # commit step, so dedupe keys are consistent with what will be stored.
    if char_dict:
        built = build_characteristics(char_dict)
        char_part = characteristics_dedupe_key(built)
    else:
        char_part = frozenset()
    return canonical_part + (char_part,)


def detect_duplicates(results: list[RecordResult], char_rows: Optional[list[dict]] = None) -> None:
    """
    Mutates results in place. char_rows, if supplied, must be parallel to
    results (same length, same order) -- characteristics are included in the
    dedupe key so Full-time and Part-time are correctly distinct.
    """
    seen: dict[tuple, int] = {}
    for i, r in enumerate(results):
        char_dict = char_rows[i] if char_rows else None
        key = _dedupe_key(r.mapped, char_dict)
        if key in seen:
            r.is_duplicate = True
            r.issues.append(ValidationIssue(
                r.row_index, None, "duplicate_record", "warning",
                f"identical to row {seen[key]} across every mapped field except student_count"
            ))
            if r.status == "valid":
                r.status = "warning"
        else:
            seen[key] = r.row_index


def compute_summary(results: list[RecordResult]) -> ImportSummary:
    summary = ImportSummary(total_records=len(results))
    missing_counts = {f: 0 for f in CANONICAL_FIELDS}
    for r in results:
        if r.is_duplicate:
            summary.duplicate_records += 1
        if r.status == "error":
            summary.records_with_errors += 1
        elif r.status == "warning":
            summary.records_with_warnings += 1
        else:
            summary.valid_records += 1
        for f in CANONICAL_FIELDS:
            if not r.mapped.get(f):
                missing_counts[f] += 1
    summary.missing_value_counts = missing_counts
    return summary


def run_pipeline(csv_bytes: bytes, column_mapping: Optional[dict[str, Optional[str]]] = None) -> dict:
    """
    CSV entry point: parse -> shared process_rows(). See process_rows() for
    the mapping -> validate -> dedupe -> summarize steps shared with XLSX.
    """
    headers, raw_rows = parse_csv_bytes(csv_bytes)
    return process_rows(headers, raw_rows, column_mapping)


def process_rows(
    headers: list[str],
    raw_rows: list[dict],
    column_mapping: Optional[dict[str, Optional[str]]] = None,
) -> dict:
    """
    The shared processing core for every import format: (suggest or use
    given mapping) -> detect ambiguities -> apply mapping -> validate ->
    detect duplicates -> summarize. Takes already-parsed (headers, raw_rows)
    so CSV and XLSX (and any future format) call this exact same function --
    there is only one place mapping/validation/dedup/normalization logic
    lives, so their behavior cannot drift apart.

    The returned dict always contains an 'ambiguities' key. When the mapping
    was auto-suggested, this lists every field with multiple plausible source
    columns. When the caller supplied a full explicit mapping, ambiguities are
    still computed (to power the preview UI) but those that were explicitly
    resolved (mapping value is not None) are filtered out of the list --
    unresolved_required_ambiguities is the subset that would block a commit.
    """
    mapping = column_mapping if column_mapping is not None else suggest_column_mapping(headers)
    canonical_rows, char_rows = apply_mapping(raw_rows, mapping)

    ambiguities = detect_mapping_ambiguities(headers)
    # Filter to only unresolved ones if a mapping was provided
    if column_mapping is not None:
        ambiguities = [a for a in ambiguities
                       if column_mapping.get(a.canonical_field) is None]
    unresolved_required = [a for a in ambiguities if a.resolution_required]

    results = [validate_record(mapped, i) for i, mapped in enumerate(canonical_rows)]
    for i, raw in enumerate(raw_rows):
        results[i].raw_row = raw
    detect_duplicates(results, char_rows)
    summary = compute_summary(results)

    return {
        "headers": headers,
        "suggested_mapping": suggest_column_mapping(headers),
        "mapping_used": mapping,
        "ambiguities": ambiguities,
        "unresolved_required_ambiguities": unresolved_required,
        "results": results,
        "char_rows": char_rows,   # parallel to results; consumed by commit
        "summary": summary,
    }
