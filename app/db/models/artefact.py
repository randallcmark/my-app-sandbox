from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Artefact(IdMixin, TimestampMixin, Base):
    __tablename__ = "artefacts"

    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=True
    )
    interview_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("interview_events.id"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    owner = relationship("User", back_populates="artefacts")
    job = relationship("Job", back_populates="artefacts")
    application = relationship("Application", back_populates="artefacts")
    interview_event = relationship("InterviewEvent", back_populates="artefacts")

