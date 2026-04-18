from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class AiProviderSetting(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_provider_settings"

    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner = relationship("User", back_populates="ai_provider_settings")
