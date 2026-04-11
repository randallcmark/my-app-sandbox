from pathlib import Path

from app.auth.users import create_local_user
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


def test_board_renders_current_users_jobs_by_stage(tmp_path: Path, monkeypatch) -> None:
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
        assert "Application Board" in response.text
        assert "Visible saved role" in response.text
        assert "Visible applied role" in response.text
        assert "Hidden archived role" not in response.text
        assert "Other user role" not in response.text
        assert 'data-status="saved"' in response.text
        assert 'data-status="applied"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_root_redirects_logged_in_user_to_board(tmp_path: Path, monkeypatch) -> None:
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
        assert response.headers["location"] == "/board"
    finally:
        app.dependency_overrides.clear()
