from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    jobs = relationship("Job", back_populates="owner")
    applications = relationship("Application", back_populates="owner")
    interviews = relationship("InterviewEvent", back_populates="owner")
    communications = relationship("Communication", back_populates="owner")
    artefacts = relationship("Artefact", back_populates="owner")
    job_artefact_links = relationship("JobArtefactLink", back_populates="owner")
    api_tokens = relationship("ApiToken", back_populates="owner")
    auth_sessions = relationship("AuthSession", back_populates="user")
    profile = relationship("UserProfile", back_populates="owner", uselist=False)
    email_intakes = relationship("EmailIntake", back_populates="owner")
    ai_provider_settings = relationship("AiProviderSetting", back_populates="owner")
    ai_outputs = relationship("AiOutput", back_populates="owner")
