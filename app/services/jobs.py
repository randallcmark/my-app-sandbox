from datetime import UTC, datetime

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.job import Job
from app.db.models.user import User

JOB_STATUSES = (
    "saved",
    "interested",
    "preparing",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "archived",
)

BOARD_STATUSES = tuple(status for status in JOB_STATUSES if status != "archived")
_STATUS_ORDER = {status: index for index, status in enumerate(JOB_STATUSES)}


def list_user_jobs(
    db: Session,
    user: User,
    *,
    include_archived: bool = False,
    status: str | None = None,
) -> list[Job]:
    statement = select(Job).where(Job.owner_user_id == user.id)
    if status is not None:
        statement = statement.where(Job.status == status)
    elif not include_archived:
        statement = statement.where(Job.status != "archived")

    statement = statement.order_by(Job.board_position, Job.created_at)
    jobs = list(db.scalars(statement).all())
    return sorted(
        jobs,
        key=lambda job: (_STATUS_ORDER.get(job.status, len(_STATUS_ORDER)), job.board_position),
    )


def get_user_job_by_uuid(db: Session, user: User, job_uuid: str) -> Job | None:
    return db.scalar(
        select(Job).where(
            Job.uuid == job_uuid,
            Job.owner_user_id == user.id,
        )
    )


def update_job_board_state(
    job: Job,
    *,
    status: str | None = None,
    board_position: int | None = None,
) -> Job:
    if status is not None:
        job.status = status
        if status == "archived" and job.archived_at is None:
            job.archived_at = datetime.now(UTC)
        elif status != "archived":
            job.archived_at = None

    if board_position is not None:
        job.board_position = board_position

    return job


class BoardOrderValidationError(ValueError):
    pass


def update_user_board_order(
    db: Session,
    user: User,
    columns: Mapping[str, Sequence[str]],
) -> list[Job]:
    unknown_statuses = set(columns) - set(BOARD_STATUSES)
    if unknown_statuses:
        unknown = ", ".join(sorted(unknown_statuses))
        raise BoardOrderValidationError(f"Unsupported board status: {unknown}")

    requested_uuids = [job_uuid for job_uuids in columns.values() for job_uuid in job_uuids]
    if len(requested_uuids) != len(set(requested_uuids)):
        raise BoardOrderValidationError("A job can appear only once in a board update")

    if not requested_uuids:
        return []

    jobs = list(
        db.scalars(
            select(Job).where(
                Job.owner_user_id == user.id,
                Job.uuid.in_(requested_uuids),
            )
        ).all()
    )
    jobs_by_uuid = {job.uuid: job for job in jobs}
    missing_uuids = set(requested_uuids) - set(jobs_by_uuid)
    if missing_uuids:
        raise BoardOrderValidationError("Board update contains unknown jobs")

    updated_jobs = []
    for job_status, job_uuids in columns.items():
        for position, job_uuid in enumerate(job_uuids):
            job = jobs_by_uuid[job_uuid]
            update_job_board_state(job, status=job_status, board_position=position)
            updated_jobs.append(job)

    db.flush()
    return updated_jobs
