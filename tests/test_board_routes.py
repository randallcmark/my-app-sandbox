from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.auth.users import create_local_user
from app.db.models.communication import Communication
from app.db.models.job import Job
from app.main import app
from tests.test_local_auth_routes import build_client


def test_board_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/board")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_board_defaults_to_in_progress_workflow(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            db.add_all(
                [
                    Job(
                        owner_user_id=user.id,
                        title="Visible saved role",
                        company="Example Co",
                        status="saved",
                    ),
                    Job(
                        owner_user_id=user.id,
                        title="Visible applied role",
                        company="Other Co",
                        status="applied",
                    ),
                    Job(
                        owner_user_id=user.id,
                        title="Hidden archived role",
                        company="Old Co",
                        status="archived",
                    ),
                    Job(
                        owner_user_id=other.id,
                        title="Other user role",
                        company="Private Co",
                        status="saved",
                    ),
                ]
            )
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board")

        assert response.status_code == 200
        assert "Application Tracker" in response.text
        assert "In Progress" in response.text
        assert "Visible saved role" not in response.text
        assert "Visible applied role" in response.text
        assert "Hidden archived role" not in response.text
        assert "Other user role" not in response.text
        assert 'class="refined-board"' in response.text
        assert 'class="workflow-tab active" href="/board?workflow=in_progress"' in response.text
        assert "ui=classic" not in response.text
        assert 'data-status="preparing"' in response.text
        assert 'data-status="applied"' in response.text
        assert 'data-status="interviewing"' in response.text
        assert 'data-status="saved"' not in response.text
        assert 'draggable="true"' in response.text
        assert 'class="workflow-select"' not in response.text
        assert 'class="job-status-select"' not in response.text
        assert 'class="refined-action positive"' in response.text
        assert 'data-move="previous"' not in response.text
        assert 'data-move="next"' not in response.text
        assert "/jobs/" in response.text
        assert 'fetch("/api/jobs/board"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_legacy_ui_query_parameter_renders_refined_board(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            db.add(Job(owner_user_id=user.id, title="Applied role", status="applied"))
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board?workflow=in_progress&ui=classic")

        assert response.status_code == 200
        assert "Application Tracker" in response.text
        assert "Applied role" in response.text
        assert 'class="refined-board"' in response.text
        assert 'class="workflow-select"' not in response.text
        assert 'class="job-status-select"' not in response.text
        assert "ui=classic" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_prospects_workflow_shows_discovery_stages(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            db.add_all(
                [
                    Job(owner_user_id=user.id, title="Saved role", status="saved"),
                    Job(owner_user_id=user.id, title="Interested role", status="interested"),
                    Job(owner_user_id=user.id, title="Applied role", status="applied"),
                ]
            )
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board?workflow=prospects")

        assert response.status_code == 200
        assert "Prospects" in response.text
        assert "Saved role" in response.text
        assert "Interested role" in response.text
        assert "Applied role" not in response.text
        assert 'class="refined-list"' in response.text
        assert 'class="refined-item status-saved"' in response.text
        assert 'class="refined-item status-interested"' in response.text
        assert 'data-status-target="archived"' in response.text
        assert 'data-status-target="interested"' in response.text
        assert ">Keep</button>" in response.text
        assert 'class="board-column"' not in response.text
        assert 'data-status="applied"' not in response.text
        assert 'option value="applied"' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_outcomes_workflow_shows_status_indicated_rows(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            db.add_all(
                [
                    Job(owner_user_id=user.id, title="Offer role", status="offer"),
                    Job(owner_user_id=user.id, title="Rejected role", status="rejected"),
                    Job(owner_user_id=user.id, title="Applied role", status="applied"),
                ]
            )
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board?workflow=outcomes")

        assert response.status_code == 200
        assert "Outcomes" in response.text
        assert "Offer role" in response.text
        assert "Rejected role" in response.text
        assert "Applied role" not in response.text
        assert 'class="refined-list"' in response.text
        assert 'class="refined-item status-offer"' in response.text
        assert 'class="refined-item status-rejected"' in response.text
        assert 'class="board-column"' not in response.text
        assert 'data-status-target="archived"' in response.text
        assert 'data-status-target="interested"' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_archived_workflow_shows_archived_jobs(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            db.add_all(
                [
                    Job(owner_user_id=user.id, title="Active role", status="saved"),
                    Job(owner_user_id=user.id, title="Archived role", status="archived"),
                    Job(
                        owner_user_id=user.id,
                        title="Dismissed inbox role",
                        status="archived",
                        intake_source="browser_capture",
                        intake_confidence="medium",
                        intake_state="dismissed",
                    ),
                ]
            )
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board?workflow=archived")

        assert response.status_code == 200
        assert "Archived role" in response.text
        assert "Dismissed inbox role" in response.text
        assert "Active role" not in response.text
        assert 'class="refined-list"' in response.text
        assert 'class="refined-item status-archived"' in response.text
        assert 'data-status-target="saved"' in response.text
        assert 'class="board-column"' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_shows_stage_age_and_stale_indicator(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Stale applied role", status="applied")
            db.add(job)
            db.flush()
            db.add(
                Communication(
                    job_id=job.id,
                    owner_user_id=user.id,
                    event_type="stage_change",
                    direction="internal",
                    occurred_at=datetime.now(UTC) - timedelta(days=11),
                    subject="Status changed from preparing to applied",
                    notes="Job status changed from preparing to applied.",
                )
            )
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board")

        assert response.status_code == 200
        assert "Stale applied role" in response.text
        assert "In stage: 11 days" in response.text
        assert "stale" in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_shows_follow_up_indicators(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            overdue_job = Job(owner_user_id=user.id, title="Overdue follow-up", status="applied")
            today_job = Job(owner_user_id=user.id, title="Today follow-up", status="interviewing")
            future_job = Job(owner_user_id=user.id, title="Future follow-up", status="preparing")
            db.add_all([overdue_job, today_job, future_job])
            db.flush()
            now = datetime.now(UTC)
            db.add_all(
                [
                    Communication(
                        job_id=overdue_job.id,
                        owner_user_id=user.id,
                        event_type="note",
                        direction="internal",
                        subject="Follow up",
                        notes="Chase recruiter.",
                        follow_up_at=now - timedelta(days=1),
                    ),
                    Communication(
                        job_id=today_job.id,
                        owner_user_id=user.id,
                        event_type="note",
                        direction="internal",
                        subject="Follow up",
                        notes="Check interview details.",
                        follow_up_at=now,
                    ),
                    Communication(
                        job_id=future_job.id,
                        owner_user_id=user.id,
                        event_type="note",
                        direction="internal",
                        subject="Follow up",
                        notes="Review later.",
                        follow_up_at=now + timedelta(days=2),
                    ),
                ]
            )
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/board")

        assert response.status_code == 200
        assert "Follow-up overdue" in response.text
        assert "Follow-up due today" in response.text
        assert f"Follow-up {(datetime.now(UTC) + timedelta(days=2)).date().isoformat()}" in response.text
    finally:
        app.dependency_overrides.clear()


def test_root_redirects_logged_in_user_to_focus(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        login_response = client.post(
            "/auth/login",
            json={"email": "jobseeker@example.com", "password": "password"},
        )
        assert login_response.status_code == 200

        response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/focus"
    finally:
        app.dependency_overrides.clear()
