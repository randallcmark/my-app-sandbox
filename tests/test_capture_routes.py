from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.db.models.job import Job
from app.main import app
from tests.test_local_auth_routes import build_client


def create_capture_token(client, session_local) -> str:
    with session_local() as db:
        create_local_user(db, email="jobseeker@example.com", password="password")
        db.commit()

    login_response = client.post(
        "/auth/login",
        json={"email": "jobseeker@example.com", "password": "password"},
    )
    assert login_response.status_code == 200

    token_response = client.post("/auth/api-tokens", json={"name": "Browser capture"})
    assert token_response.status_code == 201
    return token_response.json()["token"]


def test_capture_job_creates_owned_job_with_bearer_token(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)

        response = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_url": "https://jobs.example.com/product-manager",
                "apply_url": "https://jobs.example.com/product-manager/apply",
                "title": "Product Manager",
                "company": "Example Co",
                "location": "Remote",
                "description": "Own the roadmap.",
                "selected_text": "Interesting role",
                "source_platform": "example_jobs",
                "raw_extraction_metadata": {"selector": "json-ld"},
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["created"] is True
        assert payload["title"] == "Product Manager"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == payload["uuid"]))

            assert job is not None
            assert job.owner.email == "jobseeker@example.com"
            assert job.status == "saved"
            assert job.source == "example_jobs"
            assert job.description_raw == "Own the roadmap."
            assert job.structured_data["capture"]["selected_text"] == "Interesting role"
            assert job.structured_data["capture"]["raw_extraction_metadata"] == {
                "selector": "json-ld"
            }
    finally:
        app.dependency_overrides.clear()


def test_capture_job_deduplicates_by_owner_and_source_url(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)
        headers = {"Authorization": f"Bearer {token}"}

        first = client.post(
            "/api/capture/jobs",
            headers=headers,
            json={
                "source_url": "https://jobs.example.com/product-manager",
                "title": "Product Manager",
                "company": "Example Co",
            },
        )
        second = client.post(
            "/api/capture/jobs",
            headers=headers,
            json={
                "source_url": "https://jobs.example.com/product-manager",
                "title": "Senior Product Manager",
                "company": "Example Co",
            },
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert second.json()["uuid"] == first.json()["uuid"]
        assert second.json()["title"] == "Senior Product Manager"

        with session_local() as db:
            jobs = db.scalars(select(Job)).all()

            assert len(jobs) == 1
    finally:
        app.dependency_overrides.clear()


def test_capture_job_requires_bearer_token(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/capture/jobs",
            json={"source_url": "https://jobs.example.com/product-manager"},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_capture_bookmarklet_setup_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/api/capture/bookmarklet")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_capture_bookmarklet_setup_renders_generator(tmp_path: Path, monkeypatch) -> None:
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

        response = client.get("/api/capture/bookmarklet")

        assert response.status_code == 200
        assert "Capture setup" in response.text
        assert "Capture job" in response.text
        assert "ats_..." in response.text
        assert "/api/capture/jobs" in response.text
        assert "JobPosting" in response.text
        assert "PASTE_TOKEN_HERE" in response.text
        assert "javascript:javascript:" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_capture_endpoint_allows_bookmarklet_cors_preflight(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.options(
            "/api/capture/jobs",
            headers={
                "Origin": "https://jobs.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
        assert "POST" in response.headers["access-control-allow-methods"]
        assert "Authorization" in response.headers["access-control-allow-headers"]
    finally:
        app.dependency_overrides.clear()
