"""
SQLAlchemy ORM models for the Nigerian Student Diaspora Observatory.

Mirrors backend/migrations/001_init.sql + 002 + 003 exactly.

Phase 3 (Change 2) addition: ObservationCharacteristic for generic
breakdown dimensions (mode_of_study, ethnicity, etc.) that vary by
source and cannot all be pre-anticipated as fixed columns.

NOTE: not executed against a live SQLAlchemy install in this sandbox
(no network access). Syntax verified. See docs for local run instructions.
"""

from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    String, Text, Integer, BigInteger, Numeric, ForeignKey,
    CheckConstraint, UniqueConstraint, DateTime, Date, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Postgres uses BIGINT for these high-volume tables' primary keys, but plain
# `BigInteger` primary keys are not auto-incremented by SQLite (SQLite only
# autoincrements a column declared exactly as `INTEGER PRIMARY KEY`). The
# unit test suite runs against an in-memory SQLite DB, so we use a dialect
# variant: BIGINT on Postgres in production, plain INTEGER (autoincrementing)
# on SQLite in tests. This changes no production behavior.
BigIntPK = Integer().with_variant(BigInteger, "postgresql")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    short_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    organization_type: Mapped[str] = mapped_column(Text, nullable=False)
    home_country: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    reliability_tier: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    datasets: Mapped[list["Dataset"]] = relationship(back_populates="source")

    __table_args__ = (
        CheckConstraint(
            "organization_type in ('national_statistics_agency','international_organization',"
            "'government_department','ngo_or_press','secondary_aggregator')",
            name="ck_source_org_type"),
        CheckConstraint(
            "reliability_tier in ('official_primary','official_secondary',"
            "'credible_secondary','unverified')",
            name="ck_source_reliability"),
    )


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False, default="count of individuals")

    datasets: Mapped[list["Dataset"]] = relationship(back_populates="metric_definition")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    metric_definition_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    destination_country: Mapped[str] = mapped_column(Text, nullable=False)
    reference_period: Mapped[str] = mapped_column(Text, nullable=False)
    publication_date: Mapped[Optional[date]] = mapped_column(Date)
    original_filename: Mapped[Optional[str]] = mapped_column(Text)
    original_url: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    superseded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("datasets.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    imported_by: Mapped[str] = mapped_column(Text, nullable=False, default="system")
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[Optional[str]] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped["Source"] = relationship(back_populates="datasets")
    metric_definition: Mapped["MetricDefinition"] = relationship(back_populates="datasets")
    observations: Mapped[list["Observation"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    validation_reports: Mapped[list["ValidationReport"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status in ('draft','validated','verified','deprecated')", name="ck_dataset_status"),
        UniqueConstraint("source_id", "destination_country", "reference_period", "metric_definition_id",
                          name="uq_dataset_identity"),
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    destination_country: Mapped[str] = mapped_column(Text, nullable=False)
    institution: Mapped[Optional[str]] = mapped_column(Text)
    discipline: Mapped[Optional[str]] = mapped_column(Text)
    degree_level: Mapped[Optional[str]] = mapped_column(Text)
    value: Mapped[float] = mapped_column(Numeric, nullable=False)
    raw_source_row: Mapped[Optional[int]] = mapped_column(Integer)
    # Added in migration 002 (Phase 3A) -- all nullable, all optional
    nigerian_state: Mapped[Optional[str]] = mapped_column(Text)
    academic_year: Mapped[Optional[str]] = mapped_column(Text)
    gender: Mapped[Optional[str]] = mapped_column(Text)
    funding_type: Mapped[Optional[str]] = mapped_column(Text)
    institution_type: Mapped[Optional[str]] = mapped_column(Text)
    import_batch_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship(back_populates="observations")
    # Added in migration 003 (Phase 3 Change 2)
    characteristics: Mapped[list["ObservationCharacteristic"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )


class ObservationCharacteristic(Base):
    """
    Generic (dimension, value) pairs for a single observation. Stores any
    source breakdown that cannot be pre-anticipated as a fixed schema column:
    mode_of_study, ethnicity, FSM_status, etc.

    Design rules enforced here:
    - UNIQUE (observation_id, dimension): one value per dimension per observation.
      Two counts by gender are two *observations*, not two characteristics.
    - value_source: 'source_raw' when stored as-is, 'normalized' when a
      canonical form was applied (e.g. 'Full-time' -> 'full_time'). The
      original string is preserved in raw_value when normalized.
    - No inference: if the source does not supply a dimension, it is not
      stored here. NULL/absent is the correct representation.

    Relationship to metric_definition_id:
    metric_definition_id defines WHAT is being measured.
    ObservationCharacteristic defines the POPULATION SLICE the count applies to.
    These must never be conflated.
    """
    __tablename__ = "observation_characteristics"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    observation_id: Mapped[int] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_source: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    observation: Mapped["Observation"] = relationship(back_populates="characteristics")

    __table_args__ = (
        CheckConstraint(
            "value_source in ('source_raw','normalized')",
            name="ck_obs_char_value_source",
        ),
        UniqueConstraint("observation_id", "dimension", name="uq_obs_char_obs_dimension"),
    )


class ValidationReport(Base):
    __tablename__ = "validation_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    affected_rows: Mapped[int] = mapped_column(Integer, default=0)

    dataset: Mapped["Dataset"] = relationship(back_populates="validation_reports")

    __table_args__ = (
        CheckConstraint("status in ('pass','warning','fail')", name="ck_validation_status"),
    )


class ProvenanceLog(Base):
    __tablename__ = "provenance_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    dataset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "action in ('registered','imported','validated','verified','deprecated','edited','exported')",
            name="ck_provenance_action"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("role in ('admin','viewer')", name="ck_user_role"),
    )
