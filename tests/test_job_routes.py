from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.db.models.job import Job
from app.main import app
from tests.test_local_auth_routes import build_client


def login(client, email: str, password: str = "password") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 200


def create_user_with_jobs(session_local, *, email: str) -> list[str]:
    with session_local() as db:
        user = create_local_user(db, email=email, password="password")
        db.flush()
        jobs = [
            Job(
                owner_user_id=user.id,
                title="Saved role",
                company="Example Co",
                status="saved",
                board_position=2,
            ),
            Job(
                owner_user_id=user.id,
                title="Applied role",
                company="Other Co",
                status="applied",
                board_position=1,
            ),
            Job(
                owner_user_id=user.id,
                title="Archived role",
                company="Old Co",
                status="archived",
                board_position=0,
            ),
        ]
        db.add_all(jobs)
        db.commit()
        return [job.uuid for job in jobs]


def test_list_jobs_returns_current_users_non_archived_jobs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        create_user_with_jobs(session_local, email="other@example.com")
        login(client, "jobseeker@example.com")

        response = client.get("/api/jobs")

        assert response.status_code == 200
        titles = [job["title"] for job in response.json()]
        assert titles == ["Saved role", "Applied role"]
    finally:
        app.dependency_overrides.clear()


def test_list_jobs_can_include_archived_jobs(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.get("/api/jobs?include_archived=true")

        assert response.status_code == 200
        titles = {job["title"] for job in response.json()}
        assert titles == {"Saved role", "Applied role", "Archived role"}
    finally:
        app.dependency_overrides.clear()


def test_get_job_hides_cross_user_job_as_not_found(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_job_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.get(f"/api/jobs/{other_job_uuid}")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_update_job_board_persists_status_and_position(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.patch(
            f"/api/jobs/{job_uuid}/board",
            json={"status": "interviewing", "board_position": 4},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "interviewing"
        assert response.json()["board_position"] == 4

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "interviewing"
            assert job.board_position == 4
            assert job.archived_at is None
    finally:
        app.dependency_overrides.clear()


def test_update_job_board_sets_archive_timestamp(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.patch(f"/api/jobs/{job_uuid}/board", json={"status": "archived"})

        assert response.status_code == 200
        assert response.json()["status"] == "archived"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.archived_at is not None
    finally:
        app.dependency_overrides.clear()


def test_update_job_board_rejects_unknown_status(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.patch(f"/api/jobs/{job_uuid}/board", json={"status": "wishlist"})

        assert response.status_code == 400
        assert "Unsupported job status" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_bulk_board_update_persists_statuses_and_positions(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        saved_uuid, applied_uuid, _ = create_user_with_jobs(
            session_local,
            email="jobseeker@example.com",
        )
        login(client, "jobseeker@example.com")

        response = client.patch(
            "/api/jobs/board",
            json={
                "columns": {
                    "saved": [applied_uuid],
                    "interested": [],
                    "preparing": [],
                    "applied": [saved_uuid],
                    "interviewing": [],
                    "offer": [],
                    "rejected": [],
                }
            },
        )

        assert response.status_code == 200

        with session_local() as db:
            saved_job = db.scalar(select(Job).where(Job.uuid == saved_uuid))
            applied_job = db.scalar(select(Job).where(Job.uuid == applied_uuid))

            assert saved_job is not None
            assert applied_job is not None
            assert saved_job.status == "applied"
            assert saved_job.board_position == 0
            assert applied_job.status == "saved"
            assert applied_job.board_position == 0
    finally:
        app.dependency_overrides.clear()


def test_bulk_board_update_rejects_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.patch(
            "/api/jobs/board",
            json={
                "columns": {
                    "saved": [other_uuid],
                    "interested": [],
                    "preparing": [],
                    "applied": [],
                    "interviewing": [],
                    "offer": [],
                    "rejected": [],
                }
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Board update contains unknown jobs"
    finally:
        app.dependency_overrides.clear()


def test_bulk_board_update_rejects_duplicate_job_uuid(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.patch(
            "/api/jobs/board",
            json={
                "columns": {
                    "saved": [job_uuid],
                    "interested": [job_uuid],
                    "preparing": [],
                    "applied": [],
                    "interviewing": [],
                    "offer": [],
                    "rejected": [],
                }
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "A job can appear only once in a board update"
    finally:
        app.dependency_overrides.clear()
