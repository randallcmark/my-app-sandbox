from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.db.models.email_intake import EmailIntake
from app.db.models.job import Job
from app.main import app
from tests.test_capture_routes import create_capture_token
from tests.test_local_auth_routes import build_client


def login(client, email: str, password: str = "password") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 200


def test_inbox_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/inbox")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_inbox_empty_state(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.get("/inbox")

        assert response.status_code == 200
        assert "<h1>Inbox</h1>" in response.text
        assert "Inbox is clear" in response.text
        assert 'href="/focus"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_capture_job_lands_in_inbox_and_is_hidden_from_board(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)

        response = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_url": "https://jobs.example.com/inbox-role",
                "title": "Inbox role",
                "company": "Capture Co",
                "raw_extraction_metadata": {"extractor": "firefox_extension"},
            },
        )

        assert response.status_code == 201
        inbox_response = client.get("/inbox")
        board_response = client.get("/board?workflow=prospects")

        assert "Inbox role" in inbox_response.text
        assert "jobs.example.com" in inbox_response.text
        assert "medium confidence" in inbox_response.text
        assert "Open source" in inbox_response.text
        assert 'class="source-url"' not in inbox_response.text
        assert "Inbox role" not in board_response.text

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == response.json()["uuid"]))

            assert job is not None
            assert job.intake_source == "browser_capture"
            assert job.intake_state == "needs_review"
    finally:
        app.dependency_overrides.clear()


def test_accept_inbox_job_moves_to_interested(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)
        captured = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"source_url": "https://jobs.example.com/accept", "title": "Accept role"},
        )
        job_uuid = captured.json()["uuid"]

        response = client.post(f"/inbox/{job_uuid}/accept", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/inbox"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "interested"
            assert job.intake_state == "accepted"
            assert job.communications[-1].subject == "Inbox accepted"
    finally:
        app.dependency_overrides.clear()


def test_dismiss_inbox_job_archives_and_hides_it(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)
        captured = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"source_url": "https://jobs.example.com/dismiss", "title": "Dismiss role"},
        )
        job_uuid = captured.json()["uuid"]

        response = client.post(f"/inbox/{job_uuid}/dismiss", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/inbox"
        assert "Dismiss role" not in client.get("/inbox").text

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "archived"
            assert job.archived_at is not None
            assert job.intake_state == "dismissed"
            assert job.communications[-1].subject == "Inbox dismissed"
    finally:
        app.dependency_overrides.clear()


def test_inbox_hides_other_users_jobs(tmp_path: Path, monkeypatch) -> None:
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
                        title="Visible inbox role",
                        status="saved",
                        intake_source="api_capture",
                        intake_confidence="medium",
                        intake_state="needs_review",
                    ),
                    Job(
                        owner_user_id=other.id,
                        title="Other inbox role",
                        status="saved",
                        intake_source="api_capture",
                        intake_confidence="medium",
                        intake_state="needs_review",
                    ),
                ]
            )
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.get("/inbox")

        assert response.status_code == 200
        assert "Visible inbox role" in response.text
        assert "Other inbox role" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_email_capture_form_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/inbox/email/new")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_email_capture_form_renders(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.get("/inbox/email/new")

        assert response.status_code == 200
        assert '<form method="post" action="/inbox/email">' in response.text
        assert 'name="subject"' in response.text
        assert 'name="body_text"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_email_capture_api_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/inbox/email-captures",
            json={"subject": "Role", "body_text": "https://jobs.example.com/role"},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_email_capture_api_creates_inbox_job_with_provenance(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.post(
            "/api/inbox/email-captures",
            json={
                "subject": "Senior Platform Role",
                "sender": "alerts@example.com",
                "received_at": "2026-04-18T09:30:00Z",
                "body_text": (
                    "View role https://jobs.example.com/platform "
                    "unsubscribe https://jobs.example.com/unsubscribe"
                ),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["created"] is True
        assert body["intake_state"] == "needs_review"

        with session_local() as db:
            email_intake = db.scalar(
                select(EmailIntake).where(EmailIntake.uuid == body["email_intake_uuid"])
            )
            job = db.scalar(select(Job).where(Job.uuid == body["job_uuid"]))

            assert email_intake is not None
            assert email_intake.subject == "Senior Platform Role"
            assert email_intake.sender == "alerts@example.com"
            assert email_intake.source_provider == "manual_paste"
            assert job is not None
            assert job.email_intake_id == email_intake.id
            assert job.title == "Senior Platform Role"
            assert job.source_url == "https://jobs.example.com/platform"
            assert job.apply_url == "https://jobs.example.com/platform"
            assert job.intake_source == "email_capture"
            assert job.intake_confidence == "unknown"
            assert job.intake_state == "needs_review"
            assert job.structured_data["email_capture"]["all_urls"] == [
                "https://jobs.example.com/platform",
                "https://jobs.example.com/unsubscribe",
            ]
            assert (
                job.structured_data["email_capture"]["selected_source_url"]
                == "https://jobs.example.com/platform"
            )
    finally:
        app.dependency_overrides.clear()


def test_email_capture_api_uses_html_body_when_text_is_empty(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.post(
            "/api/inbox/email-captures",
            json={
                "subject": "HTML role",
                "body_html": "<p>Apply at <a href='https://jobs.example.com/html'>role</a></p>",
            },
        )

        assert response.status_code == 200
        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == response.json()["job_uuid"]))

            assert job is not None
            assert job.description_raw == "Apply at role"
            assert job.source_url == "https://jobs.example.com/html"
    finally:
        app.dependency_overrides.clear()


def test_email_capture_api_deduplicates_existing_owned_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            existing_job = Job(
                owner_user_id=user.id,
                title="Existing role",
                status="interested",
                source_url="https://jobs.example.com/existing",
                intake_state="accepted",
            )
            db.add(existing_job)
            db.commit()
            existing_uuid = existing_job.uuid
        login(client, "jobseeker@example.com")

        response = client.post(
            "/api/inbox/email-captures",
            json={
                "subject": "Existing role from email",
                "body_text": "See https://jobs.example.com/existing",
            },
        )

        assert response.status_code == 200
        assert response.json()["created"] is False
        assert response.json()["job_uuid"] == existing_uuid
        assert response.json()["intake_state"] == "accepted"

        with session_local() as db:
            jobs = db.scalars(select(Job)).all()
            email_intakes = db.scalars(select(EmailIntake)).all()
            job = db.scalar(select(Job).where(Job.uuid == existing_uuid))

            assert len(jobs) == 1
            assert len(email_intakes) == 1
            assert job is not None
            assert job.status == "interested"
            assert job.intake_state == "accepted"
            assert job.email_intake_id == email_intakes[0].id
            assert job.communications[-1].subject == "Email captured"
    finally:
        app.dependency_overrides.clear()


def test_email_capture_form_creates_inbox_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()
        login(client, "jobseeker@example.com")

        response = client.post(
            "/inbox/email",
            data={
                "subject": "Pasted role",
                "sender": "alerts@example.com",
                "received_at": "2026-04-18T10:15",
                "body_text": "Apply at https://jobs.example.com/pasted",
                "body_html": "",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/inbox"
        assert "Pasted role" in client.get("/inbox").text
        assert "Pasted role" not in client.get("/board?workflow=prospects").text
    finally:
        app.dependency_overrides.clear()


def test_inbox_review_page_renders_for_owned_inbox_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)
        captured = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_url": "https://jobs.example.com/review",
                "title": "Review role",
                "company": "Capture Co",
            },
        )
        job_uuid = captured.json()["uuid"]

        response = client.get(f"/inbox/{job_uuid}/review")

        assert response.status_code == 200
        assert "Review Inbox Item" in response.text
        assert 'action="/inbox/' in response.text
        assert "Capture Co" in response.text
        assert "https://jobs.example.com/review" in response.text
        assert "Captured context" in response.text
    finally:
        app.dependency_overrides.clear()


def test_inbox_review_update_saves_changes_and_creates_note(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)
        captured = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"source_url": "https://jobs.example.com/original", "title": "Original title"},
        )
        job_uuid = captured.json()["uuid"]

        response = client.post(
            f"/inbox/{job_uuid}/review",
            data={
                "title": " Updated title ",
                "company": "  New Co  ",
                "location": " Remote ",
                "source": " Email ",
                "source_url": " https://jobs.example.com/updated ",
                "description_raw": " Tailored description ",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/inbox/{job_uuid}/review"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.title == "Updated title"
            assert job.company == "New Co"
            assert job.location == "Remote"
            assert job.source == "Email"
            assert job.source_url == "https://jobs.example.com/updated"
            assert job.apply_url == "https://jobs.example.com/updated"
            assert job.description_raw == "Tailored description"
            assert job.description_clean == "Tailored description"
            assert job.communications[-1].subject == "Inbox enriched"
            assert "title" in (job.communications[-1].notes or "")
    finally:
        app.dependency_overrides.clear()


def test_inbox_review_update_rejects_blank_title(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        token = create_capture_token(client, session_local)
        captured = client.post(
            "/api/capture/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"source_url": "https://jobs.example.com/blank-title", "title": "Role"},
        )
        job_uuid = captured.json()["uuid"]

        response = client.post(
            f"/inbox/{job_uuid}/review",
            data={"title": "   "},
        )

        assert response.status_code == 200
        assert "Title is required" in response.text

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.title == "Role"
            assert all(note.subject != "Inbox enriched" for note in job.communications)
    finally:
        app.dependency_overrides.clear()


def test_inbox_review_page_is_owner_scoped(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            owner = create_local_user(db, email="owner@example.com", password="password")
            other = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=other.id,
                title="Other inbox role",
                status="saved",
                intake_source="api_capture",
                intake_confidence="medium",
                intake_state="needs_review",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "owner@example.com")

        response = client.get(f"/inbox/{job_uuid}/review")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
