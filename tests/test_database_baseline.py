from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User


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
    tables = set(inspect(engine).get_table_names())

    assert {
        "alembic_version",
        "api_tokens",
        "applications",
        "artefacts",
        "communications",
        "interview_events",
        "jobs",
        "users",
    }.issubset(tables)


def test_core_models_can_persist_lifecycle_records(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    run_migrations(database_url)

    engine = create_engine(database_url)
    with Session(engine) as session:
        user = User(email="jobseeker@example.com", display_name="Job Seeker")
        session.add(user)
        session.flush()

        job = Job(
            owner_user_id=user.id,
            title="Senior Product Manager",
            company="Example Co",
            status="saved",
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
        )
        artefact = Artefact(
            owner_user_id=user.id,
            job_id=job.id,
            application_id=application.id,
            kind="resume",
            filename="resume.pdf",
            storage_key="jobs/example/resume.pdf",
        )
        session.add_all([communication, artefact])
        session.commit()

    with Session(engine) as session:
        stored_job = session.scalar(select(Job).where(Job.title == "Senior Product Manager"))

        assert stored_job is not None
        assert stored_job.owner.email == "jobseeker@example.com"
        assert stored_job.applications[0].channel == "company_site"
        assert stored_job.interviews[0].stage == "screen"
        assert stored_job.communications[0].event_type == "note"
        assert stored_job.artefacts[0].storage_key == "jobs/example/resume.pdf"

