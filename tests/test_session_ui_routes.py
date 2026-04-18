from pathlib import Path
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import select

from app.auth.users import create_local_user
from app.core.config import settings
from app.db.models.ai_provider_setting import AiProviderSetting
from app.db.models.api_token import ApiToken
from app.db.models.job import Job
from app.db.models.user import User
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


def test_root_redirects_to_setup_when_no_users_exist(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/setup"
    finally:
        app.dependency_overrides.clear()


def test_setup_form_creates_first_admin_and_logs_in(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        form_response = client.get("/setup")

        assert form_response.status_code == 200
        assert '<form method="post" action="/setup">' in form_response.text
        assert "Create admin" in form_response.text

        response = client.post(
            "/setup",
            data={
                "email": "admin@example.com",
                "display_name": "Admin User",
                "password": "correct horse battery staple",
                "confirm_password": "correct horse battery staple",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/focus"
        assert settings.session_cookie_name in client.cookies

        with session_local() as db:
            user = db.scalar(select(User).where(User.email == "admin@example.com"))

            assert user is not None
            assert user.display_name == "Admin User"
            assert user.is_admin is True
            assert user.is_active is True
    finally:
        app.dependency_overrides.clear()


def test_setup_form_rejects_mismatched_passwords(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/setup",
            data={
                "email": "admin@example.com",
                "password": "correct horse battery staple",
                "confirm_password": "different horse battery staple",
            },
        )

        assert response.status_code == 200
        assert "Passwords do not match" in response.text

        with session_local() as db:
            assert db.scalar(select(User)) is None
    finally:
        app.dependency_overrides.clear()


def test_setup_redirects_after_user_exists(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        response = client.get("/setup", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/login"
    finally:
        app.dependency_overrides.clear()


def test_login_form_sets_cookie_and_redirects_to_focus(tmp_path: Path, monkeypatch) -> None:
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
        assert response.headers["location"] == "/focus"
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


def test_settings_shows_ai_readiness_placeholders(tmp_path: Path, monkeypatch) -> None:
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

        response = client.get("/settings")

        assert response.status_code == 200
        assert "AI readiness" in response.text
        assert "OpenAI" in response.text
        assert "Anthropic" in response.text
        assert "OpenAI-compatible local endpoint" in response.text
        assert "disabled by default" in response.text
    finally:
        app.dependency_overrides.clear()


def test_settings_updates_ai_provider_placeholder(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            create_local_user(db, email="other@example.com", password="password")
            db.commit()

        client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "password"},
            follow_redirects=False,
        )

        response = client.post(
            "/settings/ai-provider",
            data={
                "provider": "openai_compatible",
                "label": "Local endpoint",
                "base_url": "http://localhost:11434/v1",
                "model_name": "local-model",
                "is_enabled": "true",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/settings#ai"

        with session_local() as db:
            setting = db.scalar(select(AiProviderSetting))

            assert setting is not None
            assert setting.owner.email == "jobseeker@example.com"
            assert setting.provider == "openai_compatible"
            assert setting.label == "Local endpoint"
            assert setting.base_url == "http://localhost:11434/v1"
            assert setting.model_name == "local-model"
            assert setting.is_enabled is True

        settings_response = client.get("/settings")

        assert "local-model" in settings_response.text
        assert "http://localhost:11434/v1" in settings_response.text
        assert "Enabled" in settings_response.text
    finally:
        app.dependency_overrides.clear()


def test_admin_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/admin")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_admin_rejects_non_admin_user(tmp_path: Path, monkeypatch) -> None:
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

        response = client.get("/admin")

        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_admin_page_shows_system_links_and_counts(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            admin = create_local_user(
                db,
                email="admin@example.com",
                password="password",
                is_admin=True,
            )
            db.flush()
            db.add(Job(owner_user_id=admin.id, title="Tracked role", status="saved"))
            db.add(
                ApiToken(
                    owner_user_id=admin.id,
                    name="Capture",
                    token_hash="hash",
                    scopes="capture:jobs",
                )
            )
            db.commit()

        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "password"},
            follow_redirects=False,
        )

        response = client.get("/admin")

        assert response.status_code == 200
        assert "Admin" in response.text
        assert "Users" in response.text
        assert "Jobs" in response.text
        assert "API tokens" in response.text
        assert "Create Capture Token" in response.text
        assert "Capture" in response.text
        assert "admin@example.com" in response.text
        assert 'href="/api/capture/bookmarklet"' in response.text
        assert 'href="/health"' in response.text
        assert 'href="/admin/backup"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_admin_creates_capture_token_and_shows_secret_once(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="admin@example.com", password="password", is_admin=True)
            db.commit()

        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "password"},
            follow_redirects=False,
        )

        response = client.post(
            "/admin/api-tokens",
            data={"name": "Admin browser capture", "scope": "capture:jobs"},
        )

        assert response.status_code == 200
        assert "New admin token" in response.text
        assert "ats_" in response.text
        assert "Admin browser capture" in response.text
        assert "capture:jobs" in response.text

        with session_local() as db:
            api_token = db.scalar(select(ApiToken).where(ApiToken.name == "Admin browser capture"))

            assert api_token is not None
            assert api_token.owner.email == "admin@example.com"
    finally:
        app.dependency_overrides.clear()


def test_admin_revokes_any_user_token(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            admin = create_local_user(db, email="admin@example.com", password="password", is_admin=True)
            owner = create_local_user(db, email="owner@example.com", password="password")
            db.flush()
            api_token = ApiToken(
                owner_user_id=owner.id,
                name="Owner token",
                token_hash="owner-hash",
                scopes="capture:jobs",
            )
            db.add(api_token)
            db.commit()
            token_uuid = api_token.uuid
            assert admin.is_admin is True

        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "password"},
            follow_redirects=False,
        )

        response = client.post(f"/admin/api-tokens/{token_uuid}/revoke", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/admin"

        with session_local() as db:
            api_token = db.scalar(select(ApiToken).where(ApiToken.uuid == token_uuid))

            assert api_token is not None
            assert api_token.revoked_at is not None
    finally:
        app.dependency_overrides.clear()


def test_admin_backup_download_contains_database_and_artefacts(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    database_path = tmp_path / "app.db"
    artefact_root = tmp_path / "artefacts"
    artefact_path = artefact_root / "jobs" / "job-uuid" / "artefacts" / "resume.txt"
    artefact_path.parent.mkdir(parents=True)
    artefact_path.write_text("resume bytes")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database_path}")
    monkeypatch.setattr(settings, "local_storage_path", str(artefact_root))
    try:
        with session_local() as db:
            admin = create_local_user(db, email="admin@example.com", password="password", is_admin=True)
            db.add(Job(owner_user_id=admin.id, title="Backup role", status="saved"))
            db.commit()

        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "password"},
            follow_redirects=False,
        )

        response = client.get("/admin/backup")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "application-tracker-backup-" in response.headers["content-disposition"]

        with ZipFile(BytesIO(response.content)) as archive:
            names = set(archive.namelist())

            assert "MANIFEST.txt" in names
            assert "database/app.db" in names
            assert "artefacts/jobs/job-uuid/artefacts/resume.txt" in names
            assert archive.read("artefacts/jobs/job-uuid/artefacts/resume.txt") == b"resume bytes"
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
