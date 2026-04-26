import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.auth.users import create_local_user
from app.core.config import settings
from app.db.models.ai_output import AiOutput
from app.db.models.ai_provider_setting import AiProviderSetting
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.email_intake import EmailIntake
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.job_artefact_link import JobArtefactLink
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
        assert f'href="/jobs/{job_uuid}?section=application"' in response.text
        assert f'href="/jobs/{job_uuid}?section=documents"' in response.text
        assert "✦ Fit" in response.text
        assert "✦ Next step" in response.text
        assert "AI Assistant" in response.text
        assert "Generate fit summary" not in response.text
        assert "Suggest next step" not in response.text
        assert "Suggest artefacts" not in response.text
        assert "Draft tailored resume" not in response.text
        assert "Overview" in response.text
        assert "Workspace tools" not in response.text
        assert "Maintenance" not in response.text
        assert "Role &amp; notes" not in response.text
        assert 'data-ui-component="workspace-frame"' in response.text
        assert 'data-ui-component="overview-identity"' in response.text
        assert 'data-field="title"' in response.text
        assert 'data-field="description_raw"' in response.text
        assert 'id="edit-savebar"' in response.text

        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert notes_response.status_code == 200
        assert '<summary>Journal</summary>' in notes_response.text
        assert "<details class=\"timeline-panel\">" in notes_response.text
        assert 'class="local-time" datetime="2026-04-11T12:00:00+00:00"' in notes_response.text
        assert "Intl.DateTimeFormat" in notes_response.text
        assert "Status changed from applied to interviewing" in notes_response.text
        assert "Job status changed from applied to interviewing." in notes_response.text

        tasks_response = client.get(f"/jobs/{job_uuid}?section=tasks")
        assert tasks_response.status_code == 200
        assert "Tasks" in tasks_response.text
        assert "Current focus" in tasks_response.text
        assert "Workflow actions" in tasks_response.text
        assert "Maintenance" in tasks_response.text
        assert "Suggest artefacts" not in tasks_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_section_query_renders_selected_application_surface(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="section-route@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Section target",
                company="Example Co",
                status="saved",
                source_url="https://jobs.example.com/source",
                apply_url="https://jobs.example.com/apply",
                location="Remote",
                description_raw="Own the roadmap.",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "section-route@example.com")
        response = client.get(f"/jobs/{job_uuid}?section=application")

        assert response.status_code == 200
        assert 'data-ui-active-section="application"' in response.text
        assert 'data-ui-component="workspace-frame"' in response.text
        assert 'data-ui-component="overview-identity"' in response.text
        assert "Application state and route" in response.text
        assert "Open source" in response.text
        assert "Open apply link" in response.text
        assert f'action="/jobs/{job_uuid}/status"' in response.text
        assert "Role overview" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_description_markdown(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Markdown role",
                company="Example Co",
                status="saved",
                description_raw="### Responsibilities\n* **Own delivery**\n* Support stakeholders",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}")

        assert response.status_code == 200
        assert 'data-ui-component="job-description-panel"' in response.text
        assert 'data-ui-component="job-description-body"' in response.text
        assert '<div class="description-markdown">' in response.text
        assert "<h4>Responsibilities</h4>" in response.text
        assert "<strong>Own delivery</strong>" in response.text
        assert "<ul>" in response.text
        assert "<pre>### Responsibilities" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_existing_ai_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="AI target", status="saved")
            db.add(job)
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="fit_summary",
                    title="AI fit summary",
                    body="Strengths: strong systems background.",
                    provider="openai_compatible",
                    model_name="local-model",
                )
            )
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}")

        assert response.status_code == 200
        assert 'data-ui-component="ai-assessment-body"' in response.text
        assert "AI fit summary" in response.text
        assert "Strengths: strong systems background." in response.text
        assert "local-model" in response.text
        assert "Overall Assessment" in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_shortlisted_artefact_links_for_artefact_suggestion(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Artefact link target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="tpm-resume.pdf",
                storage_key="artefacts/tpm-resume.pdf",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="artefact_suggestion",
                    title="AI artefact suggestion",
                    body="### Best starting artefact\n* **tpm-resume.pdf**",
                    provider="gemini",
                    model_name="gemini-flash-latest",
                    source_context={
                        "surface": "job_workspace",
                        "prompt_contract": "artefact_suggestion_v1",
                        "shortlisted_artefact_uuids": [artefact.uuid],
                    },
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=documents")

        assert response.status_code == 200
        assert "Shortlisted artefacts" in response.text
        assert f'href="/artefacts/{artefact_uuid}/download"' in response.text
        assert "tpm-resume.pdf" in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_selected_artefact_link_for_tailoring_guidance(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Tailoring link target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="tailored-resume.pdf",
                storage_key="artefacts/tailored-resume.pdf",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                    output_type="tailoring_guidance",
                    title="AI tailoring guidance",
                    body="### Keep\n* **Programme delivery evidence**",
                    provider="system",
                    source_context={
                        "surface": "job_workspace",
                        "prompt_contract": "artefact_tailoring_v1",
                        "artefact_uuid": artefact.uuid,
                        "metadata_quality": "thin",
                        "local_fallback": True,
                        "draft_handoff_contract": "artefact_draft_seed_v1",
                    },
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=documents")

        assert response.status_code == 200
        assert "Selected artefact" in response.text
        assert f'href="/artefacts/{artefact_uuid}/download"' in response.text
        assert "tailored-resume.pdf" in response.text
        assert "metadata: thin" in response.text
        assert "Prepared for later draft generation" in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_selected_artefact_link_for_artefact_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Analysis link target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="analysis-resume.pdf",
                storage_key="artefacts/analysis-resume.pdf",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                    output_type="artefact_analysis",
                    title="AI artefact analysis",
                    body="### Artefact type and structure\n* Resume baseline",
                    provider="gemini",
                    model_name="gemini-flash-latest",
                    source_context={
                        "surface": "job_workspace",
                        "prompt_contract": "artefact_analysis_v1",
                        "artefact_uuid": artefact.uuid,
                        "content_mode": "metadata_only",
                        "inferred_requirement_summary": "Required or explicitly requested: cover letter",
                    },
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=documents")

        assert response.status_code == 200
        assert "Analyzed artefact" in response.text
        assert f'href="/artefacts/{artefact_uuid}/download"' in response.text
        assert "analysis-resume.pdf" in response.text
        assert "content: metadata_only" in response.text
        assert "Lower-confidence analysis" in response.text
        assert "Required or explicitly requested: cover letter" in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_draft_action_for_job_artefacts(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Draft action target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.md",
                storage_key="artefacts/baseline.md",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=documents")

        assert response.status_code == 200
        assert "Analyze" in response.text
        assert "Draft tailored resume" in response.text
        assert "Draft cover letter" in response.text
        assert "Draft supporting statement" in response.text
        assert "Draft attestation" in response.text
        assert f'action="/jobs/{job_uuid}/artefacts/{artefact_uuid}/analysis"' in response.text
        assert f'action="/jobs/{job_uuid}/artefacts/{artefact_uuid}/drafts"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_ai_generation_requires_enabled_provider(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="AI generation target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/ai-outputs",
            data={"output_type": "fit_summary"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_error=" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert "Enable an AI provider in Settings before generating AI output" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_ai_generation_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="AI success target", status="saved")
            db.add(job)
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="openai_compatible",
                    label="Local endpoint",
                    base_url="http://localhost:11434/v1",
                    model_name="local-model",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid

        def fake_generate_job_ai_output(db, user, job, *, output_type, profile=None):
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                output_type=output_type,
                title="AI fit summary",
                body="Strengths: shipped platform work.",
                provider="openai_compatible",
                model_name="local-model",
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_ai_output",
            fake_generate_job_ai_output,
        )

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/ai-outputs",
            data={"output_type": "fit_summary"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=AI%20output%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "AI output generated" in detail_response.text
        assert "AI fit summary" in detail_response.text
        assert "Strengths: shipped platform work." in detail_response.text

        with session_local() as db:
            outputs = db.scalars(select(AiOutput)).all()
            assert len(outputs) == 1
            assert outputs[0].job.uuid == job_uuid
            assert outputs[0].output_type == "fit_summary"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_artefact_suggestion_requires_enabled_provider_when_candidates_exist(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Artefact suggestion target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                purpose="TPM resume",
                filename="tpm-resume.pdf",
                storage_key="artefacts/tpm-resume.pdf",
            )
            db.add(job)
            db.add(artefact)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefact-suggestions",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_error=" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert "Enable an AI provider in Settings before generating AI output" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_artefact_suggestion_uses_local_fallback_when_no_candidates(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Sparse artefact target",
                status="saved",
                description_raw="Please include a cover letter.",
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefact-suggestions",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Artefact%20suggestion%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "No existing artefact is available yet" in detail_response.text
        assert "cover letter" in detail_response.text

        with session_local() as db:
            outputs = db.scalars(select(AiOutput)).all()
            assert len(outputs) == 1
            assert outputs[0].provider == "system"
            assert outputs[0].source_context["local_fallback"] is True
    finally:
        app.dependency_overrides.clear()


def test_job_detail_artefact_suggestion_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Artefact suggestion success", status="saved")
            db.add(job)
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="gemini",
                    label="AI Studio",
                    model_name="gemini-flash-latest",
                    api_key_encrypted="sealed",
                    api_key_hint="key...1234",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid

        def fake_generate_job_artefact_suggestion(db, user, job, *, profile=None, shortlist_limit=5):
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                output_type="artefact_suggestion",
                title="AI artefact suggestion",
                body="### Best starting artefact\n* **tpm-resume.pdf**",
                provider="gemini",
                model_name="gemini-flash-latest",
                source_context={
                    "surface": "job_workspace",
                    "prompt_contract": "artefact_suggestion_v1",
                    "shortlisted_artefact_uuids": [],
                },
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_artefact_suggestion",
            fake_generate_job_artefact_suggestion,
        )

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefact-suggestions",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Artefact%20suggestion%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Artefact suggestion generated" in detail_response.text
        assert "AI artefact suggestion" in detail_response.text
        assert "tpm-resume.pdf" in detail_response.text

        with session_local() as db:
            outputs = db.scalars(select(AiOutput)).all()
            assert len(outputs) == 1
            assert outputs[0].job.uuid == job_uuid
            assert outputs[0].output_type == "artefact_suggestion"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_tailoring_guidance_requires_owned_job_artefact(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other_user = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Tailor target", status="saved")
            other_job = Job(owner_user_id=other_user.id, title="Hidden target", status="saved")
            artefact = Artefact(
                owner_user_id=other_user.id,
                job_id=other_job.id,
                kind="resume",
                filename="hidden-resume.pdf",
                storage_key="artefacts/hidden-resume.pdf",
            )
            db.add_all([job, other_job, artefact])
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/tailoring-guidance",
            follow_redirects=False,
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_job_detail_tailoring_guidance_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Tailoring success", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                purpose="TPM resume",
                filename="tpm-resume.pdf",
                storage_key="artefacts/tpm-resume.pdf",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="artefact_suggestion",
                    title="AI artefact suggestion",
                    body="### Best starting artefact\n* **tpm-resume.pdf**",
                )
            )
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="gemini",
                    label="AI Studio",
                    model_name="gemini-flash-latest",
                    api_key_encrypted="sealed",
                    api_key_hint="key...1234",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        def fake_generate_job_artefact_tailoring_guidance(
            db, user, job, artefact, *, profile=None, prior_suggestion=None
        ):
            assert artefact.uuid == artefact_uuid
            assert prior_suggestion is not None
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
                output_type="tailoring_guidance",
                title="AI tailoring guidance",
                body="### Keep\n* **Programme delivery evidence**",
                provider="gemini",
                model_name="gemini-flash-latest",
                source_context={
                    "surface": "job_workspace",
                    "artefact_uuid": artefact.uuid,
                    "prompt_contract": "artefact_tailoring_v1",
                    "used_extracted_text": False,
                },
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_artefact_tailoring_guidance",
            fake_generate_job_artefact_tailoring_guidance,
        )

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/tailoring-guidance",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Tailoring%20guidance%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Tailoring guidance generated" in detail_response.text
        assert "AI tailoring guidance" in detail_response.text
        assert "Programme delivery evidence" in detail_response.text

        with session_local() as db:
            outputs = db.scalars(select(AiOutput).where(AiOutput.output_type == "tailoring_guidance")).all()
            assert len(outputs) == 1
            assert outputs[0].job.uuid == job_uuid
            assert outputs[0].artefact.uuid == artefact_uuid
    finally:
        app.dependency_overrides.clear()


def test_job_detail_artefact_analysis_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Analysis route target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.pdf",
                storage_key="artefacts/baseline.pdf",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="gemini",
                    model_name="gemini-flash-latest",
                    api_key_encrypted="sealed",
                    api_key_hint="key...1234",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        def fake_generate_job_artefact_analysis(db, user, job, artefact, *, profile=None):
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
                output_type="artefact_analysis",
                title="AI artefact analysis",
                body="### Artefact type and structure\n* Resume baseline",
                provider="gemini",
                model_name="gemini-flash-latest",
                status="active",
                source_context={
                    "surface": "job_workspace",
                    "prompt_contract": "artefact_analysis_v1",
                    "artefact_uuid": artefact.uuid,
                    "content_mode": "provider_document",
                    "inferred_requirement_summary": "No explicit additional artefact requirement was detected in the job text.",
                },
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_artefact_analysis",
            fake_generate_job_artefact_analysis,
        )

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/analysis",
            data={},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Artefact%20analysis%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert "AI artefact analysis" in detail_response.text
        assert "Artefact type and structure" in detail_response.text

        with session_local() as db:
            outputs = db.scalars(select(AiOutput).where(AiOutput.output_type == "artefact_analysis")).all()
            assert len(outputs) == 1
            assert outputs[0].source_context["prompt_contract"] == "artefact_analysis_v1"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_tailoring_guidance_uses_local_fallback_when_selected_artefact_is_thin(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Thin tailoring target",
                status="saved",
                description_raw="Please include an attestation.",
            )
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="thin-resume.pdf",
                storage_key="artefacts/thin-resume.pdf",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/tailoring-guidance",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Tailoring%20guidance%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Tailoring is currently working from metadata only" in detail_response.text
        assert "attestation" in detail_response.text

        with session_local() as db:
            output = db.scalar(select(AiOutput).where(AiOutput.output_type == "tailoring_guidance"))
            assert output is not None
            assert output.provider == "system"
            assert output.source_context["local_fallback"] is True
            assert output.source_context["artefact_uuid"] == artefact_uuid
    finally:
        app.dependency_overrides.clear()


def test_job_detail_artefact_draft_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Draft success", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.md",
                storage_key="artefacts/baseline.md",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                    output_type="tailoring_guidance",
                    title="AI tailoring guidance",
                    body="### Keep\n* **Programme delivery evidence**",
                )
            )
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="gemini",
                    label="AI Studio",
                    model_name="gemini-flash-latest",
                    api_key_encrypted="sealed",
                    api_key_hint="key...1234",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        def fake_generate_job_artefact_draft(
            db, user, job, artefact, *, draft_kind, profile=None, tailoring_guidance=None, prior_suggestion=None
        ):
            assert artefact.uuid == artefact_uuid
            assert draft_kind == "resume_draft"
            assert tailoring_guidance is not None
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
                output_type="draft",
                title="AI tailored resume draft",
                body="### Headline\nTechnical Program Manager",
                provider="gemini",
                model_name="gemini-flash-latest",
                source_context={
                    "surface": "job_workspace",
                    "artefact_uuid": artefact.uuid,
                    "prompt_contract": "artefact_draft_v1",
                    "draft_kind": "resume_draft",
                    "content_mode": "metadata_only",
                },
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_artefact_draft",
            fake_generate_job_artefact_draft,
        )

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/drafts",
            data={"draft_kind": "resume_draft"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Draft%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Draft generated" in detail_response.text
        assert "AI tailored resume draft" in detail_response.text
        assert "Technical Program Manager" in detail_response.text
        assert "content: metadata_only" in detail_response.text
        assert "Low-confidence draft" in detail_response.text

        with session_local() as db:
            outputs = db.scalars(select(AiOutput).where(AiOutput.output_type == "draft")).all()
            assert len(outputs) == 1
            assert outputs[0].job.uuid == job_uuid
            assert outputs[0].artefact.uuid == artefact_uuid
    finally:
        app.dependency_overrides.clear()


def test_job_detail_cover_letter_draft_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Cover letter draft", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.md",
                storage_key="artefacts/baseline.md",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="gemini",
                    label="AI Studio",
                    model_name="gemini-flash-latest",
                    api_key_encrypted="sealed",
                    api_key_hint="key...1234",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        def fake_generate_job_artefact_draft(
            db, user, job, artefact, *, draft_kind, profile=None, tailoring_guidance=None, prior_suggestion=None
        ):
            assert artefact.uuid == artefact_uuid
            assert draft_kind == "cover_letter_draft"
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
                output_type="draft",
                title="AI cover letter draft",
                body="### Opening\nDear Hiring Team,",
                provider="gemini",
                model_name="gemini-flash-latest",
                source_context={
                    "surface": "job_workspace",
                    "artefact_uuid": artefact.uuid,
                    "prompt_contract": "artefact_draft_v1",
                    "draft_kind": "cover_letter_draft",
                    "content_mode": "metadata_only",
                },
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_artefact_draft",
            fake_generate_job_artefact_draft,
        )

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/drafts",
            data={"draft_kind": "cover_letter_draft"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Draft%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "AI cover letter draft" in detail_response.text
        assert "Dear Hiring Team" in detail_response.text
        assert "content: metadata_only" in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_supporting_statement_draft_creates_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Supporting statement draft", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.md",
                storage_key="artefacts/baseline.md",
            )
            db.add_all([job, artefact])
            db.flush()
            db.add(
                JobArtefactLink(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=artefact.id,
                )
            )
            db.add(
                AiProviderSetting(
                    owner_user_id=user.id,
                    provider="gemini",
                    label="AI Studio",
                    model_name="gemini-flash-latest",
                    api_key_encrypted="sealed",
                    api_key_hint="key...1234",
                    is_enabled=True,
                )
            )
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        def fake_generate_job_artefact_draft(
            db, user, job, artefact, *, draft_kind, profile=None, tailoring_guidance=None, prior_suggestion=None
        ):
            assert artefact.uuid == artefact_uuid
            assert draft_kind == "supporting_statement_draft"
            output = AiOutput(
                owner_user_id=user.id,
                job_id=job.id,
                artefact_id=artefact.id,
                output_type="draft",
                title="AI supporting statement draft",
                body="### Fit summary\nPlatform delivery and stakeholder leadership.",
                provider="gemini",
                model_name="gemini-flash-latest",
                source_context={
                    "surface": "job_workspace",
                    "artefact_uuid": artefact.uuid,
                    "prompt_contract": "artefact_draft_v1",
                    "draft_kind": "supporting_statement_draft",
                    "content_mode": "metadata_only",
                },
            )
            db.add(output)
            db.flush()
            return output

        monkeypatch.setattr(
            "app.api.routes.job_detail.generate_job_artefact_draft",
            fake_generate_job_artefact_draft,
        )

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/artefacts/{artefact_uuid}/drafts",
            data={"draft_kind": "supporting_statement_draft"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Draft%20generated" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "AI supporting statement draft" in detail_response.text
        assert "Platform delivery and stakeholder leadership." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_save_draft_action_for_draft_outputs(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Save draft target", status="saved")
            db.add(job)
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="draft",
                    title="AI tailored resume draft",
                    body="### Headline\nTechnical Program Manager",
                    provider="gemini",
                    model_name="gemini-flash-latest",
                    source_context={
                        "draft_kind": "resume_draft",
                        "content_mode": "metadata_only",
                    },
                )
            )
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=documents")

        assert response.status_code == 200
        assert "Save as artefact" in response.text
        assert f'action="/jobs/{job_uuid}/ai-outputs/' in response.text
        assert '/save-draft"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_save_draft_as_artefact_creates_markdown_artefact(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Principal TPM", status="saved")
            baseline = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.md",
                storage_key="artefacts/baseline.md",
            )
            db.add_all([job, baseline])
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=baseline.id,
                    output_type="draft",
                    title="AI tailored resume draft",
                    body="### Headline\nTechnical Program Manager",
                    source_context={
                        "draft_kind": "resume_draft",
                        "artefact_uuid": baseline.uuid,
                    },
                )
            )
            db.commit()
            job_uuid = job.uuid
            baseline_uuid = baseline.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/ai-outputs/1/save-draft",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=Draft%20saved%20as%20artefact" in response.headers["location"]

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Draft saved as artefact" in detail_response.text

        with session_local() as db:
            artefacts = db.scalars(select(Artefact).order_by(Artefact.id)).all()
            assert len(artefacts) == 2
            saved = artefacts[1]
            assert saved.kind == "resume"
            assert saved.filename == "principal-tpm-resume-draft.md"
            assert saved.content_type == "text/markdown"
            assert saved.purpose == "AI tailored resume draft"
            assert saved.version_label == "ai-draft-v1"
            assert baseline_uuid in (saved.notes or "")
            output = db.scalar(select(AiOutput).where(AiOutput.output_type == "draft"))
            assert output is not None
            assert output.source_context["saved_artefact_uuid"] == saved.uuid
    finally:
        app.dependency_overrides.clear()


def test_job_detail_save_cover_letter_draft_as_matching_artefact_kind(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Senior Product Manager", status="saved")
            baseline = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="baseline.md",
                storage_key="artefacts/baseline.md",
            )
            db.add_all([job, baseline])
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    artefact_id=baseline.id,
                    output_type="draft",
                    title="AI cover letter draft",
                    body="### Opening\nDear Hiring Team,",
                    source_context={
                        "draft_kind": "cover_letter_draft",
                        "artefact_uuid": baseline.uuid,
                    },
                )
            )
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/ai-outputs/1/save-draft",
            follow_redirects=False,
        )

        assert response.status_code == 303

        with session_local() as db:
            artefacts = db.scalars(select(Artefact).order_by(Artefact.id)).all()
            assert len(artefacts) == 2
            saved = artefacts[1]
            assert saved.kind == "cover_letter"
            assert saved.filename == "senior-product-manager-cover-letter-draft.md"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_ai_generation_uses_openai_provider_with_saved_key(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="OpenAI target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "password"},
            follow_redirects=False,
        )
        provider_response = client.post(
            "/settings/ai-provider",
            data={
                "provider": "openai",
                "label": "Personal OpenAI",
                "base_url": "",
                "model_name": "gpt-5",
                "api_key": "sk-openai-secret-1234",
                "is_enabled": "true",
            },
            follow_redirects=False,
        )
        assert provider_response.status_code == 303

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"output_text": "Next step: tailor the resume first."}).encode("utf-8")

        def fake_urlopen(req, timeout=20, context=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse()

        monkeypatch.setattr("app.services.ai.request.urlopen", fake_urlopen)

        response = client.post(
            f"/jobs/{job_uuid}/ai-outputs",
            data={"output_type": "recommendation"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=AI%20output%20generated" in response.headers["location"]
        assert captured["url"] == "https://api.openai.com/v1/responses"
        assert captured["headers"]["Authorization"] == "Bearer sk-openai-secret-1234"
        assert captured["body"]["model"] == "gpt-5"

        detail_response = client.get(response.headers["location"])
        assert "Next step: tailor the resume first." in detail_response.text

        with session_local() as db:
            output = db.scalar(select(AiOutput))
            assert output is not None
            assert output.provider == "openai"
            assert output.model_name == "gpt-5"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_ai_generation_uses_gemini_provider_with_saved_key(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Gemini target", status="saved")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        client.post(
            "/login",
            data={"email": "jobseeker@example.com", "password": "password"},
            follow_redirects=False,
        )
        provider_response = client.post(
            "/settings/ai-provider",
            data={
                "provider": "gemini",
                "label": "AI Studio",
                "base_url": "",
                "model_name": "gemini-2.5-flash",
                "api_key": "gemini-secret-1234",
                "is_enabled": "true",
            },
            follow_redirects=False,
        )
        assert provider_response.status_code == 303

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": "Strengths: matches the role well."}
                                    ]
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(req, timeout=20, context=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse()

        monkeypatch.setattr("app.services.ai.request.urlopen", fake_urlopen)

        response = client.post(
            f"/jobs/{job_uuid}/ai-outputs",
            data={"output_type": "fit_summary"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "ai_status=AI%20output%20generated" in response.headers["location"]
        assert (
            captured["url"]
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        )
        headers = {key.lower(): value for key, value in captured["headers"].items()}
        assert headers["x-goog-api-key"] == "gemini-secret-1234"
        assert captured["body"]["generationConfig"]["temperature"] == 0.2

        detail_response = client.get(response.headers["location"])
        assert "Strengths: matches the role well." in detail_response.text

        with session_local() as db:
            output = db.scalar(select(AiOutput))
            assert output is not None
            assert output.provider == "gemini"
            assert output.model_name == "gemini-2.5-flash"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_renders_ai_output_markdown(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Markdown target", status="saved")
            db.add(job)
            db.flush()
            db.add(
                AiOutput(
                    owner_user_id=user.id,
                    job_id=job.id,
                    output_type="fit_summary",
                    title="AI fit summary",
                    body="### Strengths\n* **Role alignment**\n* Remote match",
                    provider="gemini",
                    model_name="gemini-flash-latest",
                )
            )
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=notes")

        assert response.status_code == 200
        assert '<div class="ai-markdown">' in response.text
        assert "<h4>Strengths</h4>" in response.text
        assert "<strong>Role alignment</strong>" in response.text
        assert "<ul>" in response.text
        assert "<pre>" not in response.text
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


def test_job_detail_shows_collapsed_email_provenance(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            email = EmailIntake(
                owner_user_id=user.id,
                subject="Interesting role",
                sender="jobs@example.com",
                body_text="Role from email https://jobs.example.com/email",
            )
            db.add(email)
            db.flush()
            job = Job(
                owner_user_id=user.id,
                email_intake_id=email.id,
                title="Email role",
                status="saved",
                source_url="https://jobs.example.com/email",
                intake_source="email_capture",
                intake_confidence="unknown",
                intake_state="needs_review",
                structured_data={
                    "email_capture": {
                        "extracted_urls": ["https://jobs.example.com/email"],
                    }
                },
            )
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/jobs/{job_uuid}?section=notes")

        assert response.status_code == 200
        assert "<summary>Capture provenance</summary>" in response.text
        assert "Interesting role" in response.text
        assert "jobs@example.com" in response.text
        assert "https://jobs.example.com/email" in response.text
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
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=notes"

        detail_response = client.get(response.headers["location"])

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

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        assert "Corrected role" in detail_response.text
        assert "Corrected description." in detail_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Status changed from saved to interested" in notes_response.text
        assert "Job edited" in notes_response.text
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
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=application"

        with session_local() as db:
            application = db.scalar(select(Application))
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert application is not None
            assert application.channel == "company_site"
            assert application.notes == "Submitted through ATS."
            assert job is not None
            assert job.status == "applied"

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        assert "Submitted through ATS." in detail_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Marked applied" in notes_response.text
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
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=application"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "preparing"
            assert job.archived_at is None

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Status changed from interested to preparing" in notes_response.text
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


def test_job_detail_application_started_moves_status_and_records_note(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Application started target", status="interested")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/application-started",
            data={"notes": "Started tailoring a resume and opening the ATS flow."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=follow-ups"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "preparing"
            assert any(note.subject == "Application started" for note in job.communications)

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Application started" in detail_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Status changed from interested to preparing" in notes_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_blocker_form_adds_note_with_optional_follow_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Blocker target", status="preparing")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/blockers",
            data={"notes": "Waiting for referral confirmation.", "follow_up_at": "2026-04-22"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=follow-ups"

        with session_local() as db:
            blocker_note = db.scalar(
                select(Communication).where(Communication.subject == "Blocker recorded")
            )
            assert blocker_note is not None
            assert blocker_note.notes == "Waiting for referral confirmation."
            assert blocker_note.follow_up_at is not None

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Blocker recorded" in detail_response.text
        assert "Waiting for referral confirmation." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_blocker_form_rejects_blank_note(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Bad blocker target", status="preparing")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/blockers",
            data={"notes": "   "},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Blocker note is required"
    finally:
        app.dependency_overrides.clear()


def test_job_detail_return_note_form_adds_note_and_follow_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Return note target", status="applied")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/return-note",
            data={
                "notes": "Completed the external form and uploaded portfolio links.",
                "follow_up_at": "2026-04-23",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=follow-ups"

        with session_local() as db:
            return_note = db.scalar(select(Communication).where(Communication.subject == "Return note"))
            assert return_note is not None
            assert return_note.notes == "Completed the external form and uploaded portfolio links."
            assert return_note.follow_up_at is not None

        detail_response = client.get(response.headers["location"])
        assert detail_response.status_code == 200
        assert "Return note" in detail_response.text
        assert "Completed the external form and uploaded portfolio links." in detail_response.text
    finally:
        app.dependency_overrides.clear()


def test_job_detail_return_note_form_rejects_blank_note(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Bad return note target", status="applied")
            db.add(job)
            db.commit()
            job_uuid = job.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/jobs/{job_uuid}/return-note",
            data={"notes": "  "},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Return note is required"
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
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=notes"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "archived"
            assert job.archived_at is not None

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        assert "Archived" in detail_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "No longer relevant." in notes_response.text
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
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=documents"

        with session_local() as db:
            artefact = db.scalar(select(Artefact))

            assert artefact is not None
            assert artefact.filename == "cover-letter.txt"
            assert artefact.kind == "cover_letter"
            artefact_uuid = artefact.uuid

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        assert "cover-letter.txt" in detail_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Artefact uploaded" in notes_response.text

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

        detail_response = client.get(f"/jobs/{job_uuid}?section=tasks")

        assert detail_response.status_code == 200
        assert f'action="/jobs/{job_uuid}/unarchive"' in detail_response.text

        response = client.post(
            f"/jobs/{job_uuid}/unarchive",
            data={"target_status": "interested", "notes": "Worth another look."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=notes"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))

            assert job is not None
            assert job.status == "interested"
            assert job.archived_at is None

        restored_response = client.get(response.headers["location"])

        assert restored_response.status_code == 200
        assert "Worth another look." in restored_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Status changed from archived to interested" in notes_response.text
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
        assert response.headers["location"] == f"/jobs/{job_uuid}?section=interviews"

        with session_local() as db:
            job = db.scalar(select(Job).where(Job.uuid == job_uuid))
            interview = db.scalar(select(InterviewEvent))

            assert job is not None
            assert job.status == "interviewing"
            assert interview is not None
            assert interview.stage == "Hiring manager"
            assert interview.location == "Video call"

        detail_response = client.get(response.headers["location"])

        assert detail_response.status_code == 200
        assert "Hiring manager" in detail_response.text
        assert "Review product examples." in detail_response.text
        notes_response = client.get(f"/jobs/{job_uuid}?section=notes")
        assert "Interview scheduled: Hiring manager" in notes_response.text
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
