from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class JobArtefactLink(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_artefact_links"

    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=False)
    artefact_id: Mapped[int] = mapped_column(ForeignKey("artefacts.id"), index=True, nullable=False)

    owner = relationship("User", back_populates="job_artefact_links")
    job = relationship("Job", back_populates="artefact_links")
    artefact = relationship("Artefact", back_populates="job_links")

    __table_args__ = (
        UniqueConstraint("job_id", "artefact_id", name="uq_job_artefact_links_job_artefact"),
    )
