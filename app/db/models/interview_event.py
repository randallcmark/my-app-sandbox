from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class InterviewEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_events"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=False)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=True
    )
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    participants: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(100), nullable=True)

    job = relationship("Job", back_populates="interviews")
    application = relationship("Application", back_populates="interviews")
    owner = relationship("User", back_populates="interviews")
    communications = relationship("Communication", back_populates="interview_event")
    artefacts = relationship("Artefact", back_populates="interview_event")

