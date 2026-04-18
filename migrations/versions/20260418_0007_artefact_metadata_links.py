"""add artefact metadata and reusable job links

Revision ID: 20260418_0007
Revises: 20260418_0006
Create Date: 2026-04-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260418_0007"
down_revision: str | None = "20260418_0006"
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
    with op.batch_alter_table("artefacts") as batch_op:
        batch_op.add_column(sa.Column("purpose", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("version_label", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("outcome_context", sa.String(length=300), nullable=True))

    op.create_table(
        "job_artefact_links",
        *base_columns(),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("artefact_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["artefact_id"], ["artefacts.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.UniqueConstraint("job_id", "artefact_id", name="uq_job_artefact_links_job_artefact"),
    )
    op.create_index(op.f("ix_job_artefact_links_uuid"), "job_artefact_links", ["uuid"], unique=True)
    op.create_index(
        op.f("ix_job_artefact_links_owner_user_id"), "job_artefact_links", ["owner_user_id"]
    )
    op.create_index(op.f("ix_job_artefact_links_job_id"), "job_artefact_links", ["job_id"])
    op.create_index(
        op.f("ix_job_artefact_links_artefact_id"), "job_artefact_links", ["artefact_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_job_artefact_links_artefact_id"), table_name="job_artefact_links")
    op.drop_index(op.f("ix_job_artefact_links_job_id"), table_name="job_artefact_links")
    op.drop_index(op.f("ix_job_artefact_links_owner_user_id"), table_name="job_artefact_links")
    op.drop_index(op.f("ix_job_artefact_links_uuid"), table_name="job_artefact_links")
    op.drop_table("job_artefact_links")

    with op.batch_alter_table("artefacts") as batch_op:
        batch_op.drop_column("outcome_context")
        batch_op.drop_column("notes")
        batch_op.drop_column("version_label")
        batch_op.drop_column("purpose")
