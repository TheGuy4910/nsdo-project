"""
CRUD functions: the only place in the app that touches the ORM session
directly for sources and datasets. Routers call these; they never build
SQLAlchemy queries themselves.
"""

from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.models.models import Source, Dataset, Observation, User
from app import schemas
from app.services.validation import can_delete_dataset, can_delete_source


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


# ---------- Sources ----------

def get_source(db: Session, source_id: int) -> Source:
    obj = db.get(Source, source_id)
    if obj is None:
        raise NotFoundError(f"Source {source_id} not found")
    return obj


def list_sources(db: Session, reliability_tier: Optional[str] = None) -> list[Source]:
    q = db.query(Source)
    if reliability_tier:
        q = q.filter(Source.reliability_tier == reliability_tier)
    return q.order_by(Source.name).all()


def create_source(db: Session, payload: schemas.SourceCreate) -> Source:
    obj = Source(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ConflictError(f"Source with short_code '{payload.short_code}' already exists") from e
    db.refresh(obj)
    return obj


def update_source(db: Session, source_id: int, payload: schemas.SourceUpdate) -> Source:
    obj = get_source(db, source_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(obj, field, value)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ConflictError(str(e.orig)) from e
    db.refresh(obj)
    return obj


def delete_source(db: Session, source_id: int) -> None:
    obj = get_source(db, source_id)
    referencing = db.query(Dataset).filter(Dataset.source_id == source_id).count()
    ok, message = can_delete_source(referencing)
    if not ok:
        raise ConflictError(message)
    db.delete(obj)
    db.commit()


# ---------- Datasets ----------

def get_dataset(db: Session, dataset_id: int) -> Dataset:
    obj = (
        db.query(Dataset)
        .options(joinedload(Dataset.source), joinedload(Dataset.metric_definition))
        .filter(Dataset.id == dataset_id)
        .first()
    )
    if obj is None:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return obj


def list_datasets(
    db: Session,
    source_id: Optional[int] = None,
    destination_country: Optional[str] = None,
    reference_period: Optional[str] = None,
    metric_definition_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Dataset]:
    q = db.query(Dataset).options(joinedload(Dataset.source), joinedload(Dataset.metric_definition))
    if source_id is not None:
        q = q.filter(Dataset.source_id == source_id)
    if destination_country is not None:
        q = q.filter(Dataset.destination_country == destination_country)
    if reference_period is not None:
        q = q.filter(Dataset.reference_period == reference_period)
    if metric_definition_id is not None:
        q = q.filter(Dataset.metric_definition_id == metric_definition_id)
    if status is not None:
        q = q.filter(Dataset.status == status)
    return q.order_by(Dataset.destination_country, Dataset.reference_period).offset(skip).limit(limit).all()


def create_dataset(db: Session, payload: schemas.DatasetCreate) -> Dataset:
    if db.get(Source, payload.source_id) is None:
        raise NotFoundError(f"source_id {payload.source_id} does not exist")
    from app.models.models import MetricDefinition
    if db.get(MetricDefinition, payload.metric_definition_id) is None:
        raise NotFoundError(f"metric_definition_id {payload.metric_definition_id} does not exist")

    obj = Dataset(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ConflictError(
            "A dataset already exists for this exact "
            "(source, destination_country, reference_period, metric_definition) "
            "combination. Register a new revision only if the content genuinely "
            "differs, and link it via superseded_by_id -- do not edit the existing one."
        ) from e
    db.refresh(obj)
    return get_dataset(db, obj.id)


def update_dataset(db: Session, dataset_id: int, payload: schemas.DatasetUpdate) -> Dataset:
    obj = get_dataset(db, dataset_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(obj, field, value)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ConflictError(str(e.orig)) from e
    db.refresh(obj)
    return get_dataset(db, dataset_id)


def delete_dataset(db: Session, dataset_id: int) -> None:
    obj = get_dataset(db, dataset_id)
    observation_count = db.query(Observation).filter(Observation.dataset_id == dataset_id).count()
    ok, message = can_delete_dataset(obj.status, observation_count)
    if not ok:
        raise ConflictError(message)
    db.delete(obj)
    db.commit()


# ---------- Observations (read-only from the API perspective) ----------

def list_observations(
    db: Session,
    dataset_id: Optional[int] = None,
    destination_country: Optional[str] = None,
    skip: int = 0,
    limit: int = 500,
) -> list:
    q = db.query(Observation)
    if dataset_id is not None:
        q = q.filter(Observation.dataset_id == dataset_id)
    if destination_country is not None:
        q = q.filter(Observation.destination_country == destination_country)
    return q.order_by(Observation.id).offset(skip).limit(limit).all()


# ---------- Users (Phase 6) ----------

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def count_users(db: Session) -> int:
    return db.query(User).count()


def create_user(db: Session, username: str, password_hash: str, role: str, email: str | None = None) -> User:
    user = User(username=username, password_hash=password_hash, role=role, email=email)    db.add(user)
    db.commit()
    db.refresh(user)
    return user
