from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Communication(IdMixin, TimestampMixin, Base):
    __tablename__ = "communications"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=False)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=True
    )
    interview_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("interview_events.id"), index=True, nullable=True
    )
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), default="note", index=True, nullable=False)
    direction: Mapped[str | None] = mapped_column(String(50), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    job = relationship("Job", back_populates="communications")
    application = relationship("Application", back_populates="communications")
    interview_event = relationship("InterviewEvent", back_populates="communications")
    owner = relationship("User", back_populates="communications")

