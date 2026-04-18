from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ai_output import AiOutput
from app.db.models.ai_provider_setting import AiProviderSetting
from app.db.models.user import User

KNOWN_PROVIDERS = ("openai", "anthropic", "openai_compatible")
KNOWN_OUTPUT_TYPES = (
    "recommendation",
    "fit_summary",
    "draft",
    "profile_observation",
    "artefact_suggestion",
)


def list_user_ai_provider_settings(db: Session, user: User) -> list[AiProviderSetting]:
    return list(
        db.scalars(
            select(AiProviderSetting)
            .where(AiProviderSetting.owner_user_id == user.id)
            .order_by(AiProviderSetting.provider, AiProviderSetting.created_at)
        )
    )


def upsert_ai_provider_setting(
    db: Session,
    user: User,
    *,
    provider: str,
    label: str | None = None,
    base_url: str | None = None,
    model_name: str | None = None,
    is_enabled: bool = False,
) -> AiProviderSetting:
    if provider not in KNOWN_PROVIDERS:
        raise ValueError("Unsupported AI provider")
    setting = db.scalar(
        select(AiProviderSetting).where(
            AiProviderSetting.owner_user_id == user.id,
            AiProviderSetting.provider == provider,
        )
    )
    if setting is None:
        setting = AiProviderSetting(owner_user_id=user.id, provider=provider)
        db.add(setting)
    setting.label = (label or "").strip() or None
    setting.base_url = (base_url or "").strip() or None
    setting.model_name = (model_name or "").strip() or None
    setting.is_enabled = is_enabled
    db.flush()
    return setting


def list_user_ai_outputs(db: Session, user: User) -> list[AiOutput]:
    return list(
        db.scalars(
            select(AiOutput)
            .where(AiOutput.owner_user_id == user.id)
            .order_by(AiOutput.updated_at.desc(), AiOutput.created_at.desc())
        )
    )
