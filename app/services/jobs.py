from datetime import UTC, datetime

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
    return sorted(jobs, key=lambda job: (_STATUS_ORDER.get(job.status, len(_STATUS_ORDER)), job.board_position))


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
