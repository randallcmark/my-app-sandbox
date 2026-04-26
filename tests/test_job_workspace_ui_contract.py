from datetime import UTC, datetime
from pathlib import Path

from app.auth.users import create_local_user
from app.db.models.ai_output import AiOutput
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.job_artefact_link import JobArtefactLink
from app.main import app
from tests.test_local_auth_routes import build_client


def login(client, email: str, password: str = "password") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 200


def test_job_workspace_ui_contract_renders_reference_layout_regions(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="designer@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Senior Product Manager",
                company="Google",
                status="applied",
                source="linkedin",
                source_url="https://jobs.example.com/google-pm",
                apply_url="https://jobs.example.com/google-pm/apply",
                location="Mountain View, CA",
                remote_policy="Hybrid",
                description_raw="Lead product initiatives for collaboration tooling.",
            )
            db.add(job)
            db.flush()
            db.add(
                Application(
                    owner_user_id=user.id,
                    job_id=job.id,
                    status="submitted",
                    applied_at=datetime(2026, 4, 20, 9, 14, tzinfo=UTC),
                    channel="company_site",
                )
            )
            db.add(
                InterviewEvent(
                    owner_user_id=user.id,
                    job_id=job.id,
                    stage="Recruiter Call",
                    scheduled_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
                    location="Video call",
                )
            )
            db.add(
                Communication(
                    owner_user_id=user.id,
                    job_id=job.id,
                    event_type="note",
                    direction="internal",
                    subject="Prep note",
                    notes="Research recent launches.",
                    follow_up_at=datetime(2026, 4, 27, 9, 0, tzinfo=UTC),
                )
            )
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="google-resume.md",
                storage_key="artefacts/google-resume.md",
                content_type="text/markdown",
            )
            db.add(artefact)
            db.flush()
            db.add(JobArtefactLink(owner_user_id=user.id, job_id=job.id, artefact_id=artefact.id))
            db.commit()
            job_uuid = job.uuid

        login(client, "designer@example.com")
        response = client.get(f"/jobs/{job_uuid}")

        assert response.status_code == 200
        html = response.text
        assert 'data-ui="job-workspace"' in html
        assert 'data-ui-active-section="overview"' in html
        assert 'data-ui-component="left-rail"' in html
        assert 'data-ui-component="main-column"' in html
        assert 'data-ui-component="ai-rail"' in html
        assert 'data-ui-component="section-nav"' in html
        assert 'data-ui-component="workspace-frame"' in html
        assert 'data-ui-component="utility-strip"' in html
        assert 'data-ui-component="overview-identity"' in html
        assert 'data-ui-section="overview"' in html
        assert 'data-ui-section="application"' not in html
        assert 'data-ui-section="interviews"' not in html
        assert 'data-ui-section="follow-ups"' not in html
        assert 'data-ui-section="tasks"' not in html
        assert 'data-ui-section="notes"' not in html
        assert 'data-ui-section="documents"' not in html
        assert 'data-ui-nav="overview"' in html
        assert 'data-ui-nav="application"' in html
        assert 'data-ui-nav="documents"' in html
        assert f'href="/jobs/{job_uuid}?section=application"' in html
        assert f'href="/jobs/{job_uuid}?section=documents"' in html
        assert 'data-ui-component="application-progress"' in html
        assert 'data-ui-component="next-up"' in html
        assert 'data-ui-component="quick-actions-overlay"' in html
        assert 'data-ui-component="quick-actions-trigger"' in html
        assert 'data-ui-component="quick-actions-panel"' in html
        assert 'data-ui-component="job-description-panel"' in html
        assert 'data-ui-component="job-description-body"' in html
        assert "Quick Actions" in html
        assert "Readiness" in html
        assert "Overview" in html
        assert "Next action" not in html
        assert "Workspace tools" not in html
        assert "Role &amp; notes" not in html
        assert "Execution surface" not in html
        assert "Job Workspace" not in html
    finally:
        app.dependency_overrides.clear()


def test_job_workspace_ui_contract_switches_main_surface_by_section_query(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="sectioned@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Document target",
                status="saved",
                description_raw="Document-heavy role.",
            )
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="resume.md",
                storage_key="artefacts/resume.md",
                content_type="text/markdown",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(JobArtefactLink(owner_user_id=user.id, job_id=job.id, artefact_id=artefact.id))
            db.commit()
            job_uuid = job.uuid

        login(client, "sectioned@example.com")
        response = client.get(f"/jobs/{job_uuid}?section=documents")

        assert response.status_code == 200
        html = response.text
        assert 'data-ui-active-section="documents"' in html
        assert 'data-ui-component="workspace-frame"' in html
        assert 'data-ui-component="overview-identity"' in html
        assert 'data-ui-component="utility-strip"' in html
        assert 'data-ui-section="documents"' in html
        assert 'data-ui-component="artefact-list"' in html
        assert 'data-ui-component="artefact-ai-workspace"' in html
        assert "Artefacts" in html
        assert "Analyze" in html
        assert 'data-ui-section="overview"' not in html
        assert "Role &amp; notes" not in html
    finally:
        app.dependency_overrides.clear()


def test_job_workspace_ui_contract_keeps_shared_frame_on_application_section(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="applicationframe@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Application frame target",
                company="Example Co",
                status="interested",
                source_url="https://jobs.example.com/source",
                apply_url="https://jobs.example.com/apply",
                location="Remote",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "applicationframe@example.com")
        response = client.get(f"/jobs/{job_uuid}?section=application")

        assert response.status_code == 200
        html = response.text
        assert 'data-ui-active-section="application"' in html
        assert 'data-ui-component="workspace-frame"' in html
        assert 'data-ui-component="overview-identity"' in html
        assert 'data-ui-component="utility-strip"' in html
        assert 'data-ui-section="application"' in html
        assert "Application state and route" in html
        assert 'data-ui-section="overview"' not in html
    finally:
        app.dependency_overrides.clear()


def test_job_workspace_ui_contract_tasks_section_uses_reduced_structure(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="tasksurface@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Task surface target",
                status="preparing",
                description_raw="Task-heavy role.",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "tasksurface@example.com")
        response = client.get(f"/jobs/{job_uuid}?section=tasks")

        assert response.status_code == 200
        html = response.text
        assert 'data-ui-active-section="tasks"' in html
        assert 'data-ui-component="workspace-frame"' in html
        assert 'data-ui-component="tasks-workbench"' in html
        assert "Tasks" in html
        assert "Current focus" in html
        assert "Workflow actions" in html
        assert "Follow-through" in html
        assert "Maintenance" in html
        assert "Suggest artefacts" not in html
        assert "Workspace tools" not in html
    finally:
        app.dependency_overrides.clear()


def test_job_workspace_ui_contract_keeps_ai_in_right_rail(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="ai@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="AI target",
                company="Example Co",
                status="interviewing",
                description_raw="Own product strategy.",
            )
            db.add(job)
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="fit_summary",
                    title="AI fit summary",
                    body="### Strengths\n* Strong systems thinking",
                    provider="gemini",
                    model_name="gemini-flash-latest",
                )
            )
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="recommendation",
                    title="AI next step",
                    body="### Next step\n* Prepare the recruiter screen narrative",
                    provider="gemini",
                    model_name="gemini-flash-latest",
                )
            )
            db.commit()
            job_uuid = job.uuid

        login(client, "ai@example.com")
        response = client.get(f"/jobs/{job_uuid}")

        assert response.status_code == 200
        html = response.text
        assert 'data-ui-component="ai-assessment"' in html
        assert 'data-ui-component="ai-assessment-body"' in html
        assert 'data-ui-component="ai-help-list"' in html
        assert "AI Assistant" in html
        assert "Overall Assessment" in html
        assert "AI can help you with" in html
        assert "Tailor your resume" in html
        assert "Analyze role fit" in html
        assert "AI fit summary" in html
        assert "gemini-flash-latest" in html
    finally:
        app.dependency_overrides.clear()


def test_job_workspace_ui_contract_emits_responsive_layout_rules(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="responsive@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Responsive role", status="saved", description_raw="Base description.")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "responsive@example.com")
        response = client.get(f"/jobs/{job_uuid}")

        assert response.status_code == 200
        html = response.text
        assert ".workspace-grid {" in html
        assert "grid-template-columns: 248px minmax(0, 1fr) 332px;" in html
        assert "@media (max-width: 1080px)" in html
        assert ".workspace-grid { grid-template-columns: 1fr; }" in html
        assert ".workspace-left-rail { order: 2; }" in html
        assert ".workspace-center { order: 1; }" in html
        assert ".workspace-right-rail { order: 3; }" in html
        assert "@media (max-width: 760px)" in html
        assert ".workspace-page-actions > *," in html
        assert ".workspace-progress-line {" in html
        assert ".workspace-quick-panel {" in html
        assert ".workspace-constrained-body {" in html
        assert ".ai-assessment-body {" in html
    finally:
        app.dependency_overrides.clear()
