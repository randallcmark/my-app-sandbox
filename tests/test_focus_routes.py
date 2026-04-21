from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.auth.users import create_local_user
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user_profile import UserProfile
from app.main import app
from tests.test_local_auth_routes import build_client


def login(client, email: str, password: str = "password") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 200


def test_focus_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/focus")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_focus_empty_state_prompts_for_profile(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.get("/focus")

        assert response.status_code == 200
        assert "<h1>Focus</h1>" in response.text
        assert "Complete your job-search profile" in response.text
        assert "No due follow-ups." in response.text
        assert "No stale active jobs." in response.text
        assert "No upcoming interviews." in response.text
        assert "No recent saved or interested jobs." in response.text
        assert 'href="/board"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_focus_shows_owner_scoped_attention_items(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            db.add(
                UserProfile(
                    owner_user_id=user.id,
                    target_roles="Engineering Manager",
                )
            )
            stale_job = Job(
                owner_user_id=user.id,
                title="Stale applied role",
                company="Example Co",
                status="applied",
                updated_at=now - timedelta(days=10),
            )
            recent_job = Job(
                owner_user_id=user.id,
                title="Recent prospect",
                company="Prospect Co",
                status="saved",
            )
            archived_job = Job(
                owner_user_id=user.id,
                title="Archived follow-up role",
                status="archived",
            )
            other_job = Job(
                owner_user_id=other.id,
                title="Other user role",
                status="applied",
                updated_at=now - timedelta(days=10),
            )
            db.add_all([stale_job, recent_job, archived_job, other_job])
            db.flush()
            db.add_all(
                [
                    Communication(
                        job_id=stale_job.id,
                        owner_user_id=user.id,
                        event_type="note",
                        subject="Chase recruiter",
                        follow_up_at=now - timedelta(hours=1),
                    ),
                    Communication(
                        job_id=archived_job.id,
                        owner_user_id=user.id,
                        event_type="note",
                        subject="Hidden archived follow-up",
                        follow_up_at=now - timedelta(hours=1),
                    ),
                    InterviewEvent(
                        job_id=stale_job.id,
                        owner_user_id=user.id,
                        stage="technical",
                        scheduled_at=now + timedelta(days=2),
                        location="Video",
                    ),
                ]
            )
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.get("/focus")

        assert response.status_code == 200
        assert "Complete your job-search profile" not in response.text
        assert "Chase recruiter" in response.text
        assert "Stale applied role" in response.text
        assert "Recent prospect" in response.text
        assert "technical" in response.text
        assert "Video" in response.text
        assert "Other user role" not in response.text
        assert "Hidden archived follow-up" not in response.text
        assert "Archived follow-up role" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_focus_goal_chip_formats_salary_as_rounded_thousands(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            db.add(
                UserProfile(
                    owner_user_id=user.id,
                    target_roles="Engineering Manager",
                    target_locations="Remote",
                    salary_min=Decimal("100000.00"),
                    salary_max=Decimal("125000.00"),
                    salary_currency="GBP",
                )
            )
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.get("/focus")

        assert response.status_code == 200
        assert "GBP 100K" in response.text
        assert "GBP 125K" in response.text
        assert "100000.00" not in response.text
        assert "125000.00" not in response.text
    finally:
        app.dependency_overrides.clear()
