import json
import ssl
import base64
from urllib import error, request

import certifi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ai_output import AiOutput
from app.db.models.ai_provider_setting import AiProviderSetting
from app.db.models.job import Job
from app.db.models.user import User
from app.db.models.user_profile import UserProfile
from app.security.sealed_secrets import SecretEnvelopeError, key_hint, open_secret, seal_secret
from app.db.models.artefact import Artefact
from app.services.artefacts import (
    ArtefactCandidateSummary,
    list_candidate_artefacts_for_job,
    load_artefact_document_payload,
    load_artefact_text_excerpt,
    summarise_artefact_for_ai,
)

KNOWN_PROVIDERS = ("openai", "gemini", "anthropic", "openai_compatible")
KNOWN_OUTPUT_TYPES = (
    "recommendation",
    "fit_summary",
    "draft",
    "profile_observation",
    "artefact_suggestion",
    "tailoring_guidance",
)

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "anthropic": "Anthropic",
    "openai_compatible": "OpenAI-compatible provider",
}


def list_user_ai_provider_settings(db: Session, user: User) -> list[AiProviderSetting]:
    return list(
        db.scalars(
            select(AiProviderSetting)
            .where(AiProviderSetting.owner_user_id == user.id)
            .order_by(AiProviderSetting.provider, AiProviderSetting.created_at)
        )
    )


def upsert_ai_provider_setting(
    db: Session,
    user: User,
    *,
    provider: str,
    label: str | None = None,
    base_url: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
    is_enabled: bool = False,
) -> AiProviderSetting:
    if provider not in KNOWN_PROVIDERS:
        raise ValueError("Unsupported AI provider")
    setting = db.scalar(
        select(AiProviderSetting).where(
            AiProviderSetting.owner_user_id == user.id,
            AiProviderSetting.provider == provider,
        )
    )
    if setting is None:
        setting = AiProviderSetting(owner_user_id=user.id, provider=provider)
        db.add(setting)
    setting.label = (label or "").strip() or None
    setting.base_url = (base_url or "").strip() or None
    setting.model_name = (model_name or "").strip() or None
    api_key_value = (api_key or "").strip()
    if api_key_value:
        setting.api_key_encrypted = seal_secret(api_key_value)
        setting.api_key_hint = key_hint(api_key_value)
    setting.is_enabled = is_enabled
    if is_enabled:
        for other_setting in list_user_ai_provider_settings(db, user):
            if other_setting.provider != provider and other_setting.is_enabled:
                other_setting.is_enabled = False
    db.flush()
    return setting


def list_user_ai_outputs(db: Session, user: User) -> list[AiOutput]:
    return list(
        db.scalars(
            select(AiOutput)
            .where(AiOutput.owner_user_id == user.id)
            .order_by(AiOutput.updated_at.desc(), AiOutput.created_at.desc())
        )
    )


class AiExecutionError(RuntimeError):
    pass


def _provider_label(setting: AiProviderSetting) -> str:
    return PROVIDER_LABELS.get(setting.provider, "AI provider")


def _parse_error_detail_payload(detail: str) -> tuple[dict[str, object], str]:
    text = detail.strip()
    if not text:
        return {}, ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}, text
    if isinstance(payload, dict):
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            message = error_payload.get("message")
            return error_payload, message.strip() if isinstance(message, str) else text
        message = payload.get("message")
        if isinstance(message, str):
            return payload, message.strip()
    return {}, text


def _http_error_message(setting: AiProviderSetting, exc: error.HTTPError) -> str:
    detail = exc.read().decode("utf-8", errors="ignore")
    payload, message = _parse_error_detail_payload(detail)
    provider = _provider_label(setting)
    normalized = message.lower()
    error_code = str(payload.get("code", "")).lower()
    error_type = str(payload.get("type", "")).lower()

    if exc.code == 404:
        if setting.provider == "gemini" and "model" in normalized and "not found" in normalized:
            return (
                f"{provider} could not find that model. Check the model name in Settings "
                "for the selected API version."
            )
        return (
            f"{provider} endpoint was not found. Check the Base URL in Settings and remove any extra path "
            "segments unless you intend to override the default endpoint."
        )
    if exc.code in (401, 403):
        return f"{provider} rejected the API key. Check the saved key and provider permissions in Settings."
    if exc.code == 429 and (
        "insufficient_quota" in error_code
        or "insufficient_quota" in error_type
        or "quota" in normalized
        or "billing" in normalized
    ):
        return (
            f"{provider} accepted the key, but the project has no available API quota. "
            "Check provider billing and quota for this key."
        )
    if exc.code == 429:
        return f"{provider} rate-limited the request. Wait a moment and try again."
    if exc.code == 400 and ("model" in normalized and ("not found" in normalized or "unsupported" in normalized)):
        return f"{provider} could not use that model. Check the model name in Settings."
    if exc.code == 400 and ("api key" in normalized or "credential" in normalized or "auth" in normalized):
        return f"{provider} rejected the credentials. Check the saved API key in Settings."

    fallback = message or exc.reason or "Unknown error"
    return f"{provider} returned an error ({exc.code}). {fallback}"


def _url_error_message(setting: AiProviderSetting, exc: error.URLError) -> str:
    provider = _provider_label(setting)
    reason = str(exc.reason)
    if "CERTIFICATE_VERIFY_FAILED" in reason:
        return (
            f"Could not reach {provider} because TLS certificate validation failed. "
            "Check the local trust store or custom HTTPS endpoint."
        )
    return f"Could not reach {provider}. Check the network connection and Base URL in Settings."


def _timeout_error_message(setting: AiProviderSetting) -> str:
    provider = _provider_label(setting)
    return f"{provider} timed out before returning a response. Try again or reduce the request size."


def get_enabled_ai_provider(db: Session, user: User) -> AiProviderSetting | None:
    settings = list_user_ai_provider_settings(db, user)
    enabled = [setting for setting in settings if setting.is_enabled]
    if not enabled:
        return None
    for provider_name in ("openai_compatible", "gemini", "openai", "anthropic"):
        for setting in enabled:
            if setting.provider == provider_name:
                return setting
    return enabled[0]


def _profile_context(profile: UserProfile | None) -> str:
    if profile is None:
        return "No user profile is configured."
    fields = [
        ("Target roles", profile.target_roles),
        ("Target locations", profile.target_locations),
        ("Remote preference", profile.remote_preference),
        ("Salary min", profile.salary_min),
        ("Salary max", profile.salary_max),
        ("Salary currency", profile.salary_currency),
        ("Preferred industries", profile.preferred_industries),
        ("Excluded industries", profile.excluded_industries),
        ("Constraints", profile.constraints),
        ("Urgency", profile.urgency),
        ("Positioning notes", profile.positioning_notes),
    ]
    visible = [f"{label}: {value}" for label, value in fields if value not in (None, "")]
    return "\n".join(visible) if visible else "No user profile is configured."


def _job_context(job: Job) -> str:
    fields = [
        ("Title", job.title),
        ("Company", job.company),
        ("Status", job.status),
        ("Location", job.location),
        ("Remote policy", job.remote_policy),
        ("Source", job.source),
        ("Source URL", job.source_url),
        ("Apply URL", job.apply_url),
        ("Description", job.description_raw),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if value not in (None, ""))


def _output_request(output_type: str, *, surface: str = "default") -> tuple[str, str]:
    if output_type == "fit_summary":
        return (
            "AI fit summary",
            (
                "Write a concise fit summary for this job. Use three short sections titled "
                "'Strengths', 'Gaps', and 'Watch-outs'. Be direct and specific. Do not invent facts. "
                "If profile context is missing, say so plainly."
            ),
        )
    if output_type == "recommendation":
        if surface == "focus":
            return (
                "AI next-step recommendation",
                (
                    "This recommendation is for the Focus surface, where the user needs one immediate next move. "
                    "Recommend exactly one concrete next action for this role right now. Keep it short and specific. "
                    "Use three short sections titled 'Next step', 'Why this now', and 'What to prepare'. "
                    "Explain why this role deserves attention in Focus based on the available context. "
                    "Do not suggest status changes or multiple parallel tasks. Do not invent facts."
                ),
            )
        return (
            "AI next-step recommendation",
            (
                "Recommend the next best action for this job search opportunity. Use three short bullet-style "
                "paragraphs titled 'Next step', 'Why now', and 'What to prepare'. Be direct and actionable."
            ),
        )
    raise AiExecutionError("Unsupported AI output type")


def _build_job_prompt(
    output_type: str,
    *,
    profile: UserProfile | None,
    job: Job,
    surface: str = "default",
) -> tuple[str, str]:
    title, instruction = _output_request(output_type, surface=surface)
    prompt = (
        f"{instruction}\n\n"
        f"User profile:\n{_profile_context(profile)}\n\n"
        f"Job:\n{_job_context(job)}"
    )
    return title, prompt


def _build_artefact_suggestion_prompt(
    *,
    profile: UserProfile | None,
    job: Job,
    candidates: list[ArtefactCandidateSummary],
) -> tuple[str, str]:
    title = "AI artefact suggestion"
    if candidates:
        candidate_block = "\n\n".join(
            f"Candidate {index + 1}:\n{candidate.summary_text}"
            for index, candidate in enumerate(candidates)
        )
    else:
        candidate_block = "No existing artefacts are available for this user."
    prompt = (
        "Recommend which existing artefacts should be reused or adapted for this job. "
        "Use markdown sections titled 'Best starting artefact', 'Other usable candidates', "
        "'Missing artefacts', 'Why', and 'What to adapt before submission'. "
        "Prefer 'no suitable artefact' over weak guesses. "
        "Do not invent unseen document content. "
        "Use the provided artefact summaries and outcome signals conservatively.\n\n"
        f"User profile:\n{_profile_context(profile)}\n\n"
        f"Job:\n{_job_context(job)}\n\n"
        f"Candidate artefacts:\n{candidate_block}"
    )
    return title, prompt


def _build_artefact_tailoring_prompt(
    *,
    profile: UserProfile | None,
    job: Job,
    artefact: Artefact,
    artefact_summary: ArtefactCandidateSummary,
    extracted_text: str | None = None,
    prior_suggestion: AiOutput | None = None,
) -> tuple[str, str]:
    title = "AI tailoring guidance"
    prior_context = ""
    if prior_suggestion is not None and prior_suggestion.body:
        prior_context = f"\n\nPrior artefact suggestion:\n{prior_suggestion.body}"
    extracted_text_block = ""
    if extracted_text:
        extracted_text_block = f"\n\nExtracted artefact text (verified excerpt):\n{extracted_text}"
    prompt = (
        "You are providing tailoring guidance for one selected artefact against one job. "
        "Use markdown sections titled 'Keep', 'Strengthen', 'De-emphasise or remove', "
        "'Missing evidence', 'Supporting documents', and 'How to use this artefact for this submission'. "
        "Do not invent document content. If extracted artefact text is unavailable, say that you are "
        "reasoning from metadata and prior usage history only. If extracted text is present, treat it as "
        "verified present content and keep any other claims clearly separate. Be concrete and job-specific.\n\n"
        f"User profile:\n{_profile_context(profile)}\n\n"
        f"Job:\n{_job_context(job)}\n\n"
        f"Selected artefact:\n{artefact_summary.summary_text}{extracted_text_block}{prior_context}"
    )
    return title, prompt


def _draft_request(draft_kind: str) -> tuple[str, str]:
    if draft_kind == "resume_draft":
        return (
            "AI tailored resume draft",
            (
                "Draft a tailored resume variant for this job. Use markdown sections titled "
                "'Headline', 'Professional summary', 'Relevant impact bullets', 'Skills to emphasise', "
                "and 'Gaps or evidence still needed'. If the baseline artefact content is unavailable, "
                "produce a cautious scaffold rather than pretending to rewrite exact document content. "
                "Do not invent experience."
            ),
        )
    if draft_kind == "cover_letter_draft":
        return (
            "AI cover letter draft",
            (
                "Draft a concise cover letter for this job. Use markdown sections titled "
                "'Opening', 'Role fit', 'Relevant evidence', 'Why this company or role', and 'Closing'. "
                "If the baseline artefact content is unavailable, produce a cautious scaffold based on "
                "metadata, tailoring guidance, and job context rather than inventing specifics."
            ),
        )
    if draft_kind == "supporting_statement_draft":
        return (
            "AI supporting statement draft",
            (
                "Draft a targeted supporting statement for this job. Use markdown sections titled "
                "'Fit summary', 'Relevant evidence', 'Operational examples', 'Why this role', and "
                "'Points still to evidence'. If the baseline artefact content is unavailable, produce "
                "a cautious scaffold based on metadata, tailoring guidance, and job context rather than "
                "inventing specifics."
            ),
        )
    if draft_kind == "attestation_draft":
        return (
            "AI attestation draft",
            (
                "Draft a concise attestation or supporting declaration for this job. Use markdown sections "
                "titled 'Context', 'Statement', 'Relevant evidence', and 'Closing'. If the baseline artefact "
                "content is unavailable, produce a cautious scaffold based on metadata, tailoring guidance, "
                "and job context rather than inventing specifics."
            ),
        )
    raise AiExecutionError("Unsupported draft kind")


def _build_artefact_draft_prompt(
    *,
    profile: UserProfile | None,
    job: Job,
    artefact_summary: ArtefactCandidateSummary,
    draft_kind: str,
    content_mode: str,
    extracted_text: str | None = None,
    tailoring_guidance: AiOutput | None = None,
    prior_suggestion: AiOutput | None = None,
) -> tuple[str, str]:
    title, instruction = _draft_request(draft_kind)
    content_block = "Baseline artefact content is unavailable. Reason from metadata only."
    if content_mode == "extracted_text" and extracted_text:
        content_block = f"Verified extracted artefact text:\n{extracted_text}"
    tailoring_block = ""
    if tailoring_guidance is not None and tailoring_guidance.body:
        tailoring_block = f"\n\nTailoring guidance:\n{tailoring_guidance.body}"
    prior_block = ""
    if prior_suggestion is not None and prior_suggestion.body:
        prior_block = f"\n\nPrior artefact suggestion:\n{prior_suggestion.body}"
    prompt = (
        f"{instruction}\n\n"
        f"User profile:\n{_profile_context(profile)}\n\n"
        f"Job:\n{_job_context(job)}\n\n"
        f"Selected baseline artefact:\n{artefact_summary.summary_text}\n\n"
        f"Content mode: {content_mode}\n"
        f"{content_block}"
        f"{tailoring_block}"
        f"{prior_block}"
    )
    return title, prompt


def _infer_missing_artefacts(job: Job) -> list[str]:
    description = (job.description_raw or "").lower()
    needed = ["resume"]
    if "cover letter" in description:
        needed.append("cover letter")
    if "supporting statement" in description or "personal statement" in description:
        needed.append("supporting statement")
    if "attestation" in description:
        needed.append("attestation")
    if "writing sample" in description:
        needed.append("writing sample")
    return needed


def _build_empty_artefact_suggestion_body(job: Job, *, profile: UserProfile | None) -> str:
    target_role = profile.target_roles if profile and profile.target_roles else "this role"
    missing = _infer_missing_artefacts(job)
    missing_text = ", ".join(missing)
    role_context = f" for {target_role}" if target_role else ""
    return (
        "### Best starting artefact\n"
        "* No existing artefact is available yet for this job.\n\n"
        "### Other usable candidates\n"
        "* None yet.\n\n"
        f"### Missing artefacts\n"
        f"* Prepare at least a {missing_text}{role_context}.\n\n"
        "### Why\n"
        "* The artefact library has no current candidates to reuse or adapt for this application.\n"
        "* Starting with a clear baseline artefact will make later tailoring suggestions much stronger.\n\n"
        "### What to adapt before submission\n"
        "* Upload a baseline resume or relevant submission document first.\n"
        "* Add purpose, version, and outcome notes so future suggestions have stronger evidence.\n"
        "* If the role asks for extra materials, add those as separate artefacts rather than folding everything into one file."
    )


def _build_sparse_tailoring_guidance_body(
    job: Job,
    artefact: Artefact,
    artefact_summary: ArtefactCandidateSummary,
    *,
    prior_suggestion: AiOutput | None = None,
) -> str:
    prior_note = ""
    if prior_suggestion is not None and prior_suggestion.body:
        prior_note = (
            "\n* A prior artefact suggestion exists for this job, but the selected artefact still needs "
            "clearer metadata before stronger tailoring advice will be reliable."
        )
    return (
        "### Keep\n"
        f"* Keep `{artefact.filename}` as a possible baseline only if it is the closest available starting point for {job.title or 'this job'}.\n"
        "* Keep any clearly relevant role, domain, or delivery evidence that you know is already in the file.\n\n"
        "### Strengthen\n"
        "* Add purpose, version, and notes so the system can understand what this artefact is meant to do.\n"
        "* Link the artefact to prior jobs or outcomes if it has been used before.\n"
        "* Add outcome context when this artefact helped lead to interviews or other meaningful progress.\n\n"
        "### De-emphasise or remove\n"
        "* Avoid assuming this artefact is submission-ready until its purpose and history are clearer.\n"
        "* Do not over-index on generic content that is not obviously tied to this role.\n\n"
        "### Missing evidence\n"
        f"* Tailoring is currently working from metadata only, and this artefact has **{artefact_summary.metadata_quality}** metadata quality.\n"
        "* The current record is too thin to give high-confidence line-by-line tailoring advice.\n"
        f"* Missing metadata should be filled in first: {', '.join(part for part in ['purpose' if not artefact.purpose else '', 'version' if not artefact.version_label else '', 'notes' if not artefact.notes else '', 'outcome context' if not artefact.outcome_context else ''] if part) or 'linked history or richer artefact notes'}.\n\n"
        "### Supporting documents\n"
        "* Check the role description for extra submission requirements such as a cover letter, supporting statement, or attestation.\n"
        "* Add those as separate artefacts if they are required for this application.\n\n"
        "### How to use this artefact for this submission\n"
        "* Treat this as a baseline candidate rather than a final recommendation.\n"
        "* Improve the artefact record first, then run tailoring guidance again for stronger advice."
        f"{prior_note}"
    )


def _call_openai_compatible(setting: AiProviderSetting, prompt: str) -> str:
    if not setting.base_url:
        raise AiExecutionError("Enabled AI provider is missing a base URL")
    if not setting.model_name:
        raise AiExecutionError("Enabled AI provider is missing a model name")

    payload = {
        "model": setting.model_name,
        "messages": [
            {"role": "system", "content": "You are an assistant helping a jobseeker inside a private application tracker."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    endpoint = setting.base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with request.urlopen(req, timeout=20, context=ssl_context) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise AiExecutionError(_http_error_message(setting, exc)) from exc
    except error.URLError as exc:
        raise AiExecutionError(_url_error_message(setting, exc)) from exc
    except TimeoutError as exc:
        raise AiExecutionError(_timeout_error_message(setting)) from exc

    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AiExecutionError("AI provider returned no choices")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AiExecutionError("AI provider returned an empty response")
    return content.strip()


def _open_provider_api_key(setting: AiProviderSetting) -> str:
    try:
        value = open_secret(setting.api_key_encrypted)
    except SecretEnvelopeError as exc:
        raise AiExecutionError("Stored API key could not be opened. Re-save the provider in Settings.") from exc
    if not value:
        raise AiExecutionError("Enabled AI provider is missing an API key")
    return value


def _call_openai(setting: AiProviderSetting, prompt: str) -> str:
    if not setting.model_name:
        raise AiExecutionError("Enabled AI provider is missing a model name")
    api_key = _open_provider_api_key(setting)
    endpoint_root = (setting.base_url or "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": setting.model_name,
        "input": prompt,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint_root + "/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with request.urlopen(req, timeout=20, context=ssl_context) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise AiExecutionError(_http_error_message(setting, exc)) from exc
    except error.URLError as exc:
        raise AiExecutionError(_url_error_message(setting, exc)) from exc
    except TimeoutError as exc:
        raise AiExecutionError(_timeout_error_message(setting)) from exc

    output_text = raw.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = raw.get("output")
    if isinstance(output, list):
        for item in output:
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for entry in content:
                text = entry.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    raise AiExecutionError("AI provider returned an empty response")


def _call_gemini(
    setting: AiProviderSetting,
    prompt: str,
    *,
    document: dict[str, object] | None = None,
) -> str:
    if not setting.model_name:
        raise AiExecutionError("Enabled AI provider is missing a model name")
    api_key = _open_provider_api_key(setting)
    endpoint_root = (setting.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    parts: list[dict[str, object]] = [
        {
            "text": (
                "You are an assistant helping a jobseeker inside a private application tracker.\n\n"
                + prompt
            )
        }
    ]
    if document is not None:
        mime_type = document.get("mime_type")
        data = document.get("data")
        if isinstance(mime_type, str) and isinstance(data, (bytes, bytearray)):
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(bytes(data)).decode("ascii"),
                    }
                }
            )
    payload = {
        "contents": [
            {
                "parts": parts
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint_root + f"/models/{setting.model_name}:generateContent",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with request.urlopen(req, timeout=20, context=ssl_context) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise AiExecutionError(_http_error_message(setting, exc)) from exc
    except error.URLError as exc:
        raise AiExecutionError(_url_error_message(setting, exc)) from exc
    except TimeoutError as exc:
        raise AiExecutionError(_timeout_error_message(setting)) from exc

    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise AiExecutionError("AI provider returned no candidates")
    for candidate in candidates:
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    raise AiExecutionError("AI provider returned an empty response")


def _execute_prompt(
    setting: AiProviderSetting,
    prompt: str,
    *,
    document: dict[str, object] | None = None,
) -> str:
    if setting.provider == "openai_compatible":
        return _call_openai_compatible(setting, prompt)
    if setting.provider == "gemini":
        return _call_gemini(setting, prompt, document=document)
    if setting.provider == "openai":
        return _call_openai(setting, prompt)
    raise AiExecutionError(
        "Anthropic execution is not implemented yet. Use OpenAI, Gemini, or an OpenAI-compatible endpoint."
    )


def generate_job_ai_output(
    db: Session,
    user: User,
    job: Job,
    *,
    output_type: str,
    profile: UserProfile | None = None,
    surface: str = "default",
) -> AiOutput:
    setting = get_enabled_ai_provider(db, user)
    if setting is None:
        raise AiExecutionError("Enable an AI provider in Settings before generating AI output")

    title, prompt = _build_job_prompt(
        output_type,
        profile=profile,
        job=job,
        surface=surface,
    )
    body = _execute_prompt(setting, prompt)
    output = AiOutput(
        owner_user_id=user.id,
        job_id=job.id,
        output_type=output_type,
        title=title,
        body=body,
        provider=setting.provider,
        model_name=setting.model_name,
        status="active",
        source_context={
            "job_uuid": job.uuid,
            "provider_label": setting.label,
            "job_status": job.status,
            "job_title": job.title,
            "surface": surface,
        },
    )
    db.add(output)
    db.flush()
    return output


def generate_job_artefact_suggestion(
    db: Session,
    user: User,
    job: Job,
    *,
    profile: UserProfile | None = None,
    shortlist_limit: int = 5,
) -> AiOutput:
    candidates = list_candidate_artefacts_for_job(db, user, job, limit=shortlist_limit)
    if not candidates:
        output = AiOutput(
            owner_user_id=user.id,
            job_id=job.id,
            output_type="artefact_suggestion",
            title="AI artefact suggestion",
            body=_build_empty_artefact_suggestion_body(job, profile=profile),
            provider="system",
            model_name=None,
            status="active",
            source_context={
                "job_uuid": job.uuid,
                "job_status": job.status,
                "job_title": job.title,
                "surface": "job_workspace",
                "prompt_contract": "artefact_suggestion_v1",
                "shortlisted_artefact_uuids": [],
                "local_fallback": True,
            },
        )
        db.add(output)
        db.flush()
        return output

    setting = get_enabled_ai_provider(db, user)
    if setting is None:
        raise AiExecutionError("Enable an AI provider in Settings before generating AI output")

    title, prompt = _build_artefact_suggestion_prompt(
        profile=profile,
        job=job,
        candidates=candidates,
    )
    body = _execute_prompt(setting, prompt)
    output = AiOutput(
        owner_user_id=user.id,
        job_id=job.id,
        output_type="artefact_suggestion",
        title=title,
        body=body,
        provider=setting.provider,
        model_name=setting.model_name,
        status="active",
        source_context={
            "job_uuid": job.uuid,
            "provider_label": setting.label,
            "job_status": job.status,
            "job_title": job.title,
            "surface": "job_workspace",
            "prompt_contract": "artefact_suggestion_v1",
            "shortlisted_artefact_uuids": [candidate.artefact_uuid for candidate in candidates],
        },
    )
    db.add(output)
    db.flush()
    return output


def generate_job_artefact_tailoring_guidance(
    db: Session,
    user: User,
    job: Job,
    artefact: Artefact,
    *,
    profile: UserProfile | None = None,
    prior_suggestion: AiOutput | None = None,
) -> AiOutput:
    artefact_summary = summarise_artefact_for_ai(artefact, current_job=job)
    extracted_text = load_artefact_text_excerpt(artefact)
    used_extracted_text = bool(extracted_text)
    if artefact_summary.metadata_quality == "thin" and not used_extracted_text:
        output = AiOutput(
            owner_user_id=user.id,
            job_id=job.id,
            artefact_id=artefact.id,
            output_type="tailoring_guidance",
            title="AI tailoring guidance",
            body=_build_sparse_tailoring_guidance_body(
                job,
                artefact,
                artefact_summary,
                prior_suggestion=prior_suggestion,
            ),
            provider="system",
            model_name=None,
            status="active",
            source_context={
                "surface": "job_workspace",
                "job_uuid": job.uuid,
                "artefact_uuid": artefact.uuid,
                "prompt_contract": "artefact_tailoring_v1",
                "used_extracted_text": False,
                "metadata_quality": artefact_summary.metadata_quality,
                "local_fallback": True,
                "draft_handoff_contract": "artefact_draft_seed_v1",
                **(
                    {"artefact_suggestion_output_id": prior_suggestion.id}
                    if prior_suggestion is not None
                    else {}
                ),
            },
        )
        db.add(output)
        db.flush()
        return output

    setting = get_enabled_ai_provider(db, user)
    if setting is None:
        raise AiExecutionError("Enable an AI provider in Settings before generating AI output")

    title, prompt = _build_artefact_tailoring_prompt(
        profile=profile,
        job=job,
        artefact=artefact,
        artefact_summary=artefact_summary,
        extracted_text=extracted_text,
        prior_suggestion=prior_suggestion,
    )
    body = _execute_prompt(setting, prompt)
    output = AiOutput(
        owner_user_id=user.id,
        job_id=job.id,
        artefact_id=artefact.id,
        output_type="tailoring_guidance",
        title=title,
        body=body,
        provider=setting.provider,
        model_name=setting.model_name,
        status="active",
        source_context={
            "surface": "job_workspace",
            "job_uuid": job.uuid,
            "artefact_uuid": artefact.uuid,
            "prompt_contract": "artefact_tailoring_v1",
            "artefact_suggestion_output_id": prior_suggestion.id if prior_suggestion is not None else None,
            "used_extracted_text": used_extracted_text,
            "metadata_quality": artefact_summary.metadata_quality,
            "draft_handoff_contract": "artefact_draft_seed_v1",
        },
    )
    db.add(output)
    db.flush()
    return output


def generate_job_artefact_draft(
    db: Session,
    user: User,
    job: Job,
    artefact: Artefact,
    *,
    draft_kind: str,
    profile: UserProfile | None = None,
    tailoring_guidance: AiOutput | None = None,
    prior_suggestion: AiOutput | None = None,
) -> AiOutput:
    setting = get_enabled_ai_provider(db, user)
    if setting is None:
        raise AiExecutionError("Enable an AI provider in Settings before generating AI output")

    artefact_summary = summarise_artefact_for_ai(artefact, current_job=job)
    extracted_text = load_artefact_text_excerpt(artefact)
    document_payload = None
    content_mode = "extracted_text" if extracted_text else "metadata_only"
    if extracted_text is None and setting.provider == "gemini":
        provider_document = load_artefact_document_payload(artefact)
        if provider_document is not None:
            mime_type, raw = provider_document
            document_payload = {"mime_type": mime_type, "data": raw}
            content_mode = "provider_document"
    title, prompt = _build_artefact_draft_prompt(
        profile=profile,
        job=job,
        artefact_summary=artefact_summary,
        draft_kind=draft_kind,
        content_mode=content_mode,
        extracted_text=extracted_text,
        tailoring_guidance=tailoring_guidance,
        prior_suggestion=prior_suggestion,
    )
    body = _execute_prompt(setting, prompt, document=document_payload)
    output = AiOutput(
        owner_user_id=user.id,
        job_id=job.id,
        artefact_id=artefact.id,
        output_type="draft",
        title=title,
        body=body,
        provider=setting.provider,
        model_name=setting.model_name,
        status="active",
        source_context={
            "surface": "job_workspace",
            "job_uuid": job.uuid,
            "artefact_uuid": artefact.uuid,
            "prompt_contract": "artefact_draft_v1",
            "draft_kind": draft_kind,
            "content_mode": content_mode,
            "used_extracted_text": bool(extracted_text),
            "provider_document_mime_type": document_payload["mime_type"] if document_payload is not None else None,
            "metadata_quality": artefact_summary.metadata_quality,
            "tailoring_guidance_output_id": tailoring_guidance.id if tailoring_guidance is not None else None,
            "artefact_suggestion_output_id": prior_suggestion.id if prior_suggestion is not None else None,
        },
    )
    db.add(output)
    db.flush()
    return output
