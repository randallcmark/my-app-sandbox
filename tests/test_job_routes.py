from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.db.models.application import Application
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
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

            event = db.scalar(
                select(Communication).where(
                    Communication.job_id == job.id,
                    Communication.event_type == "stage_change",
                )
            )
            assert event is not None
            assert event.owner_user_id == job.owner_user_id
            assert event.subject == "Status changed from saved to interviewing"
            assert event.notes == "Job status changed from saved to interviewing."
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


def test_update_job_board_position_only_does_not_create_stage_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.patch(f"/api/jobs/{job_uuid}/board", json={"board_position": 9})

        assert response.status_code == 200

        with session_local() as db:
            events = db.scalars(select(Communication)).all()

            assert events == []
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

            events = db.scalars(
                select(Communication).order_by(Communication.subject)
            ).all()
            assert [event.subject for event in events] == [
                "Status changed from applied to saved",
                "Status changed from saved to applied",
            ]
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


def test_job_timeline_lists_stage_change_events(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")
        update_response = client.patch(
            f"/api/jobs/{job_uuid}/board",
            json={"status": "interviewing"},
        )
        assert update_response.status_code == 200

        response = client.get(f"/api/jobs/{job_uuid}/timeline")

        assert response.status_code == 200
        assert response.json()[0]["event_type"] == "stage_change"
        assert response.json()[0]["subject"] == "Status changed from saved to interviewing"
    finally:
        app.dependency_overrides.clear()


def test_create_job_timeline_note_adds_owned_note(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{job_uuid}/timeline",
            json={"subject": "Recruiter call", "notes": "Follow up next week."},
        )

        assert response.status_code == 201
        assert response.json()["event_type"] == "note"
        assert response.json()["subject"] == "Recruiter call"
        assert response.json()["notes"] == "Follow up next week."

        timeline_response = client.get(f"/api/jobs/{job_uuid}/timeline")

        assert timeline_response.status_code == 200
        assert timeline_response.json()[0]["event_type"] == "note"
    finally:
        app.dependency_overrides.clear()


def test_create_job_timeline_note_rejects_blank_note(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{job_uuid}/timeline",
            json={"subject": "Empty", "notes": "   "},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Note text is required"
    finally:
        app.dependency_overrides.clear()


def test_create_job_timeline_note_hides_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_job_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{other_job_uuid}/timeline",
            json={"subject": "Nope", "notes": "Cannot see this."},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_job_timeline_hides_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_job_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.get(f"/api/jobs/{other_job_uuid}/timeline")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_mark_applied_creates_application_and_journal_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{job_uuid}/mark-applied",
            json={"channel": "company_site", "notes": "Used tailored resume."},
        )

        assert response.status_code == 201
        assert response.json()["created"] is True
        assert response.json()["status"] == "applied"
        assert response.json()["channel"] == "company_site"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "applied"
            assert len(job.applications) == 1
            assert job.applications[0].notes == "Used tailored resume."

            event_subjects = [
                event.subject
                for event in db.scalars(
                    select(Communication).order_by(Communication.subject)
                ).all()
            ]
            assert event_subjects == [
                "Marked applied",
                "Status changed from saved to applied",
            ]
    finally:
        app.dependency_overrides.clear()


def test_mark_applied_reuses_existing_application(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        first = client.post(
            f"/api/jobs/{job_uuid}/mark-applied",
            json={"channel": "company_site", "notes": "First submission."},
        )
        second = client.post(
            f"/api/jobs/{job_uuid}/mark-applied",
            json={"channel": "referral", "notes": "Updated channel."},
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert second.json()["channel"] == "referral"

        with session_local() as db:
            applications = db.scalars(select(Application)).all()

            assert len(applications) == 1
    finally:
        app.dependency_overrides.clear()


def test_mark_applied_hides_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_job_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{other_job_uuid}/mark-applied",
            json={"channel": "company_site"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_archive_job_moves_to_archived_and_journals_status_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(f"/api/jobs/{job_uuid}/archive", json={})

        assert response.status_code == 200
        assert response.json()["status"] == "archived"
        assert response.json()["archived_at"] is not None

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "archived"
            assert job.archived_at is not None
            events = db.scalars(select(Communication)).all()
            assert [event.subject for event in events] == [
                "Status changed from saved to archived"
            ]
    finally:
        app.dependency_overrides.clear()


def test_archive_job_can_add_archive_note(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{job_uuid}/archive",
            json={"notes": "Role closed before applying."},
        )

        assert response.status_code == 200

        timeline_response = client.get(f"/api/jobs/{job_uuid}/timeline")
        subjects = [event["subject"] for event in timeline_response.json()]

        assert "Archived" in subjects
        assert "Status changed from saved to archived" in subjects
    finally:
        app.dependency_overrides.clear()


def test_archive_job_hides_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_job_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.post(f"/api/jobs/{other_job_uuid}/archive", json={})

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_schedule_interview_creates_event_moves_job_and_journals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{job_uuid}/interviews",
            json={
                "stage": "Recruiter screen",
                "scheduled_at": "2026-04-12T18:30:00Z",
                "location": "Video call",
                "participants": "Recruiter",
                "notes": "Prepare salary range.",
            },
        )

        assert response.status_code == 201
        assert response.json()["stage"] == "Recruiter screen"
        assert response.json()["location"] == "Video call"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))
            interview = db.scalar(select(InterviewEvent))
            event_subjects = [
                event.subject
                for event in db.scalars(
                    select(Communication).order_by(Communication.subject)
                ).all()
            ]

            assert job is not None
            assert job.status == "interviewing"
            assert interview is not None
            assert interview.stage == "Recruiter screen"
            assert interview.notes == "Prepare salary range."
            assert event_subjects == [
                "Interview scheduled: Recruiter screen",
                "Status changed from saved to interviewing",
            ]
    finally:
        app.dependency_overrides.clear()


def test_schedule_interview_requires_stage(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        job_uuid = create_user_with_jobs(session_local, email="jobseeker@example.com")[0]
        login(client, "jobseeker@example.com")

        response = client.post(f"/api/jobs/{job_uuid}/interviews", json={"stage": "   "})

        assert response.status_code == 400
        assert response.json()["detail"] == "Interview stage is required"
    finally:
        app.dependency_overrides.clear()


def test_schedule_interview_hides_cross_user_job(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        other_job_uuid = create_user_with_jobs(session_local, email="other@example.com")[0]
        create_user_with_jobs(session_local, email="jobseeker@example.com")
        login(client, "jobseeker@example.com")

        response = client.post(
            f"/api/jobs/{other_job_uuid}/interviews",
            json={"stage": "Recruiter screen"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
