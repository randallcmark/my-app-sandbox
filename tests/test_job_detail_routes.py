from datetime import UTC, datetime
from pathlib import Path

from app.auth.users import create_local_user
from app.db.models.communication import Communication
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
        assert "Status changed from applied to interviewing" in response.text
        assert "Job status changed from applied to interviewing." in response.text
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
