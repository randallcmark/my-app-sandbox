from pathlib import Path

from app.auth.users import create_local_user
from app.core.config import settings
from app.main import app
from tests.test_local_auth_routes import build_client


def test_login_page_renders_form(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/login")

        assert response.status_code == 200
        assert '<form method="post" action="/login">' in response.text
        assert 'name="email"' in response.text
        assert 'name="password"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_login_form_sets_cookie_and_redirects_to_board(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        response = client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "password"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/board"
        assert settings.session_cookie_name in client.cookies
    finally:
        app.dependency_overrides.clear()


def test_login_form_shows_error_for_bad_credentials(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        response = client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "wrong"},
        )

        assert response.status_code == 200
        assert "Invalid email or password" in response.text
        assert settings.session_cookie_name not in client.cookies
    finally:
        app.dependency_overrides.clear()


def test_logout_form_clears_cookie_and_redirects_to_login(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        login_response = client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "password"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        logout_response = client.post("/logout", follow_redirects=False)

        assert logout_response.status_code == 303
        assert logout_response.headers["location"] == "/login"
        assert settings.session_cookie_name not in client.cookies
    finally:
        app.dependency_overrides.clear()
