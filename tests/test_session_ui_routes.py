from pathlib import Path

from app.auth.users import create_local_user
from app.core.config import settings
from app.db.models.api_token import ApiToken
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


def test_settings_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/settings")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_settings_creates_capture_token_and_shows_secret_once(tmp_path: Path, monkeypatch) -> None:
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

        response = client.post(
            "/settings/api-tokens",
            data={"name": "Browser bookmarklet", "scope": "capture:jobs"},
        )

        assert response.status_code == 200
        assert "New token" in response.text
        assert "ats_" in response.text
        assert "Browser bookmarklet" in response.text
        assert "capture:jobs" in response.text
        assert "Open Capture setup" in response.text

        settings_response = client.get("/settings")

        assert settings_response.status_code == 200
        assert "Browser bookmarklet" in settings_response.text
        assert "capture:jobs" in settings_response.text
        assert "New token" not in settings_response.text
    finally:
        app.dependency_overrides.clear()


def test_settings_revokes_owned_token(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "password"},
            follow_redirects=False,
        )
        create_response = client.post(
            "/settings/api-tokens",
            data={"name": "Browser bookmarklet", "scope": "capture:jobs"},
        )
        assert create_response.status_code == 200

        with session_local() as db:
            api_token = db.query(ApiToken).one()
            token_uuid = api_token.uuid

        revoke_response = client.post(
            f"/settings/api-tokens/{token_uuid}/revoke",
            follow_redirects=False,
        )

        assert revoke_response.status_code == 303
        assert revoke_response.headers["location"] == "/settings"

        with session_local() as db:
            api_token = db.query(ApiToken).one()

            assert api_token.revoked_at is not None
    finally:
        app.dependency_overrides.clear()


def test_settings_revoke_does_not_cross_user_boundaries(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            owner = create_local_user(db, email="owner@example.com", password="password")
            create_local_user(db, email="other@example.com", password="password")
            db.flush()
            api_token = ApiToken(
                owner_user_id=owner.id,
                name="Owner token",
                token_hash="hash",
                scopes="capture:jobs",
            )
            db.add(api_token)
            db.commit()
            token_uuid = api_token.uuid

        client.post(
            "/login",
            data={"email": "other@example.com", "password": "password"},
            follow_redirects=False,
        )

        response = client.post(f"/settings/api-tokens/{token_uuid}/revoke")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
