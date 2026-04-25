from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

from app.auth.users import create_local_user
from app.db.models.ai_output import AiOutput
from app.db.models.job import Job
from app.db.models.ai_provider_setting import AiProviderSetting
from app.db.models.user_profile import UserProfile
from app.db.models.artefact import Artefact
from app.db.models.user import User
from app.main import app
from app.services.ai import (
    _call_gemini,
    _build_artefact_draft_prompt,
    _build_artefact_tailoring_prompt,
    _build_artefact_suggestion_prompt,
    _build_job_prompt,
    _http_error_message,
    _timeout_error_message,
    _url_error_message,
    AiExecutionError,
    generate_job_artefact_draft,
    generate_job_artefact_tailoring_guidance,
    generate_job_artefact_suggestion,
)
from app.services.artefacts import load_artefact_text_excerpt
from tests.test_local_auth_routes import build_client


def _setting(provider: str, *, base_url: str | None = None) -> AiProviderSetting:
    return AiProviderSetting(provider=provider, base_url=base_url)


def _http_error(code: int, body: str, *, reason: str = "error") -> HTTPError:
    return HTTPError(
        url="https://example.test",
        code=code,
        msg=reason,
        hdrs=None,
        fp=BytesIO(body.encode("utf-8")),
    )


def test_http_error_message_maps_openai_quota_errors() -> None:
    setting = _setting("openai")
    exc = _http_error(
        429,
        '{"error":{"message":"You exceeded your current quota, please check your plan and billing details.","type":"insufficient_quota","code":"insufficient_quota"}}',
        reason="Too Many Requests",
    )

    message = _http_error_message(setting, exc)

    assert "OpenAI accepted the key" in message
    assert "no available API quota" in message


def test_http_error_message_maps_gemini_model_not_found() -> None:
    setting = _setting("gemini")
    exc = _http_error(
        404,
        '{"error":{"code":404,"message":"models/gemini-missing is not found for API version v1beta, or is not supported for generateContent.","status":"NOT_FOUND"}}',
        reason="Not Found",
    )

    message = _http_error_message(setting, exc)

    assert "Google Gemini could not find that model" in message
    assert "model name in Settings" in message


def test_http_error_message_maps_endpoint_not_found() -> None:
    setting = _setting("gemini", base_url="https://generativelanguage.googleapis.com/v1beta/models")
    exc = _http_error(404, "Not Found", reason="Not Found")

    message = _http_error_message(setting, exc)

    assert "endpoint was not found" in message
    assert "Base URL in Settings" in message


def test_http_error_message_maps_auth_errors() -> None:
    setting = _setting("gemini")
    exc = _http_error(401, '{"error":{"message":"Request had invalid authentication credentials."}}', reason="Unauthorized")

    message = _http_error_message(setting, exc)

    assert "rejected the API key" in message


def test_url_error_message_maps_tls_certificate_failures() -> None:
    setting = _setting("openai")
    exc = URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    message = _url_error_message(setting, exc)

    assert "TLS certificate validation failed" in message


def test_url_error_message_maps_generic_connectivity_failures() -> None:
    setting = _setting("openai_compatible")
    exc = URLError("Connection refused")

    message = _url_error_message(setting, exc)

    assert "Could not reach OpenAI-compatible provider" in message
    assert "Base URL in Settings" in message


def test_timeout_error_message_maps_provider_timeouts() -> None:
    setting = _setting("gemini")

    message = _timeout_error_message(setting)

    assert "Google Gemini timed out before returning a response" in message
    assert "reduce the request size" in message


def test_build_job_prompt_uses_focus_specific_recommendation_instruction() -> None:
    profile = UserProfile(target_roles="Technical Program Manager", target_locations="Remote UK")
    job = Job(
        title="Staff TPM",
        company="Example Co",
        status="applied",
        location="Remote",
        description_raw="Lead cross-functional delivery.",
    )

    title, prompt = _build_job_prompt(
        "recommendation",
        profile=profile,
        job=job,
        surface="focus",
    )

    assert title == "AI next-step recommendation"
    assert "This recommendation is for the Focus surface" in prompt
    assert "Recommend exactly one concrete next action" in prompt
    assert "Why this now" in prompt
    assert "Do not suggest status changes or multiple parallel tasks" in prompt
    assert "Target roles: Technical Program Manager" in prompt
    assert "Title: Staff TPM" in prompt


def test_build_job_prompt_keeps_default_recommendation_instruction_for_non_focus_surfaces() -> None:
    job = Job(title="Generalist role", status="saved")

    _, prompt = _build_job_prompt(
        "recommendation",
        profile=None,
        job=job,
    )

    assert "This recommendation is for the Focus surface" not in prompt
    assert "Why now" in prompt
    assert "No user profile is configured." in prompt


def test_build_artefact_suggestion_prompt_includes_candidate_summaries() -> None:
    profile = UserProfile(target_roles="Technical Program Manager")
    job = Job(title="Staff TPM", status="saved", description_raw="Lead cross-functional delivery.")
    candidate = type("Candidate", (), {
        "summary_text": "Kind: resume | Filename: tpm-resume.pdf | Linked jobs: 2",
        "artefact_uuid": "artefact-1",
    })()

    title, prompt = _build_artefact_suggestion_prompt(
        profile=profile,
        job=job,
        candidates=[candidate],
    )

    assert title == "AI artefact suggestion"
    assert "Best starting artefact" in prompt
    assert "Candidate 1:" in prompt
    assert "Kind: resume | Filename: tpm-resume.pdf" in prompt
    assert "Target roles: Technical Program Manager" in prompt
    assert "Title: Staff TPM" in prompt


def test_build_artefact_suggestion_prompt_handles_empty_candidate_list() -> None:
    job = Job(title="No artefacts role", status="saved")

    _, prompt = _build_artefact_suggestion_prompt(
        profile=None,
        job=job,
        candidates=[],
    )

    assert "No existing artefacts are available for this user." in prompt
    assert "Prefer 'no suitable artefact' over weak guesses." in prompt


def test_generate_job_artefact_suggestion_stores_visible_output(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Staff TPM", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                purpose="TPM resume",
                version_label="v3",
                notes="Used for senior platform roles.",
                outcome_context="Helped reach interview loop.",
                filename="tpm-resume.pdf",
                storage_key="artefacts/tpm-resume.pdf",
            )
            setting = AiProviderSetting(
                owner_user_id=user.id,
                provider="gemini",
                model_name="gemini-flash-latest",
                api_key_encrypted="sealed",
                api_key_hint="key...1234",
                is_enabled=True,
            )
            db.add_all([job, artefact, setting])
            db.commit()
            user_id = user.id
            job_id = job.id

        def fake_execute_prompt(setting, prompt):
            assert "Candidate artefacts:" in prompt
            assert "tpm-resume.pdf" in prompt
            return "### Best starting artefact\n* **tpm-resume.pdf**"

        monkeypatch.setattr("app.services.ai._execute_prompt", fake_execute_prompt)

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)

            output = generate_job_artefact_suggestion(db, user, job)
            db.commit()

            assert output.output_type == "artefact_suggestion"
            assert output.title == "AI artefact suggestion"
            assert output.source_context["surface"] == "job_workspace"
            assert output.source_context["prompt_contract"] == "artefact_suggestion_v1"
            assert len(output.source_context["shortlisted_artefact_uuids"]) == 1

            stored = db.get(AiOutput, output.id)
            assert stored is not None
            assert stored.body == "### Best starting artefact\n* **tpm-resume.pdf**"
    finally:
        app.dependency_overrides.clear()


def test_generate_job_artefact_suggestion_uses_local_fallback_when_no_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="No artefacts role",
                status="saved",
                description_raw="Please submit a cover letter and supporting statement.",
            )
            db.add(job)
            db.commit()
            user_id = user.id
            job_id = job.id

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)

            output = generate_job_artefact_suggestion(db, user, job)
            db.commit()

            assert output.output_type == "artefact_suggestion"
            assert output.provider == "system"
            assert output.source_context["local_fallback"] is True
            assert output.source_context["shortlisted_artefact_uuids"] == []
            assert "No existing artefact is available yet" in output.body
            assert "cover letter, supporting statement" in output.body
    finally:
        app.dependency_overrides.clear()


def test_build_artefact_tailoring_prompt_uses_selected_artefact_context() -> None:
    profile = UserProfile(target_roles="Technical Program Manager")
    job = Job(title="Staff TPM", status="saved", description_raw="Lead delivery.")
    artefact = Artefact(
        kind="resume",
        purpose="TPM resume",
        filename="tpm-resume.pdf",
        storage_key="artefacts/tpm-resume.pdf",
    )
    candidate = type("Candidate", (), {
        "summary_text": "Kind: resume | Filename: tpm-resume.pdf | Metadata quality: strong",
    })()
    prior = AiOutput(body="### Best starting artefact\n* **tpm-resume.pdf**")

    title, prompt = _build_artefact_tailoring_prompt(
        profile=profile,
        job=job,
        artefact=artefact,
        artefact_summary=candidate,
        prior_suggestion=prior,
    )

    assert title == "AI tailoring guidance"
    assert "sections titled 'Keep', 'Strengthen', 'De-emphasise or remove'" in prompt
    assert "Selected artefact:" in prompt
    assert "Filename: tpm-resume.pdf" in prompt
    assert "Prior artefact suggestion:" in prompt
    assert "Target roles: Technical Program Manager" in prompt


def test_build_artefact_draft_prompt_includes_content_mode_and_tailoring_guidance() -> None:
    profile = UserProfile(target_roles="Technical Program Manager")
    job = Job(title="Staff TPM", status="saved", description_raw="Lead delivery.")
    candidate = type("Candidate", (), {
        "summary_text": "Kind: resume | Filename: tpm-resume.pdf | Metadata quality: strong",
    })()
    tailoring = AiOutput(body="### Keep\n* **Programme delivery**")

    title, prompt = _build_artefact_draft_prompt(
        profile=profile,
        job=job,
        artefact_summary=candidate,
        draft_kind="resume_draft",
        content_mode="extracted_text",
        extracted_text="# Resume\n\nPlatform delivery",
        tailoring_guidance=tailoring,
    )

    assert title == "AI tailored resume draft"
    assert "Content mode: extracted_text" in prompt
    assert "Verified extracted artefact text:" in prompt
    assert "Tailoring guidance:" in prompt
    assert "Platform delivery" in prompt


def test_build_cover_letter_draft_prompt_uses_cover_letter_contract() -> None:
    job = Job(title="Staff TPM", company="Example Co", status="saved")
    candidate = type("Candidate", (), {
        "summary_text": "Kind: resume | Filename: tpm-resume.pdf | Metadata quality: strong",
    })()

    title, prompt = _build_artefact_draft_prompt(
        profile=None,
        job=job,
        artefact_summary=candidate,
        draft_kind="cover_letter_draft",
        content_mode="metadata_only",
    )

    assert title == "AI cover letter draft"
    assert "Draft a concise cover letter for this job" in prompt
    assert "Content mode: metadata_only" in prompt
    assert "Baseline artefact content is unavailable. Reason from metadata only." in prompt


def test_build_supporting_statement_draft_prompt_uses_statement_contract() -> None:
    job = Job(title="Staff TPM", company="Example Co", status="saved")
    candidate = type("Candidate", (), {
        "summary_text": "Kind: resume | Filename: tpm-resume.pdf | Metadata quality: strong",
    })()

    title, prompt = _build_artefact_draft_prompt(
        profile=None,
        job=job,
        artefact_summary=candidate,
        draft_kind="supporting_statement_draft",
        content_mode="metadata_only",
    )

    assert title == "AI supporting statement draft"
    assert "Draft a targeted supporting statement for this job" in prompt
    assert "Content mode: metadata_only" in prompt


def test_generate_job_artefact_tailoring_guidance_stores_visible_output(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Staff TPM", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                purpose="TPM resume",
                version_label="v3",
                notes="Used for senior platform roles.",
                outcome_context="Helped reach interview loop.",
                filename="tpm-resume.pdf",
                storage_key="artefacts/tpm-resume.pdf",
            )
            setting = AiProviderSetting(
                owner_user_id=user.id,
                provider="gemini",
                model_name="gemini-flash-latest",
                api_key_encrypted="sealed",
                api_key_hint="key...1234",
                is_enabled=True,
            )
            db.add_all([job, artefact, setting])
            db.commit()
            user_id = user.id
            job_id = job.id
            artefact_id = artefact.id

        def fake_execute_prompt(setting, prompt, *, document=None):
            assert "Selected artefact:" in prompt
            assert "tpm-resume.pdf" in prompt
            return "### Keep\n* **Programme delivery evidence**"

        monkeypatch.setattr("app.services.ai._execute_prompt", fake_execute_prompt)

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)
            artefact = db.get(Artefact, artefact_id)

            output = generate_job_artefact_tailoring_guidance(db, user, job, artefact)
            db.commit()

            assert output.output_type == "tailoring_guidance"
            assert output.artefact_id == artefact_id
            assert output.title == "AI tailoring guidance"
            assert output.source_context["prompt_contract"] == "artefact_tailoring_v1"
            assert output.source_context["artefact_uuid"] == artefact.uuid
            assert output.source_context["used_extracted_text"] is False
            assert output.source_context["draft_handoff_contract"] == "artefact_draft_seed_v1"

            stored = db.get(AiOutput, output.id)
            assert stored is not None
            assert stored.body == "### Keep\n* **Programme delivery evidence**"
    finally:
        app.dependency_overrides.clear()


def test_generate_job_artefact_tailoring_guidance_uses_local_fallback_for_thin_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(
                owner_user_id=user.id,
                title="Sparse tailoring target",
                status="saved",
                description_raw="Please include a supporting statement.",
            )
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                filename="baseline-resume.pdf",
                storage_key="artefacts/baseline-resume.pdf",
            )
            db.add_all([job, artefact])
            db.commit()
            user_id = user.id
            job_id = job.id
            artefact_id = artefact.id

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)
            artefact = db.get(Artefact, artefact_id)

            output = generate_job_artefact_tailoring_guidance(db, user, job, artefact)
            db.commit()

            assert output.output_type == "tailoring_guidance"
            assert output.provider == "system"
            assert output.source_context["local_fallback"] is True
            assert output.source_context["metadata_quality"] == "thin"
            assert output.source_context["artefact_uuid"] == artefact.uuid
            assert "Tailoring is currently working from metadata only" in output.body
            assert "supporting statement" in output.body
    finally:
        app.dependency_overrides.clear()


def test_load_artefact_text_excerpt_reads_textlike_artefacts() -> None:
    artefact = Artefact(
        kind="resume",
        filename="baseline.md",
        content_type="text/markdown",
        storage_key="artefacts/baseline.md",
    )

    excerpt = load_artefact_text_excerpt(
        artefact,
        storage=type("FakeStorage", (), {"load": lambda self, key: b"# Resume\n\nPlatform delivery evidence"})(),
    )

    assert excerpt == "# Resume\n\nPlatform delivery evidence"


def test_generate_job_artefact_tailoring_guidance_uses_extracted_text_for_textlike_artefacts(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Markdown tailoring target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                filename="baseline.md",
                content_type="text/markdown",
                storage_key="artefacts/baseline.md",
            )
            setting = AiProviderSetting(
                owner_user_id=user.id,
                provider="gemini",
                model_name="gemini-flash-latest",
                api_key_encrypted="sealed",
                api_key_hint="key...1234",
                is_enabled=True,
            )
            db.add_all([job, artefact, setting])
            db.commit()
            user_id = user.id
            job_id = job.id
            artefact_id = artefact.id

        monkeypatch.setattr(
            "app.services.ai.load_artefact_text_excerpt",
            lambda artefact: "# Resume\n\n* Platform delivery\n* Stakeholder leadership",
        )

        def fake_execute_prompt(setting, prompt, *, document=None):
            assert "Extracted artefact text (verified excerpt):" in prompt
            assert "Platform delivery" in prompt
            return "### Keep\n* **Platform delivery**"

        monkeypatch.setattr("app.services.ai._execute_prompt", fake_execute_prompt)

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)
            artefact = db.get(Artefact, artefact_id)

            output = generate_job_artefact_tailoring_guidance(db, user, job, artefact)
            db.commit()

            assert output.provider == "gemini"
            assert output.source_context["used_extracted_text"] is True
            assert output.source_context["draft_handoff_contract"] == "artefact_draft_seed_v1"
    finally:
        app.dependency_overrides.clear()


def test_generate_job_artefact_draft_stores_visible_output(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Draft target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                purpose="TPM resume",
                version_label="v3",
                notes="Used for senior platform roles.",
                outcome_context="Helped reach interview loop.",
                filename="baseline.md",
                content_type="text/markdown",
                storage_key="artefacts/baseline.md",
            )
            setting = AiProviderSetting(
                owner_user_id=user.id,
                provider="gemini",
                model_name="gemini-flash-latest",
                api_key_encrypted="sealed",
                api_key_hint="key...1234",
                is_enabled=True,
            )
            db.add_all([job, artefact, setting])
            db.commit()
            user_id = user.id
            job_id = job.id
            artefact_id = artefact.id

        monkeypatch.setattr(
            "app.services.ai.load_artefact_text_excerpt",
            lambda artefact: "# Resume\n\n* Platform delivery",
        )

        def fake_execute_prompt(setting, prompt, *, document=None):
            assert "Content mode: extracted_text" in prompt
            assert "Platform delivery" in prompt
            assert document is None
            return "### Headline\nTechnical Program Manager"

        monkeypatch.setattr("app.services.ai._execute_prompt", fake_execute_prompt)

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)
            artefact = db.get(Artefact, artefact_id)

            output = generate_job_artefact_draft(
                db,
                user,
                job,
                artefact,
                draft_kind="resume_draft",
            )
            db.commit()

            assert output.output_type == "draft"
            assert output.title == "AI tailored resume draft"
            assert output.source_context["prompt_contract"] == "artefact_draft_v1"
            assert output.source_context["draft_kind"] == "resume_draft"
            assert output.source_context["content_mode"] == "extracted_text"
            assert output.source_context["artefact_uuid"] == artefact.uuid
    finally:
        app.dependency_overrides.clear()


def test_generate_job_artefact_draft_uses_gemini_provider_document_for_pdf_when_no_text_excerpt(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="PDF draft target", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                filename="baseline.pdf",
                content_type="application/pdf",
                storage_key="artefacts/baseline.pdf",
            )
            setting = AiProviderSetting(
                owner_user_id=user.id,
                provider="gemini",
                model_name="gemini-flash-latest",
                api_key_encrypted="sealed",
                api_key_hint="key...1234",
                is_enabled=True,
            )
            db.add_all([job, artefact, setting])
            db.commit()
            user_id = user.id
            job_id = job.id
            artefact_id = artefact.id

        monkeypatch.setattr("app.services.ai.load_artefact_text_excerpt", lambda artefact: None)
        monkeypatch.setattr(
            "app.services.ai.load_artefact_document_payload",
            lambda artefact: ("application/pdf", b"%PDF-sample"),
        )

        def fake_execute_prompt(setting, prompt, *, document=None):
            assert "Content mode: provider_document" in prompt
            assert document is not None
            assert document["mime_type"] == "application/pdf"
            assert document["data"] == b"%PDF-sample"
            return "### Headline\nTechnical Program Manager"

        monkeypatch.setattr("app.services.ai._execute_prompt", fake_execute_prompt)

        with session_local() as db:
            user = db.get(User, user_id)
            job = db.get(Job, job_id)
            artefact = db.get(Artefact, artefact_id)

            output = generate_job_artefact_draft(
                db,
                user,
                job,
                artefact,
                draft_kind="resume_draft",
            )
            db.commit()

            assert output.source_context["content_mode"] == "provider_document"
            assert output.source_context["provider_document_mime_type"] == "application/pdf"
            assert output.source_context["used_extracted_text"] is False
    finally:
        app.dependency_overrides.clear()


def test_call_gemini_maps_raw_timeout_error(monkeypatch) -> None:
    setting = AiProviderSetting(
        provider="gemini",
        model_name="gemini-flash-latest",
        api_key_encrypted="sealed",
    )

    monkeypatch.setattr("app.services.ai._open_provider_api_key", lambda setting: "gemini-secret-1234")
    monkeypatch.setattr("app.services.ai.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))

    try:
        _call_gemini(setting, "hello")
    except AiExecutionError as exc:
        assert "Google Gemini timed out before returning a response" in str(exc)
    else:
        raise AssertionError("Expected AiExecutionError")
