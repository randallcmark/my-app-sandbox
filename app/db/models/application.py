from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="preparing", index=True, nullable=False)
    channel: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_comp: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    job = relationship("Job", back_populates="applications")
    owner = relationship("User", back_populates="applications")
    interviews = relationship("InterviewEvent", back_populates="application")
    communications = relationship("Communication", back_populates="application")
    artefacts = relationship("Artefact", back_populates="application")

