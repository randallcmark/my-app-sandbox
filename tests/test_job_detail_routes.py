from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.db.models.application import Application
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.main import app
from tests.test_local_auth_routes import build_client


def login(client, email: str, password: str = "password") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 200


def test_job_detail_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/jobs/example")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_owned_job_and_timeline(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Senior Product Manager",
                company="Example Co",
                status="interviewing",
                board_position=3,
                source="terminal",
                source_url="https://jobs.example.com/product-manager",
                apply_url="https://jobs.example.com/product-manager/apply",
                location="Remote",
                description_raw="Own the roadmap.",
            )
            db.add(job)
            db.flush()
            db.add(
                Communication(
                    job_id=job.id,
                    owner_user_id=user.id,
                    event_type="stage_change",
                    direction="internal",
                    occurred_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
                    subject="Status changed from applied to interviewing",
                    notes="Job status changed from applied to interviewing.",
                )
            )
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}")

        assert response.status_code == 200
        assert "Senior Product Manager" in response.text
        assert "Example Co" in response.text
        assert "Own the roadmap." in response.text
        assert "Open source" in response.text
        assert "Open apply link" in response.text
        assert '<form class="note-form"' in response.text
        assert '<form class="quick-action-form"' in response.text
        assert f'action="/jobs/{job_uuid}/interviews"' in response.text
        assert f'action="/jobs/{job_uuid}/archive"' in response.text
        assert "Status changed from applied to interviewing" in response.text
        assert "Job status changed from applied to interviewing." in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_note_form_adds_note_and_redirects(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Note target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/notes",
            data={"subject": "Prep", "notes": "Update resume bullets."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Prep" in detail_response.text
        assert "Update resume bullets." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_mark_applied_form_creates_application_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Apply target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/mark-applied",
            data={"channel": "company_site", "notes": "Submitted through ATS."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            application = db.scalar(select(Application))
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert application is not None
            assert application.channel == "company_site"
            assert application.notes == "Submitted through ATS."
            assert job is not None
            assert job.status == "applied"

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Submitted through ATS." in detail_response.text
        assert "Marked applied" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_archive_form_archives_job_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Archive target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/archive",
            data={"notes": "No longer relevant."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "archived"
            assert job.archived_at is not None

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Archived" in detail_response.text
        assert "No longer relevant." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_schedule_interview_form_creates_interview_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Interview target", status="applied")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/interviews",
            data={
                "stage": "Hiring manager",
                "scheduled_at": "2026-04-12T18:30",
                "location": "Video call",
                "participants": "Hiring manager",
                "notes": "Review product examples.",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))
            interview = db.scalar(select(InterviewEvent))

            assert job is not None
            assert job.status == "interviewing"
            assert interview is not None
            assert interview.stage == "Hiring manager"
            assert interview.location == "Video call"

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Hiring manager" in detail_response.text
        assert "Review product examples." in detail_response.text
        assert "Interview scheduled: Hiring manager" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_hides_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            other = create_local_user(db, email="other@example.com", password="password")
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=other.id, title="Private role", status="saved")
            db.add(job)
            db.add(Job(owner_user_id=user.id, title="Visible role", status="saved"))
            db.commit()
            other_job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{other_job_uuid}")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
