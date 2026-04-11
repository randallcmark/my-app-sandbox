from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job


def schedule_interview(
    db: Session,
    job: Job,
    *,
    stage: str,
    scheduled_at: datetime | None = None,
    location: str | None = None,
    participants: str | None = None,
    notes: str | None = None,
) -> tuple[InterviewEvent, Communication]:
    timestamp = datetime.now(UTC)
    interview = InterviewEvent(
        job_id=job.id,
        owner_user_id=job.owner_user_id,
        stage=stage.strip(),
        scheduled_at=scheduled_at,
        location=location.strip() if location else None,
        participants=participants.strip() if participants else None,
        notes=notes.strip() if notes else None,
    )
    db.add(interview)
    db.flush()

    when = scheduled_at.strftime("%Y-%m-%d %H:%M") if scheduled_at else "time pending"
    event = Communication(
        job_id=job.id,
        interview_event_id=interview.id,
        owner_user_id=job.owner_user_id,
        event_type="interview",
        direction="inbound",
        occurred_at=timestamp,
        subject=f"Interview scheduled: {interview.stage}",
        notes=notes.strip() if notes else f"Interview scheduled for {when}.",
    )
    db.add(event)
    db.flush()
    return interview, event
