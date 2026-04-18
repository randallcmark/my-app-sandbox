from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class AiOutput(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_outputs"

    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=True)
    artefact_id: Mapped[int | None] = mapped_column(
        ForeignKey("artefacts.id"), index=True, nullable=True
    )
    output_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True, nullable=False)

    owner = relationship("User", back_populates="ai_outputs")
    job = relationship("Job", back_populates="ai_outputs")
    artefact = relationship("Artefact", back_populates="ai_outputs")
