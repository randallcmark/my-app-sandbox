from hashlib import sha256
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.artefact import Artefact
from app.db.models.job import Job
from app.db.models.job_artefact_link import JobArtefactLink
from app.db.models.user import User
from app.storage.base import StorageProvider
from app.storage.paths import sanitize_filename
from app.storage.provider import get_storage_provider


def get_user_job_artefact_by_uuid(
    db: Session,
    user: User,
    job: Job,
    artefact_uuid: str,
) -> Artefact | None:
    return db.scalar(
        select(Artefact)
        .outerjoin(
            JobArtefactLink,
            (JobArtefactLink.artefact_id == Artefact.id) & (JobArtefactLink.job_id == job.id),
        )
        .where(
            Artefact.uuid == artefact_uuid,
            Artefact.owner_user_id == user.id,
            (Artefact.job_id == job.id) | (JobArtefactLink.id.is_not(None)),
        )
    )


def get_user_artefact_by_uuid(db: Session, user: User, artefact_uuid: str) -> Artefact | None:
    return db.scalar(
        select(Artefact).where(
            Artefact.uuid == artefact_uuid,
            Artefact.owner_user_id == user.id,
        )
    )


def list_user_artefacts(db: Session, user: User) -> list[Artefact]:
    return list(
        db.scalars(
            select(Artefact)
            .where(Artefact.owner_user_id == user.id)
            .order_by(Artefact.updated_at.desc(), Artefact.created_at.desc())
        )
    )


def list_user_unlinked_artefacts_for_job(db: Session, user: User, job: Job) -> list[Artefact]:
    linked_ids = select(JobArtefactLink.artefact_id).where(
        JobArtefactLink.owner_user_id == user.id,
        JobArtefactLink.job_id == job.id,
    )
    return list(
        db.scalars(
            select(Artefact)
            .where(
                Artefact.owner_user_id == user.id,
                Artefact.id.not_in(linked_ids),
                or_(Artefact.job_id.is_(None), Artefact.job_id != job.id),
            )
            .order_by(Artefact.updated_at.desc(), Artefact.created_at.desc())
        )
    )


def linked_artefacts_for_job(job: Job) -> list[Artefact]:
    artefacts: dict[int, Artefact] = {}
    for artefact in job.artefacts:
        artefacts[artefact.id] = artefact
    for link in job.artefact_links:
        artefacts[link.artefact.id] = link.artefact
    return sorted(artefacts.values(), key=lambda item: item.updated_at, reverse=True)


def update_artefact_metadata(
    artefact: Artefact,
    *,
    kind: str | None = None,
    purpose: str | None = None,
    version_label: str | None = None,
    notes: str | None = None,
    outcome_context: str | None = None,
) -> None:
    if kind is not None:
        artefact.kind = kind.strip() or "other"
    if purpose is not None:
        artefact.purpose = purpose.strip() or None
    if version_label is not None:
        artefact.version_label = version_label.strip() or None
    if notes is not None:
        artefact.notes = notes.strip() or None
    if outcome_context is not None:
        artefact.outcome_context = outcome_context.strip() or None


def link_artefact_to_job(db: Session, user: User, job: Job, artefact: Artefact) -> JobArtefactLink:
    existing = db.scalar(
        select(JobArtefactLink).where(
            JobArtefactLink.owner_user_id == user.id,
            JobArtefactLink.job_id == job.id,
            JobArtefactLink.artefact_id == artefact.id,
        )
    )
    if existing is not None:
        return existing

    link = JobArtefactLink(
        owner_user_id=user.id,
        job_id=job.id,
        artefact_id=artefact.id,
    )
    db.add(link)
    db.flush()
    return link


def store_job_artefact(
    db: Session,
    job: Job,
    *,
    kind: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    storage: StorageProvider | None = None,
) -> Artefact:
    safe_filename = sanitize_filename(filename)
    artefact_kind = kind.strip() or "other"
    storage_key = f"jobs/{job.uuid}/artefacts/{uuid4().hex}-{safe_filename}"
    provider = storage or get_storage_provider()
    stored = provider.save(storage_key, content)

    artefact = Artefact(
        owner_user_id=job.owner_user_id,
        job_id=job.id,
        kind=artefact_kind,
        filename=safe_filename,
        content_type=content_type,
        storage_key=stored.key,
        size_bytes=stored.size_bytes,
        checksum_sha256=sha256(content).hexdigest(),
    )
    db.add(artefact)
    db.flush()
    link_artefact_to_job(db, job.owner, job, artefact)
    return artefact
