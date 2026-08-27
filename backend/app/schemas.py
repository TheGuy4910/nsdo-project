"""
Pydantic v2 schemas: request/response contracts for the API.

Immutability enforcement: DatasetUpdate deliberately does NOT declare
source_id, metric_definition_id, destination_country, or reference_period
as fields, and sets model_config = ConfigDict(extra="forbid"). Any PUT
request body that includes one of those keys is rejected by Pydantic itself
with a 422 before it ever reaches the database -- this makes "never
overwrite historical dataset identity" a structural guarantee rather than
a convention someone could forget to check in a router function.
"""

from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, field_validator

from app.services.validation import (
    validate_limitations, validate_reference_period, validate_short_code
)

OrganizationType = Literal[
    "national_statistics_agency", "international_organization",
    "government_department", "ngo_or_press", "secondary_aggregator",
]
ReliabilityTier = Literal[
    "official_primary", "official_secondary", "credible_secondary", "unverified",
]
DatasetStatus = Literal["draft", "validated", "verified", "deprecated"]


# ---------- Sources ----------

class SourceCreate(BaseModel):
    name: str
    short_code: str
    organization_type: OrganizationType
    home_country: Optional[str] = None
    url: Optional[str] = None
    reliability_tier: ReliabilityTier
    notes: Optional[str] = None

    @field_validator("short_code")
    @classmethod
    def _short_code(cls, v: str) -> str:
        return validate_short_code(v)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    organization_type: Optional[OrganizationType] = None
    home_country: Optional[str] = None
    url: Optional[str] = None
    reliability_tier: Optional[ReliabilityTier] = None
    notes: Optional[str] = None
    # short_code is intentionally excluded from Update: it's the stable
    # identifier datasets/tests reference informally. Delete and recreate
    # the source if a genuine rename is required.


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    short_code: str
    organization_type: str
    home_country: Optional[str]
    url: Optional[str]
    reliability_tier: str
    notes: Optional[str]
    created_at: datetime


# ---------- Metric definitions (read-only, nested into DatasetRead) ----------

class MetricDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str
    unit: str


# ---------- Datasets ----------

class DatasetCreate(BaseModel):
    source_id: int
    metric_definition_id: int
    title: str
    destination_country: str
    reference_period: str
    publication_date: Optional[date] = None
    original_filename: Optional[str] = None
    original_url: Optional[str] = None
    status: DatasetStatus = "draft"
    limitations: str
    superseded_by_id: Optional[int] = None

    @field_validator("limitations")
    @classmethod
    def _limitations(cls, v: str) -> str:
        return validate_limitations(v)

    @field_validator("reference_period")
    @classmethod
    def _reference_period(cls, v: str) -> str:
        return validate_reference_period(v)


class DatasetUpdate(BaseModel):
    """
    Deliberately excludes source_id, metric_definition_id,
    destination_country, reference_period -- see module docstring.
    To register a corrected/updated release of a dataset, create a new
    Dataset via POST and point the old one's superseded_by_id at it,
    or set status='deprecated' on the old one.
    """
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    publication_date: Optional[date] = None
    original_filename: Optional[str] = None
    original_url: Optional[str] = None
    status: Optional[DatasetStatus] = None
    limitations: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    superseded_by_id: Optional[int] = None

    @field_validator("limitations")
    @classmethod
    def _limitations(cls, v: Optional[str]) -> Optional[str]:
        return validate_limitations(v) if v is not None else v


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: SourceRead
    metric_definition: MetricDefinitionRead
    title: str
    destination_country: str
    reference_period: str
    publication_date: Optional[date]
    original_filename: Optional[str]
    original_url: Optional[str]
    status: str
    superseded_by_id: Optional[int]
    imported_at: datetime
    imported_by: str
    verified_at: Optional[datetime]
    verified_by: Optional[str]
    limitations: str


class ErrorResponse(BaseModel):
    detail: str


# ---------- Import pipeline (Phase 3A/3B) ----------

# ---------- Observations (read-only; written by import pipeline) ----------

class CharacteristicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    observation_id: int
    dimension: str
    value: str
    value_source: str
    raw_value: Optional[str]


class ObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dataset_id: int
    destination_country: str
    value: float
    academic_year: Optional[str]
    degree_level: Optional[str]
    institution: Optional[str]
    discipline: Optional[str]
    gender: Optional[str]
    funding_type: Optional[str]
    institution_type: Optional[str]
    nigerian_state: Optional[str]


class CsvImportCommitRequest(BaseModel):
    source_id: int
    metric_definition_id: int
    title: str
    reference_period: str
    limitations: str
    original_url: Optional[str] = None
    original_filename: Optional[str] = None
    column_mapping: dict[str, Optional[str]]
    include_warnings: bool = True
    include_duplicates: bool = False

    @field_validator("limitations")
    @classmethod
    def _limitations(cls, v: str) -> str:
        return validate_limitations(v)

    @field_validator("reference_period")
    @classmethod
    def _reference_period(cls, v: str) -> str:
        return validate_reference_period(v)


# ---------- Authentication (Phase 6) ----------

class UserCreate(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
