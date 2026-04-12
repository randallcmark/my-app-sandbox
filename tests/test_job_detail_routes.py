from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.core.config import settings
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
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
        assert '<form class="note-form"' in response.text
        assert '<form class="quick-action-form"' in response.text
        assert f'action="/jobs/{job_uuid}/interviews"' in response.text
        assert f'action="/jobs/{job_uuid}/archive"' in response.text
        assert f'action="/jobs/{job_uuid}/artefacts"' in response.text
        assert f'action="/jobs/{job_uuid}/status"' in response.text
        assert "Workflow Status" in response.text
        assert 'data-field="title"' in response.text
        assert 'data-field="description_raw"' in response.text
        assert 'data-field="status"' in response.text
        assert 'id="edit-savebar"' in response.text
        assert '<summary>Journal</summary>' in response.text
        assert "<details class=\"timeline-panel\">" in response.text
        assert 'class="local-time" datetime="2026-04-11T12:00:00+00:00"' in response.text
        assert "Intl.DateTimeFormat" in response.text
        assert "Status changed from applied to interviewing" in response.text
        assert "Job status changed from applied to interviewing." in response.text
    finally:
        app.dependency_overrides.clear()


def test_new_job_form_creates_job_and_redirects(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        login(client, "jobseeker@example.com")

        form_response = client.get("/jobs/new")

        assert form_response.status_code == 200
        assert '<form class="job-form" method="post" action="/jobs/new">' in form_response.text

        response = client.post(
            "/jobs/new",
            data={
                "title": "Manual UI role",
                "company": "Manual UI Co",
                "job_status": "preparing",
                "source_url": "https://jobs.example.com/ui",
                "apply_url": "https://jobs.example.com/ui/apply",
                "location": "Remote",
                "remote_policy": "remote",
                "salary_min": "90000",
                "salary_max": "110000",
                "salary_currency": "GBP",
                "description_raw": "Own the UI.",
                "initial_note": "Good fit.",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.title == "Manual UI role"))

            assert job is not None
            assert response.headers["location"] == f"/jobs/{job.uuid}"
            assert job.status == "preparing"
            assert job.board_position == 0
            assert job.source == "manual"
            assert job.salary_min == 90000
            assert job.communications[0].subject == "Created manually"

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        assert "Manual UI role" in detail_response.text
        assert "Own the UI." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_new_job_form_rejects_bad_status(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        login(client, "jobseeker@example.com")

        response = client.post(
            "/jobs/new",
            data={"title": "Bad status role", "job_status": "archived"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "New job status must be an active board status"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_note_form_adds_note_and_redirects(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Note target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/notes",
            data={
                "subject": "Prep",
                "notes": "Update resume bullets.",
                "follow_up_at": "2026-04-12",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Prep" in detail_response.text
        assert "Update resume bullets." in detail_response.text
        assert "Follow-up:" in detail_response.text
        assert 'datetime="2026-04-12T00:00:00+00:00"' in detail_response.text
        assert ">2026-04-12 00:00</time>" in detail_response.text

        with session_local() as db:
            event = db.scalar(select(Communication).where(Communication.subject == "Prep"))

            assert event is not None
            assert event.follow_up_at is not None
    finally:
        app.dependency_overrides.clear()


def test_job_detail_edit_form_updates_job_and_redirects(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Typo role",
                company="Typo Co",
                status="saved",
                source_url="https://jobs.example.com/source",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/edit",
            data={
                "title": "Corrected role",
                "company": "Corrected Co",
                "job_status": "interested",
                "source": "manual",
                "source_url": "",
                "apply_url": "https://jobs.example.com/apply",
                "location": "Remote",
                "remote_policy": "remote",
                "salary_min": "85000",
                "salary_max": "100000",
                "salary_currency": "GBP",
                "description_raw": "Corrected description.",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.title == "Corrected role"
            assert job.company == "Corrected Co"
            assert job.status == "interested"
            assert job.source_url is None
            assert job.description_clean == "Corrected description."

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Corrected role" in detail_response.text
        assert "Corrected description." in detail_response.text
        assert "Status changed from saved to interested" in detail_response.text
        assert "Job edited" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_edit_form_rejects_blank_title(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Edit target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/edit",
            data={"title": "   ", "job_status": "saved"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Job title is required"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_section_edit_preserves_unsubmitted_fields(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Section edit target",
                company="Keep Co",
                status="applied",
                source_url="https://jobs.example.com/source",
                location="Remote",
                description_raw="Old description.",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/edit",
            data={"description_raw": "Only the description changed."},
            follow_redirects=False,
        )

        assert response.status_code == 303

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.title == "Section edit target"
            assert job.company == "Keep Co"
            assert job.status == "applied"
            assert job.source_url == "https://jobs.example.com/source"
            assert job.location == "Remote"
            assert job.description_raw == "Only the description changed."
    finally:
        app.dependency_overrides.clear()


def test_job_detail_mark_applied_form_creates_application_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Apply target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/mark-applied",
            data={"channel": "company_site", "notes": "Submitted through ATS."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            application = db.scalar(select(Application))
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert application is not None
            assert application.channel == "company_site"
            assert application.notes == "Submitted through ATS."
            assert job is not None
            assert job.status == "applied"

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Submitted through ATS." in detail_response.text
        assert "Marked applied" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_status_form_updates_status_and_journal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Transition target", status="interested")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/status",
            data={"target_status": "preparing"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "preparing"
            assert job.archived_at is None

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Status changed from interested to preparing" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_status_form_rejects_bad_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Bad transition target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/status",
            data={"target_status": "wishlist"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Unsupported job status"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_archive_form_archives_job_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Archive target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/archive",
            data={"notes": "No longer relevant."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "archived"
            assert job.archived_at is not None

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Archived" in detail_response.text
        assert "No longer relevant." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_upload_artefact_form_stores_and_downloads_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "artefacts"))
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Artefact target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts",
            data={"kind": "cover_letter"},
            files={"file": ("cover-letter.txt", b"letter bytes", "text/plain")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            artefact = db.scalar(select(Artefact))

            assert artefact is not None
            assert artefact.filename == "cover-letter.txt"
            assert artefact.kind == "cover_letter"
            artefact_uuid = artefact.uuid

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "cover-letter.txt" in detail_response.text
        assert "Artefact uploaded" in detail_response.text

        download_response = client.get(f"/jobs/{job_uuid}/artefacts/{artefact_uuid}")

        assert download_response.status_code == 200
        assert download_response.content == b"letter bytes"
        assert download_response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "cover-letter.txt" in download_response.headers["content-disposition"]
    finally:
        app.dependency_overrides.clear()


def test_job_detail_download_hides_cross_user_artefact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "artefacts"))
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            other = create_local_user(db, email="other@example.com", password="password")
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            other_job = Job(owner_user_id=other.id, title="Private file role", status="saved")
            user_job = Job(owner_user_id=user.id, title="Visible role", status="saved")
            db.add_all([other_job, user_job])
            db.flush()
            artefact = Artefact(
                owner_user_id=other.id,
                job_id=other_job.id,
                kind="resume",
                filename="private.txt",
                content_type="text/plain",
                storage_key="jobs/private/private.txt",
                size_bytes=7,
            )
            db.add(artefact)
            db.commit()
            other_job_uuid = other_job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{other_job_uuid}/artefacts/{artefact_uuid}")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_job_detail_unarchive_form_restores_job_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Restore target",
                status="archived",
                archived_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert f'action="/jobs/{job_uuid}/unarchive"' in detail_response.text

        response = client.post(
            f"/jobs/{job_uuid}/unarchive",
            data={"target_status": "interested", "notes": "Worth another look."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "interested"
            assert job.archived_at is None

        restored_response = client.get(f"/jobs/{job_uuid}")

        assert restored_response.status_code == 200
        assert "Status changed from archived to interested" in restored_response.text
        assert "Worth another look." in restored_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_unarchive_form_rejects_archived_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Bad restore target", status="archived")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/unarchive",
            data={"target_status": "archived"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Unsupported unarchive target status"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_schedule_interview_form_creates_interview_and_redirects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Interview target", status="applied")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/interviews",
            data={
                "stage": "Hiring manager",
                "scheduled_at": "2026-04-12T18:30",
                "location": "Video call",
                "participants": "Hiring manager",
                "notes": "Review product examples.",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))
            interview = db.scalar(select(InterviewEvent))

            assert job is not None
            assert job.status == "interviewing"
            assert interview is not None
            assert interview.stage == "Hiring manager"
            assert interview.location == "Video call"

        detail_response = client.get(f"/jobs/{job_uuid}")

        assert detail_response.status_code == 200
        assert "Hiring manager" in detail_response.text
        assert "Review product examples." in detail_response.text
        assert "Interview scheduled: Hiring manager" in detail_response.text
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
