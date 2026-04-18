"""add ai readiness records

Revision ID: 20260418_0008
Revises: 20260418_0007
Create Date: 2026-04-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260418_0008"
down_revision: str | None = "20260418_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_provider_settings",
        *base_columns(),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(op.f("ix_ai_provider_settings_uuid"), "ai_provider_settings", ["uuid"], unique=True)
    op.create_index(
        op.f("ix_ai_provider_settings_owner_user_id"),
        "ai_provider_settings",
        ["owner_user_id"],
    )

    op.create_table(
        "ai_outputs",
        *base_columns(),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("artefact_id", sa.Integer(), nullable=True),
        sa.Column("output_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_context", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["artefact_id"], ["artefacts.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(op.f("ix_ai_outputs_uuid"), "ai_outputs", ["uuid"], unique=True)
    op.create_index(op.f("ix_ai_outputs_owner_user_id"), "ai_outputs", ["owner_user_id"])
    op.create_index(op.f("ix_ai_outputs_job_id"), "ai_outputs", ["job_id"])
    op.create_index(op.f("ix_ai_outputs_artefact_id"), "ai_outputs", ["artefact_id"])
    op.create_index(op.f("ix_ai_outputs_output_type"), "ai_outputs", ["output_type"])
    op.create_index(op.f("ix_ai_outputs_status"), "ai_outputs", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_outputs_status"), table_name="ai_outputs")
    op.drop_index(op.f("ix_ai_outputs_output_type"), table_name="ai_outputs")
    op.drop_index(op.f("ix_ai_outputs_artefact_id"), table_name="ai_outputs")
    op.drop_index(op.f("ix_ai_outputs_job_id"), table_name="ai_outputs")
    op.drop_index(op.f("ix_ai_outputs_owner_user_id"), table_name="ai_outputs")
    op.drop_index(op.f("ix_ai_outputs_uuid"), table_name="ai_outputs")
    op.drop_table("ai_outputs")

    op.drop_index(op.f("ix_ai_provider_settings_owner_user_id"), table_name="ai_provider_settings")
    op.drop_index(op.f("ix_ai_provider_settings_uuid"), table_name="ai_provider_settings")
    op.drop_table("ai_provider_settings")
