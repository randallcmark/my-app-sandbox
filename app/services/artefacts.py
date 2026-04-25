from dataclasses import dataclass
from hashlib import sha256
import io
from pathlib import Path
import shutil
import subprocess
from typing import Iterable
from uuid import uuid4
import zipfile
from xml.etree import ElementTree

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.job_artefact_link import JobArtefactLink
from app.db.models.user import User
from app.storage.base import StorageProvider
from app.storage.local import LocalStorageProvider
from app.storage.paths import resolve_storage_path, sanitize_filename
from app.storage.provider import get_storage_provider


ARTEFACT_KIND_PRIORITY = {
    "resume": 40,
    "cv": 40,
    "cover_letter": 34,
    "supporting_statement": 30,
    "attestation": 28,
    "writing_sample": 28,
    "portfolio": 24,
    "case_study": 24,
    "other": 10,
}

TEXTLIKE_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/markdown",
    "application/json",
}

TEXTLIKE_SUFFIXES = (".txt", ".md", ".markdown", ".json")
DOCXLIKE_SUFFIXES = (".docx",)
TEXTUTIL_SUFFIXES = (".doc", ".rtf", ".odt")
PDF_SUFFIXES = (".pdf",)
PROVIDER_DOCUMENT_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/rtf",
    "text/rtf",
    "application/vnd.oasis.opendocument.text",
}


@dataclass(frozen=True)
class ArtefactCandidateSummary:
    artefact_uuid: str
    filename: str
    kind: str
    purpose: str | None
    version_label: str | None
    notes: str | None
    outcome_context: str | None
    is_linked_to_current_job: bool
    linked_job_count: int
    linked_interview_count: int
    linked_offer_count: int
    linked_rejection_count: int
    linked_active_count: int
    metadata_quality: str
    score: int
    summary_text: str


def _related_jobs_for_artefact(artefact: Artefact) -> list[Job]:
    jobs: dict[int, Job] = {}
    if artefact.job is not None:
        jobs[artefact.job.id] = artefact.job
    for link in artefact.job_links:
        if link.job is not None:
            jobs[link.job.id] = link.job
    if artefact.application is not None and artefact.application.job is not None:
        jobs[artefact.application.job.id] = artefact.application.job
    if artefact.interview_event is not None and artefact.interview_event.job is not None:
        jobs[artefact.interview_event.job.id] = artefact.interview_event.job
    return list(jobs.values())


def _status_counts(jobs: Iterable[Job]) -> tuple[int, int, int, int]:
    interview_like = 0
    offer_like = 0
    rejection_like = 0
    active_like = 0
    for job in jobs:
        status = (job.status or "").strip().lower()
        if status == "offer":
            offer_like += 1
        elif status == "interviewing":
            interview_like += 1
        elif status in {"rejected", "archived"}:
            rejection_like += 1
        elif status in {"saved", "interested", "preparing", "applied"}:
            active_like += 1
    return interview_like, offer_like, rejection_like, active_like


def _artefact_score(
    artefact: Artefact,
    *,
    current_job: Job,
    linked_jobs: list[Job],
    interview_like: int,
    offer_like: int,
    rejection_like: int,
    active_like: int,
) -> int:
    score = ARTEFACT_KIND_PRIORITY.get((artefact.kind or "other").strip().lower(), 12)
    if any(job.id == current_job.id for job in linked_jobs):
        score += 60
    if artefact.purpose:
        score += 10
    if artefact.version_label:
        score += 4
    if artefact.notes:
        score += 4
    if artefact.outcome_context:
        score += 6
    score += min(len(linked_jobs), 4) * 3
    score += interview_like * 8
    score += offer_like * 12
    score += active_like * 2
    score -= rejection_like * 2
    return score


def _metadata_gaps(artefact: Artefact, linked_jobs: list[Job]) -> list[str]:
    gaps: list[str] = []
    if not artefact.purpose:
        gaps.append("purpose")
    if not artefact.version_label:
        gaps.append("version")
    if not artefact.notes:
        gaps.append("notes")
    if not artefact.outcome_context:
        gaps.append("outcome context")
    if not linked_jobs:
        gaps.append("linked history")
    return gaps


def _metadata_quality_label(gaps: list[str]) -> str:
    if len(gaps) <= 1:
        return "strong"
    if len(gaps) <= 3:
        return "moderate"
    return "thin"


def summarise_artefact_for_ai(artefact: Artefact, *, current_job: Job) -> ArtefactCandidateSummary:
    linked_jobs = _related_jobs_for_artefact(artefact)
    interview_like, offer_like, rejection_like, active_like = _status_counts(linked_jobs)
    is_linked_to_current_job = any(job.id == current_job.id for job in linked_jobs)
    metadata_gaps = _metadata_gaps(artefact, linked_jobs)
    metadata_quality = _metadata_quality_label(metadata_gaps)
    score = _artefact_score(
        artefact,
        current_job=current_job,
        linked_jobs=linked_jobs,
        interview_like=interview_like,
        offer_like=offer_like,
        rejection_like=rejection_like,
        active_like=active_like,
    )
    recent_titles = ", ".join(job.title for job in linked_jobs[:3] if job.title)
    summary_bits = [
        f"Kind: {artefact.kind}",
        f"Filename: {artefact.filename}",
        f"Purpose: {artefact.purpose or 'Not set'}",
        f"Version: {artefact.version_label or 'Not set'}",
        f"Outcome context: {artefact.outcome_context or 'Not set'}",
        f"Linked jobs: {len(linked_jobs)}",
        f"Interview-linked jobs: {interview_like}",
        f"Offer-linked jobs: {offer_like}",
        f"Rejected/archived-linked jobs: {rejection_like}",
        f"Active-linked jobs: {active_like}",
        f"Metadata quality: {metadata_quality}",
        f"Already linked to current job: {'yes' if is_linked_to_current_job else 'no'}",
    ]
    if metadata_gaps:
        summary_bits.append("Missing metadata: " + ", ".join(metadata_gaps))
    if recent_titles:
        summary_bits.append(f"Recent linked job titles: {recent_titles}")
    if artefact.notes:
        summary_bits.append(f"Notes: {artefact.notes}")
    return ArtefactCandidateSummary(
        artefact_uuid=artefact.uuid,
        filename=artefact.filename,
        kind=artefact.kind,
        purpose=artefact.purpose,
        version_label=artefact.version_label,
        notes=artefact.notes,
        outcome_context=artefact.outcome_context,
        is_linked_to_current_job=is_linked_to_current_job,
        linked_job_count=len(linked_jobs),
        linked_interview_count=interview_like,
        linked_offer_count=offer_like,
        linked_rejection_count=rejection_like,
        linked_active_count=active_like,
        metadata_quality=metadata_quality,
        score=score,
        summary_text=" | ".join(summary_bits),
    )


def list_candidate_artefacts_for_job(
    db: Session,
    user: User,
    job: Job,
    *,
    limit: int = 5,
) -> list[ArtefactCandidateSummary]:
    artefacts = list(
        db.scalars(
            select(Artefact)
            .where(Artefact.owner_user_id == user.id)
            .options(
                selectinload(Artefact.job),
                selectinload(Artefact.application).selectinload(Application.job),
                selectinload(Artefact.interview_event).selectinload(InterviewEvent.job),
                selectinload(Artefact.job_links).selectinload(JobArtefactLink.job),
            )
            .order_by(Artefact.updated_at.desc(), Artefact.created_at.desc())
        )
    )
    summaries = [summarise_artefact_for_ai(artefact, current_job=job) for artefact in artefacts]
    summaries.sort(
        key=lambda item: (
            item.score,
            item.linked_offer_count,
            item.linked_interview_count,
            item.linked_job_count,
            item.filename.lower(),
        ),
        reverse=True,
    )
    return summaries[: max(limit, 0)]


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


def _clip_text(text: str, *, max_chars: int) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 16].rstrip() + "\n\n[truncated]"


def _extract_docx_text(raw: bytes) -> str | None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    with archive:
        try:
            document_xml = archive.read("word/document.xml")
        except KeyError:
            return None
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return None
    text_parts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    return "\n".join(part.strip() for part in text_parts if part and part.strip()) or None


def _local_storage_path(artefact: Artefact, provider: StorageProvider) -> Path | None:
    if not isinstance(provider, LocalStorageProvider):
        return None
    try:
        return resolve_storage_path(provider.root, artefact.storage_key)
    except Exception:
        return None


def _extract_with_textutil(path: Path) -> str | None:
    if shutil.which("textutil") is None:
        return None
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _extract_pdf_text(path: Path) -> str | None:
    if shutil.which("mdls") is None:
        return None
    result = subprocess.run(
        ["mdls", "-name", "kMDItemTextContent", "-raw", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text or text == "(null)":
        return None
    return text


def load_artefact_text_excerpt(
    artefact: Artefact,
    *,
    storage: StorageProvider | None = None,
    max_chars: int = 4000,
) -> str | None:
    content_type = (artefact.content_type or "").strip().lower()
    filename = (artefact.filename or "").strip().lower()
    is_textlike = content_type in TEXTLIKE_CONTENT_TYPES or filename.endswith(TEXTLIKE_SUFFIXES)
    provider = storage or get_storage_provider()
    if is_textlike:
        try:
            raw = provider.load(artefact.storage_key)
        except FileNotFoundError:
            return None
        return _clip_text(raw.decode("utf-8", errors="ignore"), max_chars=max_chars)

    if filename.endswith(DOCXLIKE_SUFFIXES):
        try:
            raw = provider.load(artefact.storage_key)
        except FileNotFoundError:
            return None
        return _clip_text(_extract_docx_text(raw) or "", max_chars=max_chars)

    local_path = _local_storage_path(artefact, provider)
    if local_path is None:
        return None

    if filename.endswith(TEXTUTIL_SUFFIXES):
        return _clip_text(_extract_with_textutil(local_path) or "", max_chars=max_chars)

    if filename.endswith(PDF_SUFFIXES):
        return _clip_text(_extract_pdf_text(local_path) or "", max_chars=max_chars)

    return None


def load_artefact_document_payload(
    artefact: Artefact,
    *,
    storage: StorageProvider | None = None,
    max_bytes: int = 10 * 1024 * 1024,
) -> tuple[str, bytes] | None:
    content_type = (artefact.content_type or "").strip().lower()
    filename = (artefact.filename or "").strip().lower()
    inferred_type = content_type
    if not inferred_type:
        if filename.endswith(PDF_SUFFIXES):
            inferred_type = "application/pdf"
        elif filename.endswith(DOCXLIKE_SUFFIXES):
            inferred_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif filename.endswith(".doc"):
            inferred_type = "application/msword"
        elif filename.endswith(".rtf"):
            inferred_type = "application/rtf"
        elif filename.endswith(".odt"):
            inferred_type = "application/vnd.oasis.opendocument.text"
    if inferred_type not in PROVIDER_DOCUMENT_CONTENT_TYPES:
        return None

    provider = storage or get_storage_provider()
    try:
        raw = provider.load(artefact.storage_key)
    except FileNotFoundError:
        return None
    if not raw or len(raw) > max_bytes:
        return None
    return inferred_type, raw


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
