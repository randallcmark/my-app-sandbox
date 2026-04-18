from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ai_output import AiOutput
from app.db.models.ai_provider_setting import AiProviderSetting
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.email_intake import EmailIntake
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.job_artefact_link import JobArtefactLink
from app.db.models.user import User
from app.db.models.user_profile import UserProfile


def run_migrations(database_url: str) -> None:
    get_settings.cache_clear()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    get_settings.cache_clear()


def test_baseline_migration_creates_core_tables(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    run_migrations(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert {
        "alembic_version",
        "ai_outputs",
        "ai_provider_settings",
        "api_tokens",
        "applications",
        "artefacts",
        "auth_sessions",
        "communications",
        "email_intakes",
        "interview_events",
        "job_artefact_links",
        "jobs",
        "user_profiles",
        "users",
    }.issubset(tables)

    communication_columns = {column["name"] for column in inspector.get_columns("communications")}
    assert "follow_up_at" in communication_columns

    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    assert {"email_intake_id", "intake_source", "intake_confidence", "intake_state"}.issubset(
        job_columns
    )

    email_intake_columns = {column["name"] for column in inspector.get_columns("email_intakes")}
    assert {
        "owner_user_id",
        "subject",
        "sender",
        "received_at",
        "body_text",
        "body_html",
        "source_provider",
    }.issubset(email_intake_columns)

    artefact_columns = {column["name"] for column in inspector.get_columns("artefacts")}
    assert {"purpose", "version_label", "notes", "outcome_context"}.issubset(artefact_columns)

    job_artefact_link_columns = {
        column["name"] for column in inspector.get_columns("job_artefact_links")
    }
    assert {"owner_user_id", "job_id", "artefact_id"}.issubset(job_artefact_link_columns)

    ai_output_columns = {column["name"] for column in inspector.get_columns("ai_outputs")}
    assert {
        "owner_user_id",
        "job_id",
        "artefact_id",
        "output_type",
        "body",
        "source_context",
        "provider",
        "model_name",
        "status",
    }.issubset(ai_output_columns)

    ai_provider_columns = {
        column["name"] for column in inspector.get_columns("ai_provider_settings")
    }
    assert {"owner_user_id", "provider", "base_url", "model_name", "is_enabled"}.issubset(
        ai_provider_columns
    )

    profile_columns = {column["name"] for column in inspector.get_columns("user_profiles")}
    assert {
        "owner_user_id",
        "target_roles",
        "target_locations",
        "remote_preference",
        "salary_min",
        "salary_max",
        "salary_currency",
        "preferred_industries",
        "excluded_industries",
        "constraints",
        "urgency",
        "positioning_notes",
    }.issubset(profile_columns)


def test_core_models_can_persist_lifecycle_records(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    run_migrations(database_url)

    engine = create_engine(database_url)
    with Session(engine) as session:
        user = User(email="jobseeker@example.com", display_name="Job Seeker")
        session.add(user)
        session.flush()

        profile = UserProfile(
            owner_user_id=user.id,
            target_roles="Engineering Manager\nProduct Engineering Lead",
            target_locations="London\nRemote",
            remote_preference="hybrid",
            salary_currency="GBP",
            urgency="actively searching",
        )
        session.add(profile)
        session.flush()

        email_intake = EmailIntake(
            owner_user_id=user.id,
            subject="Interesting role",
            sender="alerts@example.com",
            body_text="See https://jobs.example.com/role",
            source_provider="manual_paste",
        )
        session.add(email_intake)
        session.flush()

        job = Job(
            owner_user_id=user.id,
            email_intake_id=email_intake.id,
            title="Senior Product Manager",
            company="Example Co",
            status="saved",
            intake_source="manual",
            intake_confidence="high",
            intake_state="accepted",
        )
        session.add(job)
        session.flush()

        application = Application(
            job_id=job.id,
            owner_user_id=user.id,
            status="preparing",
            channel="company_site",
        )
        session.add(application)
        session.flush()

        interview = InterviewEvent(
            job_id=job.id,
            application_id=application.id,
            owner_user_id=user.id,
            stage="screen",
        )
        session.add(interview)
        session.flush()

        communication = Communication(
            job_id=job.id,
            application_id=application.id,
            interview_event_id=interview.id,
            owner_user_id=user.id,
            event_type="note",
            notes="Initial recruiter screen scheduled.",
            follow_up_at=datetime(2026, 4, 12, 9, 0),
        )
        artefact = Artefact(
            owner_user_id=user.id,
            job_id=job.id,
            application_id=application.id,
            kind="resume",
            purpose="Tailored resume",
            version_label="v1",
            notes="Used for application prep.",
            outcome_context="unknown",
            filename="resume.pdf",
            storage_key="jobs/example/resume.pdf",
        )
        session.add_all([communication, artefact])
        session.flush()
        session.add(
            JobArtefactLink(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
            )
        )
        session.add(
            AiProviderSetting(
                owner_user_id=user.id,
                provider="openai",
                model_name="gpt-example",
                is_enabled=False,
            )
        )
        session.add(
            AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
                output_type="fit_summary",
                title="Fit summary",
                body="Strong alignment with product leadership.",
                source_context={"job_uuid": job.uuid},
                provider="openai",
                model_name="gpt-example",
                status="active",
            )
        )
        session.commit()

    with Session(engine) as session:
        stored_job = session.scalar(select(Job).where(Job.title == "Senior Product Manager"))

        assert stored_job is not None
        assert stored_job.owner.email == "jobseeker@example.com"
        assert stored_job.owner.profile is not None
        assert stored_job.owner.profile.remote_preference == "hybrid"
        assert stored_job.email_intake is not None
        assert stored_job.email_intake.subject == "Interesting role"
        assert stored_job.applications[0].channel == "company_site"
        assert stored_job.interviews[0].stage == "screen"
        assert stored_job.communications[0].event_type == "note"
        assert stored_job.communications[0].follow_up_at is not None
        assert stored_job.artefacts[0].storage_key == "jobs/example/resume.pdf"
        assert stored_job.artefact_links[0].artefact.purpose == "Tailored resume"
        assert stored_job.ai_outputs[0].output_type == "fit_summary"
        assert stored_job.owner.ai_provider_settings[0].provider == "openai"
