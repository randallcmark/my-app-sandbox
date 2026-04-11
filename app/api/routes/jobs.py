from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DbSession, get_current_user
from app.api.ownership import require_owner
from app.db.models.job import Job
from app.db.models.user import User
from app.services.jobs import (
    JOB_STATUSES,
    BoardOrderValidationError,
    get_user_job_by_uuid,
    list_user_jobs,
    update_job_board_state,
    update_user_board_order,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    title: str
    company: str | None
    status: str
    board_position: int
    source: str | None
    source_url: str | None
    apply_url: str | None
    location: str | None
    remote_policy: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    description_raw: str | None
    captured_at: datetime | None
    archived_at: datetime | None


class JobBoardUpdateRequest(BaseModel):
    status: str | None = None
    board_position: int | None = Field(default=None, ge=0)


class JobBoardOrderRequest(BaseModel):
    columns: dict[str, list[str]]


def _validate_status(job_status: str | None) -> None:
    if job_status is not None and job_status not in JOB_STATUSES:
        allowed = ", ".join(JOB_STATUSES)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported job status. Allowed values: {allowed}",
        )


@router.get("", response_model=list[JobResponse])
def list_jobs(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    include_archived: bool = False,
    job_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[Job]:
    _validate_status(job_status)
    return list_user_jobs(
        db,
        current_user,
        include_archived=include_archived,
        status=job_status,
    )


@router.patch("/board", response_model=list[JobResponse])
def update_board_order(
    payload: JobBoardOrderRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[Job]:
    try:
        jobs = update_user_board_order(db, current_user, payload.columns)
    except BoardOrderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    return jobs


@router.get("/{job_uuid}", response_model=JobResponse)
def get_job(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Job:
    return require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)


@router.patch("/{job_uuid}/board", response_model=JobResponse)
def update_job_board(
    job_uuid: str,
    payload: JobBoardUpdateRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Job:
    if payload.status is None and payload.board_position is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide status or board_position",
        )

    _validate_status(payload.status)
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    update_job_board_state(
        job,
        status=payload.status,
        board_position=payload.board_position,
    )
    db.commit()
    return job
