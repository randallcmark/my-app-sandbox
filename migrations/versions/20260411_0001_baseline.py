"""baseline schema

Revision ID: 20260411_0001
Revises:
Create Date: 2026-04-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260411_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def create_uuid_index(table_name: str) -> None:
    op.create_index(op.f(f"ix_{table_name}_uuid"), table_name, ["uuid"], unique=True)


def upgrade() -> None:
    op.create_table(
        "users",
        *base_columns(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("email"),
    )
    create_uuid_index("users")
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "jobs",
        *base_columns(),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("company", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("board_position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("apply_url", sa.String(length=2048), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("remote_policy", sa.String(length=50), nullable=True),
        sa.Column("salary_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("salary_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("description_raw", sa.Text(), nullable=True),
        sa.Column("description_clean", sa.Text(), nullable=True),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    create_uuid_index("jobs")
    op.create_index(op.f("ix_jobs_owner_user_id"), "jobs", ["owner_user_id"])
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"])

    op.create_table(
        "applications",
        *base_columns(),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_comp", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    create_uuid_index("applications")
    op.create_index(op.f("ix_applications_job_id"), "applications", ["job_id"])
    op.create_index(op.f("ix_applications_owner_user_id"), "applications", ["owner_user_id"])
    op.create_index(op.f("ix_applications_status"), "applications", ["status"])

    op.create_table(
        "interview_events",
        *base_columns(),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("participants", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    create_uuid_index("interview_events")
    op.create_index(op.f("ix_interview_events_application_id"), "interview_events", ["application_id"])
    op.create_index(op.f("ix_interview_events_job_id"), "interview_events", ["job_id"])
    op.create_index(op.f("ix_interview_events_owner_user_id"), "interview_events", ["owner_user_id"])

    op.create_table(
        "communications",
        *base_columns(),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("interview_event_id", sa.Integer(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=50), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["interview_event_id"], ["interview_events.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    create_uuid_index("communications")
    op.create_index(op.f("ix_communications_application_id"), "communications", ["application_id"])
    op.create_index(op.f("ix_communications_event_type"), "communications", ["event_type"])
    op.create_index(op.f("ix_communications_interview_event_id"), "communications", ["interview_event_id"])
    op.create_index(op.f("ix_communications_job_id"), "communications", ["job_id"])
    op.create_index(op.f("ix_communications_owner_user_id"), "communications", ["owner_user_id"])

    op.create_table(
        "artefacts",
        *base_columns(),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("interview_event_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["interview_event_id"], ["interview_events.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    create_uuid_index("artefacts")
    op.create_index(op.f("ix_artefacts_application_id"), "artefacts", ["application_id"])
    op.create_index(op.f("ix_artefacts_interview_event_id"), "artefacts", ["interview_event_id"])
    op.create_index(op.f("ix_artefacts_job_id"), "artefacts", ["job_id"])
    op.create_index(op.f("ix_artefacts_owner_user_id"), "artefacts", ["owner_user_id"])

    op.create_table(
        "api_tokens",
        *base_columns(),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.String(length=500), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.UniqueConstraint("token_hash"),
    )
    create_uuid_index("api_tokens")
    op.create_index(op.f("ix_api_tokens_owner_user_id"), "api_tokens", ["owner_user_id"])
    op.create_index(op.f("ix_api_tokens_token_hash"), "api_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_api_tokens_token_hash"), table_name="api_tokens")
    op.drop_index(op.f("ix_api_tokens_owner_user_id"), table_name="api_tokens")
    op.drop_index(op.f("ix_api_tokens_uuid"), table_name="api_tokens")
    op.drop_table("api_tokens")

    op.drop_index(op.f("ix_artefacts_owner_user_id"), table_name="artefacts")
    op.drop_index(op.f("ix_artefacts_job_id"), table_name="artefacts")
    op.drop_index(op.f("ix_artefacts_interview_event_id"), table_name="artefacts")
    op.drop_index(op.f("ix_artefacts_application_id"), table_name="artefacts")
    op.drop_index(op.f("ix_artefacts_uuid"), table_name="artefacts")
    op.drop_table("artefacts")

    op.drop_index(op.f("ix_communications_owner_user_id"), table_name="communications")
    op.drop_index(op.f("ix_communications_job_id"), table_name="communications")
    op.drop_index(op.f("ix_communications_interview_event_id"), table_name="communications")
    op.drop_index(op.f("ix_communications_event_type"), table_name="communications")
    op.drop_index(op.f("ix_communications_application_id"), table_name="communications")
    op.drop_index(op.f("ix_communications_uuid"), table_name="communications")
    op.drop_table("communications")

    op.drop_index(op.f("ix_interview_events_owner_user_id"), table_name="interview_events")
    op.drop_index(op.f("ix_interview_events_job_id"), table_name="interview_events")
    op.drop_index(op.f("ix_interview_events_application_id"), table_name="interview_events")
    op.drop_index(op.f("ix_interview_events_uuid"), table_name="interview_events")
    op.drop_table("interview_events")

    op.drop_index(op.f("ix_applications_status"), table_name="applications")
    op.drop_index(op.f("ix_applications_owner_user_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_job_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_uuid"), table_name="applications")
    op.drop_table("applications")

    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_owner_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_uuid"), table_name="jobs")
    op.drop_table("jobs")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_uuid"), table_name="users")
    op.drop_table("users")

