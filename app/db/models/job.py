from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    email_intake_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_intakes.id"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="saved", index=True, nullable=False)
    board_position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intake_source: Mapped[str] = mapped_column(String(100), default="manual", index=True, nullable=False)
    intake_confidence: Mapped[str] = mapped_column(String(50), default="high", index=True, nullable=False)
    intake_state: Mapped[str] = mapped_column(String(50), default="accepted", index=True, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    apply_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    remote_policy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    description_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_clean: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="jobs")
    email_intake = relationship("EmailIntake", back_populates="jobs")
    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")
    interviews = relationship("InterviewEvent", back_populates="job", cascade="all, delete-orphan")
    communications = relationship("Communication", back_populates="job", cascade="all, delete-orphan")
    artefacts = relationship("Artefact", back_populates="job", cascade="all, delete-orphan")
    artefact_links = relationship(
        "JobArtefactLink", back_populates="job", cascade="all, delete-orphan"
    )
    ai_outputs = relationship("AiOutput", back_populates="job")
