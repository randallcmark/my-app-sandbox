from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
import json
import logging
import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from starlette.datastructures import FormData

from app.api.deps import DbSession, get_current_user
from app.api.ownership import require_owner
from app.api.routes.ui import render_shell_page
from app.db.models.ai_output import AiOutput
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.competency_evidence import CompetencyEvidence
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User
from app.services.ai import (
    AiExecutionError,
    _ai_debug_summary,
    generate_job_artefact_analysis,
    generate_job_ai_output,
    generate_job_artefact_draft,
    generate_job_artefact_suggestion,
    generate_job_artefact_tailoring_guidance,
)
from app.services.applications import mark_job_applied
from app.services.artefacts import (
    get_user_artefact_by_uuid,
    get_user_job_artefact_by_uuid,
    link_artefact_to_job,
    linked_artefacts_for_job,
    list_user_unlinked_artefacts_for_job,
    update_artefact_metadata,
    store_job_artefact,
)
from app.services.competency_evidence import list_competency_evidence
from app.services.interviews import schedule_interview
from app.services.jobs import (
    BOARD_STATUSES,
    JOB_STATUSES,
    create_job_note,
    get_user_job_by_uuid,
    record_job_status_change,
    update_job_board_state,
)
from app.services.markdown import render_markdown_blocks
from app.services.profiles import get_user_profile
from app.storage.provider import get_storage_provider

router = APIRouter(tags=["job-detail"])
logger = logging.getLogger(__name__)


def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _datetime_attr(value: datetime) -> str:
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.isoformat()


def _time_element(value: datetime) -> str:
    return (
        f'<time class="local-time" datetime="{escape(_datetime_attr(value), quote=True)}">'
        f"{escape(_value(value))}</time>"
    )


def _link(label: str, url: str | None) -> str:
    if not url:
        return '<span class="muted">Not set</span>'
    escaped_url = escape(url, quote=True)
    return f'<a href="{escaped_url}" target="_blank" rel="noreferrer">{escape(label)}</a>'


def _status_options(current_status: str = "saved") -> str:
    return "\n".join(
        f'<option value="{escape(job_status, quote=True)}"'
        f'{" selected" if job_status == current_status else ""}>{escape(job_status.title())}</option>'
        for job_status in BOARD_STATUSES
    )


def _job_status_options(current_status: str = "saved") -> str:
    return "\n".join(
        f'<option value="{escape(job_status, quote=True)}"'
        f'{" selected" if job_status == current_status else ""}>{escape(job_status.title())}</option>'
        for job_status in JOB_STATUSES
    )


def _input_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _field(label: str, value: object) -> str:
    return f"""
    <div class="field">
      <dt>{escape(label)}</dt>
      <dd>{escape(_value(value))}</dd>
    </div>
    """


def _editable_text(label: str, field_name: str, value: object, *, input_type: str = "text") -> str:
    raw_value = _input_value(value)
    return f"""
    <div class="field">
      <dt>{escape(label)}</dt>
      <dd class="editable" data-field="{escape(field_name, quote=True)}" data-kind="text" data-original="{escape(raw_value, quote=True)}" tabindex="0" title="Double-click to edit">
        <span class="editable-display">{escape(_value(value))}</span>
        <input class="editable-control" type="{escape(input_type, quote=True)}" value="{escape(raw_value, quote=True)}">
      </dd>
    </div>
    """


def _editable_url(label: str, field_name: str, value: str | None, link_label: str) -> str:
    raw_value = _input_value(value)
    return f"""
    <div class="field">
      <dt>{escape(label)}</dt>
      <dd class="editable" data-field="{escape(field_name, quote=True)}" data-kind="text" data-original="{escape(raw_value, quote=True)}" tabindex="0" title="Double-click to edit">
        <span class="editable-display">{_link(link_label, value)}</span>
        <input class="editable-control" type="url" value="{escape(raw_value, quote=True)}">
      </dd>
    </div>
    """


def _editable_select(label: str, field_name: str, value: str) -> str:
    return f"""
    <div class="field">
      <dt>{escape(label)}</dt>
      <dd class="editable" data-field="{escape(field_name, quote=True)}" data-kind="select" data-original="{escape(value, quote=True)}" tabindex="0" title="Double-click to edit">
        <span class="editable-display">{escape(_value(value))}</span>
        <select class="editable-control">
          {_job_status_options(value)}
        </select>
      </dd>
    </div>
    """


def _editable_title(job: Job) -> str:
    raw_value = _input_value(job.title)
    return f"""
    <h1 class="editable editable-heading" data-field="title" data-kind="text" data-original="{escape(raw_value, quote=True)}" tabindex="0" title="Double-click to edit">
      <span class="editable-display">{escape(job.title)}</span>
      <input class="editable-control" value="{escape(raw_value, quote=True)}" maxlength="300" required>
    </h1>
    """


def _editable_description(job: Job) -> str:
    raw_value = _input_value(job.description_raw)
    display = (
        _render_description_markdown(job.description_raw)
        if job.description_raw
        else '<p class="empty">No description captured yet.</p>'
    )
    return f"""
    <div class="editable editable-description" data-field="description_raw" data-kind="textarea" data-original="{escape(raw_value, quote=True)}" tabindex="0" title="Double-click to edit">
      <div class="editable-display">{display}</div>
      <textarea class="editable-control description-editor" rows="22">{escape(raw_value)}</textarea>
    </div>
    """


def _timeline_event(event: Communication) -> str:
    occurred_at = event.occurred_at or event.created_at
    follow_up = (
        f'<p class="follow-up">Follow-up: {_time_element(event.follow_up_at)}</p>'
        if event.follow_up_at
        else ""
    )
    notes = f"<p>{escape(event.notes)}</p>" if event.notes else ""
    return f"""
    <li>
      {_time_element(occurred_at)}
      <strong>{escape(event.subject or event.event_type)}</strong>
      {follow_up}
      {notes}
    </li>
    """


def _timeline(events: list[Communication]) -> str:
    if not events:
        return '<p class="empty">No timeline events yet.</p>'
    items = "\n".join(_timeline_event(event) for event in events)
    return f"<ol>{items}</ol>"


def _note_form(job: Job) -> str:
    return f"""
    <form class="note-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/notes">
      <label>
        Subject
        <input name="subject" value="Note" maxlength="300">
      </label>
      <label>
        Note
        <textarea name="notes" rows="5" required></textarea>
      </label>
      <label>
        Follow-up date
        <input name="follow_up_at" type="date">
      </label>
      <button type="submit">Add note</button>
    </form>
    """


def _new_job_form() -> str:
    return f"""
    <form class="job-form" method="post" action="/jobs/new">
      <label>
        Title
        <input name="title" maxlength="300" required>
      </label>
      <label>
        Company
        <input name="company" maxlength="300">
      </label>
      <label>
        Status
        <select name="job_status">
          {_status_options()}
        </select>
      </label>
      <label>
        Source URL
        <input name="source_url" type="url" maxlength="2048">
      </label>
      <label>
        Apply URL
        <input name="apply_url" type="url" maxlength="2048">
      </label>
      <label>
        Location
        <input name="location" maxlength="300">
      </label>
      <label>
        Remote policy
        <input name="remote_policy" maxlength="50" placeholder="remote, hybrid, onsite">
      </label>
      <div class="inline-fields">
        <label>
          Salary min
          <input name="salary_min">
        </label>
        <label>
          Salary max
          <input name="salary_max">
        </label>
        <label>
          Currency
          <input name="salary_currency" maxlength="3" placeholder="GBP">
        </label>
      </div>
      <label>
        Description
        <textarea name="description_raw" rows="8"></textarea>
      </label>
      <label>
        Initial note
        <textarea name="initial_note" rows="4" placeholder="Why this is worth tracking"></textarea>
      </label>
      <button type="submit">Create job</button>
    </form>
    """


def _mark_applied_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/mark-applied">
      <label>
        Channel
        <input name="channel" placeholder="company_site">
      </label>
      <label>
        Notes
        <textarea name="notes" rows="4" placeholder="Resume version, referral, confirmation number"></textarea>
      </label>
      <button type="submit">Mark applied</button>
    </form>
    """


def _application_started_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/application-started">
      <label>
        Notes
        <textarea name="notes" rows="3" placeholder="What have you started externally?"></textarea>
      </label>
      <button type="submit">Application started</button>
    </form>
    """


def _blocker_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/blockers">
      <label>
        Blocker
        <textarea name="notes" rows="3" placeholder="What is blocked and what is needed?" required></textarea>
      </label>
      <label>
        Follow-up date
        <input name="follow_up_at" type="date">
      </label>
      <button type="submit">Record blocker</button>
    </form>
    """


def _return_note_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/return-note">
      <label>
        Return note
        <textarea name="notes" rows="3" placeholder="What happened and what is next?" required></textarea>
      </label>
      <label>
        Follow-up date
        <input name="follow_up_at" type="date">
      </label>
      <button type="submit">Record return note</button>
    </form>
    """


def _archive_form(job: Job) -> str:
    disabled = " disabled" if job.status == "archived" else ""
    button_label = "Archived" if job.status == "archived" else "Archive"
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/archive">
      <label>
        Archive note
        <textarea name="notes" rows="3" placeholder="Why this job is being archived"></textarea>
      </label>
      <button type="submit"{disabled}>{button_label}</button>
    </form>
    """


def _unarchive_form(job: Job) -> str:
    if job.status != "archived":
        return '<p class="empty">Available after a job is archived.</p>'

    options = "\n".join(
        f'<option value="{escape(job_status, quote=True)}">{escape(job_status.title())}</option>'
        for job_status in BOARD_STATUSES
    )
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/unarchive">
      <label>
        Restore to
        <select name="target_status">
          {options}
        </select>
      </label>
      <label>
        Unarchive note
        <textarea name="notes" rows="3" placeholder="Why this job is being restored"></textarea>
      </label>
      <button type="submit">Unarchive</button>
    </form>
    """


def _status_transition_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/status">
      <label>
        Move to status
        <select name="target_status">
          {_job_status_options(job.status)}
        </select>
      </label>
      <button type="submit">Update status</button>
    </form>
    """


def _schedule_interview_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/interviews">
      <label>
        Stage
        <input name="stage" placeholder="Recruiter screen" maxlength="100" required>
      </label>
      <label>
        Scheduled time
        <input name="scheduled_at" type="datetime-local">
      </label>
      <label>
        Location
        <input name="location" placeholder="Video call, phone, office" maxlength="300">
      </label>
      <label>
        Participants
        <input name="participants" placeholder="Recruiter, hiring manager" maxlength="500">
      </label>
      <label>
        Notes
        <textarea name="notes" rows="4" placeholder="Preparation notes or scheduling context"></textarea>
      </label>
      <button type="submit">Schedule interview</button>
    </form>
    """


def _artefact_form(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" enctype="multipart/form-data" action="/jobs/{escape(job.uuid, quote=True)}/artefacts">
      <label>
        Kind
        <input name="kind" value="resume" maxlength="100">
      </label>
      <label>
        File
        <input name="file" type="file" required>
      </label>
      <button type="submit">Upload artefact</button>
    </form>
    """


def _application(application: Application) -> str:
    return f"""
    <li>
      <strong>{escape(application.status)}</strong>
      <p>Applied: {escape(_value(application.applied_at))}</p>
      <p>Channel: {escape(_value(application.channel))}</p>
      {f'<p>{escape(application.notes)}</p>' if application.notes else ""}
    </li>
    """


def _applications(applications: list[Application]) -> str:
    if not applications:
        return '<p class="empty">No application record yet.</p>'
    items = "\n".join(_application(application) for application in applications)
    return f"<ol>{items}</ol>"


def _interview(interview: InterviewEvent) -> str:
    return f"""
    <li>
      <strong>{escape(interview.stage)}</strong>
      <p>Scheduled: {escape(_value(interview.scheduled_at))}</p>
      <p>Location: {escape(_value(interview.location))}</p>
      <p>Participants: {escape(_value(interview.participants))}</p>
      {f'<p>{escape(interview.notes)}</p>' if interview.notes else ""}
    </li>
    """


def _interviews(interviews: list[InterviewEvent]) -> str:
    if not interviews:
        return '<p class="empty">No interviews scheduled yet.</p>'
    items = "\n".join(_interview(interview) for interview in interviews)
    return f"<ol>{items}</ol>"


def _ai_badge(output_type: str) -> str:
    labels = {
        "fit_summary": ("Fit summary", "accent"),
        "recommendation": ("Recommendation", "success"),
        "draft": ("Draft", "accent"),
        "profile_observation": ("Profile", "warn"),
        "artefact_suggestion": ("Artefact", "accent"),
        "artefact_analysis": ("Analysis", "accent"),
        "tailoring_guidance": ("Tailoring", "success"),
    }
    label, tone = labels.get(output_type, ("AI output", "accent"))
    return f'<span class="status-pill {tone}">{escape(label)}</span>'


def _render_ai_markdown(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    boilerplate_lines = {
        "here is a concise fit summary for this job:",
        "here's a concise fit summary for this job:",
        "here is a concise fit summary:",
        "here's a concise fit summary:",
    }
    lines = cleaned.split("\n")
    while lines and lines[0].strip().lower() in boilerplate_lines:
        lines.pop(0)
    return render_markdown_blocks("\n".join(lines), class_name="ai-markdown")


def _render_description_markdown(text: str) -> str:
    return render_markdown_blocks(text, class_name="description-markdown")


def _artefact_suggestion_links(
    output: AiOutput,
    artefact_lookup: dict[str, Artefact],
) -> str:
    source_context = output.source_context or {}
    shortlisted = source_context.get("shortlisted_artefact_uuids")
    if not isinstance(shortlisted, list) or not shortlisted:
        return ""
    links: list[str] = []
    for artefact_uuid in shortlisted[:5]:
        if not isinstance(artefact_uuid, str):
            continue
        artefact = artefact_lookup.get(artefact_uuid)
        if artefact is None:
            continue
        links.append(
            f'<li><a href="/artefacts/{escape(artefact.uuid, quote=True)}/download">'
            f'{escape(artefact.filename)}</a>'
            f' <span class="muted">({escape(artefact.kind)})</span></li>'
        )
    if not links:
        return ""
    return (
        '<div class="ai-output-links">'
        '<p class="muted">Shortlisted artefacts</p>'
        '<ul>' + "".join(links) + "</ul>"
        "</div>"
    )


def _tailoring_guidance_links(
    output: AiOutput,
    artefact_lookup: dict[str, Artefact],
) -> str:
    source_context = output.source_context or {}
    artefact_uuid = source_context.get("artefact_uuid")
    if not isinstance(artefact_uuid, str) or not artefact_uuid:
        return ""
    artefact = artefact_lookup.get(artefact_uuid)
    if artefact is None:
        return ""
    metadata_quality = source_context.get("metadata_quality")
    metadata_note = ""
    if isinstance(metadata_quality, str) and metadata_quality:
        metadata_note = f' <span class="muted">(metadata: {escape(metadata_quality)})</span>'
    draft_note = ""
    if source_context.get("draft_handoff_contract") == "artefact_draft_seed_v1":
        draft_note = '<p class="muted">Prepared for later draft generation from this artefact and guidance.</p>'
    return (
        '<div class="ai-output-links">'
        '<p class="muted">Selected artefact</p>'
        '<ul>'
        f'<li><a href="/artefacts/{escape(artefact.uuid, quote=True)}/download">{escape(artefact.filename)}</a>'
        f' <span class="muted">({escape(artefact.kind)})</span>{metadata_note}</li>'
        '</ul>'
        f'{draft_note}'
        '</div>'
    )


def _artefact_analysis_links(
    output: AiOutput,
    artefact_lookup: dict[str, Artefact],
) -> str:
    source_context = output.source_context or {}
    artefact_uuid = source_context.get("artefact_uuid")
    if not isinstance(artefact_uuid, str) or not artefact_uuid:
        return ""
    artefact = artefact_lookup.get(artefact_uuid)
    if artefact is None:
        return ""
    content_mode = source_context.get("content_mode")
    content_note = ""
    if isinstance(content_mode, str) and content_mode:
        content_note = f' <span class="muted">(content: {escape(content_mode)})</span>'
    confidence_note = ""
    if content_mode == "metadata_only":
        confidence_note = (
            '<p class="muted">Lower-confidence analysis: based on artefact metadata and job context because verified document text was not available.</p>'
        )
    requirement_summary = source_context.get("inferred_requirement_summary")
    requirement_note = ""
    if isinstance(requirement_summary, str) and requirement_summary:
        requirement_note = f"<p class=\"muted\">{escape(requirement_summary)}</p>"
    return (
        '<div class="ai-output-links">'
        '<p class="muted">Analysed artefact</p>'
        '<ul>'
        f'<li><a href="/artefacts/{escape(artefact.uuid, quote=True)}/download">{escape(artefact.filename)}</a>'
        f' <span class="muted">({escape(artefact.kind)})</span>{content_note}</li>'
        '</ul>'
        f"{confidence_note}"
        f"{requirement_note}"
        '</div>'
    )


def _draft_links(
    output: AiOutput,
    artefact_lookup: dict[str, Artefact],
) -> str:
    source_context = output.source_context or {}
    artefact_uuid = source_context.get("artefact_uuid")
    if not isinstance(artefact_uuid, str) or not artefact_uuid:
        return ""
    artefact = artefact_lookup.get(artefact_uuid)
    if artefact is None:
        return ""
    content_mode = source_context.get("content_mode")
    content_note = ""
    if isinstance(content_mode, str) and content_mode:
        content_note = f' <span class="muted">(content: {escape(content_mode)})</span>'
    confidence_note = ""
    if content_mode == "metadata_only":
        confidence_note = (
            '<p class="muted">Low-confidence draft: generated from artefact metadata, job context, '
            'and guidance rather than verified document text.</p>'
        )
    return (
        '<div class="ai-output-links">'
        '<p class="muted">Baseline artefact</p>'
        '<ul>'
        f'<li><a href="/artefacts/{escape(artefact.uuid, quote=True)}/download">{escape(artefact.filename)}</a>'
        f' <span class="muted">({escape(artefact.kind)})</span>{content_note}</li>'
        '</ul>'
        f'{confidence_note}'
        '</div>'
    )


def _draft_output_actions(output: AiOutput) -> str:
    if output.output_type != "draft" or output.job_id is None:
        return ""
    return f"""
    <div class="ai-output-actions">
      <form class="inline-action-form" method="post" action="/jobs/{escape(output.job.uuid, quote=True)}/ai-outputs/{output.id}/save-draft">
        <button class="outline" type="submit">Save as artefact</button>
      </form>
    </div>
    """


def _ai_outputs_panel(
    outputs: list[AiOutput],
    *,
    artefact_lookup: dict[str, Artefact] | None = None,
) -> str:
    if not outputs:
        return '<p class="empty">No AI output yet. Generate a fit summary or recommendation when you want help deciding what to do next.</p>'
    artefact_lookup = artefact_lookup or {}
    cards = []
    for output in outputs:
        provider = output.model_name or output.provider or "AI"
        extra_links = ""
        if output.output_type == "artefact_suggestion":
            extra_links = _artefact_suggestion_links(output, artefact_lookup)
        elif output.output_type == "artefact_analysis":
            extra_links = _artefact_analysis_links(output, artefact_lookup)
        elif output.output_type == "tailoring_guidance":
            extra_links = _tailoring_guidance_links(output, artefact_lookup)
        elif output.output_type == "draft":
            extra_links = _draft_links(output, artefact_lookup)
        extra_actions = _draft_output_actions(output)
        cards.append(
            f"""
            <article class="ai-output-card">
              <div class="card-header">
                <div>
                  <p class="eyebrow">AI output</p>
                  <h3>{escape(output.title or output.output_type.replace('_', ' ').title())}</h3>
                </div>
                {_ai_badge(output.output_type)}
              </div>
              <p class="muted">From {escape(provider)}</p>
              {_render_ai_markdown(output.body)}
              {extra_links}
              {extra_actions}
            </article>
            """
        )
    return '<div class="ai-output-list">' + "".join(cards) + "</div>"


def _ai_actions(job: Job) -> str:
    return f"""
    <div class="action-stack">
      <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs">
        <input type="hidden" name="output_type" value="fit_summary">
        <button type="submit">Generate fit summary</button>
      </form>
      <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs">
        <input type="hidden" name="output_type" value="recommendation">
        <button class="outline" type="submit">Suggest next step</button>
      </form>
      <p class="muted">AI only creates visible output records. It does not change status, notes, artefacts, or profile data.</p>
    </div>
    """


def _flash_message(message: str, *, tone: str, detail: str | None = None) -> str:
    detail_html = f'<p class="flash-detail">{escape(detail)}</p>' if detail else ""
    return f"""
    <section class="workspace-panel flash flash-{escape(tone, quote=True)}">
      <p>{escape(message)}</p>
      {detail_html}
    </section>
    """


def _log_ai_route_error(
    *,
    route_action: str,
    section: str,
    job: Job,
    exc: AiExecutionError,
) -> str | None:
    debug_detail = _ai_debug_summary(exc) or None
    logger.warning(
        "AI action failed: route_action=%s section=%s job_uuid=%s error=%s diagnostics=%s",
        route_action,
        section,
        job.uuid,
        str(exc),
        exc.diagnostics,
    )
    return debug_detail


def _artefact(job: Job, artefact: Artefact) -> str:
    size = f"{artefact.size_bytes} bytes" if artefact.size_bytes is not None else "Size not set"
    purpose = f"<p>{escape(artefact.purpose)}</p>" if artefact.purpose else ""
    version = f" · {escape(artefact.version_label)}" if artefact.version_label else ""
    return f"""
    <li>
      <strong>{escape(artefact.filename)}</strong>
      <p>{escape(artefact.kind)}{version} · {escape(size)}</p>
      {purpose}
      <div class="artefact-actions">
        <a href="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}">Download</a>
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/tailoring-guidance">
          <button class="outline" type="submit">Suggest tailoring changes</button>
        </form>
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/drafts">
          <input type="hidden" name="draft_kind" value="resume_draft">
          <button class="outline" type="submit">Draft tailored resume</button>
        </form>
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/drafts">
          <input type="hidden" name="draft_kind" value="cover_letter_draft">
          <button class="outline" type="submit">Draft cover letter</button>
        </form>
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/drafts">
          <input type="hidden" name="draft_kind" value="supporting_statement_draft">
          <button class="outline" type="submit">Draft supporting statement</button>
        </form>
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/drafts">
          <input type="hidden" name="draft_kind" value="attestation_draft">
          <button class="outline" type="submit">Draft attestation</button>
        </form>
      </div>
    </li>
    """


def _artefacts(job: Job, artefacts: list[Artefact]) -> str:
    if not artefacts:
        return '<p class="empty">No artefacts uploaded yet.</p>'
    items = "\n".join(_artefact(job, artefact) for artefact in artefacts)
    return f"<ol>{items}</ol>"


def _link_existing_artefact_form(job: Job, available_artefacts: list[Artefact]) -> str:
    if not available_artefacts:
        return '<p class="empty">No other artefacts available to attach yet.</p>'
    options = "\n".join(
        f'<option value="{escape(artefact.uuid, quote=True)}">'
        f'{escape(artefact.filename)} · {escape(artefact.kind)}</option>'
        for artefact in available_artefacts
    )
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefact-links">
      <label>
        Existing artefact
        <select name="artefact_uuid">
          {options}
        </select>
      </label>
      <button type="submit">Attach existing</button>
    </form>
    """


def _artefact_ai_action(job: Job) -> str:
    return f"""
    <form class="quick-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefact-suggestions">
      <button class="outline" type="submit">Suggest artefacts</button>
      <p class="muted">AI ranks existing artefacts for this job and highlights missing materials. It does not attach files automatically.</p>
    </form>
    """


def _salary_range(job: Job) -> str:
    if job.salary_min is None and job.salary_max is None:
        return "Not set"
    currency = f"{job.salary_currency} " if job.salary_currency else ""
    if job.salary_min is not None and job.salary_max is not None:
        return f"{currency}{job.salary_min:,.0f} - {job.salary_max:,.0f}"
    if job.salary_min is not None:
        return f"{currency}{job.salary_min:,.0f}+"
    return f"Up to {currency}{job.salary_max:,.0f}"


def _status_class(status_value: str) -> str:
    if status_value == "interviewing" or status_value == "offer":
        return "success"
    if status_value in {"interested", "preparing", "applied"}:
        return "active"
    if status_value in {"rejected", "archived"}:
        return "closed"
    return "inbox"


def _stage_pill(status_value: str) -> str:
    return f'<span class="stage-pill {escape(_status_class(status_value), quote=True)}">{escape(status_value)}</span>'


def _compact_status_form(job: Job, target_status: str, label: str, *, variant: str = "primary") -> str:
    return f"""
    <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/status">
      <input type="hidden" name="target_status" value="{escape(target_status, quote=True)}">
      <button class="{escape(variant, quote=True)}" type="submit">{escape(label)}</button>
    </form>
    """


def _button_link(label: str, url: str | None, *, primary: bool = False) -> str:
    if not url:
        return ""
    variant = "button-link primary" if primary else "button-link"
    return (
        f'<a class="{variant}" href="{escape(url, quote=True)}" target="_blank" '
        f'rel="noreferrer">{escape(label)} ↗</a>'
    )


def _workspace_section(
    *,
    section_id: str,
    kicker: str,
    title: str,
    body: str,
    actions: str = "",
) -> str:
    return f"""
    <section class="workspace-surface" id="{escape(section_id, quote=True)}" data-ui-section="{escape(section_id, quote=True)}">
      <div class="workspace-surface-head">
        <div>
          <p class="eyebrow">{escape(kicker)}</p>
          <h2>{escape(title)}</h2>
        </div>
        {actions}
      </div>
      <div class="workspace-surface-body">
        {body}
      </div>
    </section>
    """


WORKSPACE_SECTION_ORDER = (
    "overview",
    "application",
    "interviews",
    "follow-ups",
    "tasks",
    "notes",
    "documents",
)


def _normalize_workspace_section(section: str | None) -> str:
    if section in WORKSPACE_SECTION_ORDER:
        return section
    return "overview"


def _workspace_stat_count(value: int | str, label: str) -> str:
    return (
        '<div class="workspace-stat">'
        f"<strong>{escape(str(value))}</strong>"
        f"<span>{escape(label)}</span>"
        "</div>"
    )


def _latest_ai_output(outputs: list[AiOutput], output_type: str) -> AiOutput | None:
    for output in outputs:
        if output.output_type == output_type:
            return output
    return None


def _follow_up_events(job: Job) -> list[Communication]:
    return sorted(
        [event for event in job.communications if event.follow_up_at is not None],
        key=lambda event: event.follow_up_at or event.created_at,
    )


def _workspace_anchor_nav(job: Job, artefacts: list[Artefact], events: list[Communication], active_section: str) -> str:
    follow_up_count = len(_follow_up_events(job))
    items = [
        ("overview", "Overview", ""),
        ("application", "Application", str(len(job.applications)) if job.applications else "✓"),
        ("interviews", "Interviews", str(len(job.interviews)) if job.interviews else ""),
        ("follow-ups", "Follow-ups", str(follow_up_count) if follow_up_count else ""),
        ("tasks", "Tasks", "1"),
        ("notes", "Notes", str(len(events)) if events else ""),
        ("documents", "Documents", str(len(artefacts)) if artefacts else ""),
    ]
    rendered = []
    for target, label, count in items:
        badge = f'<span class="workspace-nav-count">{escape(count)}</span>' if count else ""
        rendered.append(
            f'<a class="workspace-nav-link{" active" if target == active_section else ""}" '
            f'href="/jobs/{escape(job.uuid, quote=True)}?section={escape(target, quote=True)}" '
            f'data-ui-nav="{escape(target, quote=True)}">'
            f"<span>{escape(label)}</span>{badge}</a>"
        )
    return '<nav class="workspace-anchor-nav" data-ui-component="section-nav">' + "".join(rendered) + "</nav>"


def _workspace_quick_actions(job: Job) -> str:
    actions = [
        ("Log interview", f"/jobs/{job.uuid}?section=interviews"),
        ("Add follow-up", f"/jobs/{job.uuid}?section=follow-ups"),
        ("Upload document", f"/jobs/{job.uuid}?section=documents"),
        ("Create AI draft", f"/jobs/{job.uuid}?section=documents"),
    ]
    rendered = "".join(
        f'<a class="workspace-quick-link" href="{escape(url, quote=True)}"><span>{escape(label)}</span><span>›</span></a>'
        for label, url in actions
    )
    return (
        '<details class="workspace-quick-actions" data-ui-component="quick-actions-overlay">'
        '<summary class="workspace-quick-trigger" data-ui-component="quick-actions-trigger">'
        '<span>Quick Actions</span><span>⌄</span>'
        '</summary>'
        '<div class="workspace-quick-panel" data-ui-component="quick-actions-panel">'
        '<div class="workspace-side-heading">Quick Actions</div>'
        '<p class="muted">Use these utility actions without adding permanent page height.</p>'
        f"{rendered}"
        "</div>"
        "</details>"
    )


def _workspace_readiness_score(job: Job, artefacts: list[Artefact]) -> tuple[int, int]:
    total = 4
    done = 0
    if job.title and job.description_raw:
        done += 1
    if job.apply_url or job.source_url:
        done += 1
    if artefacts:
        done += 1
    if job.applications:
        done += 1
    return done, total


def _workspace_score_card(job: Job, artefacts: list[Artefact]) -> str:
    done, total = _workspace_readiness_score(job, artefacts)
    percent = int((done / total) * 100) if total else 0
    label = "Ready to move" if done >= 3 else "Needs setup"
    summary = (
        "Core application inputs are in place."
        if done >= 3
        else "Add missing links, artefacts, or application detail before pushing this forward."
    )
    return f"""
    <section class="workspace-side-card" data-ui-component="workspace-score">
      <div class="workspace-side-heading">Readiness</div>
      <div class="workspace-score-card">
        <div class="workspace-score-ring" style="--score:{percent};">
          <span>{percent}</span>
        </div>
        <div>
          <strong>{escape(label)}</strong>
          <p class="muted">{escape(summary)}</p>
        </div>
      </div>
    </section>
    """


def _workspace_back_link_card() -> str:
    return '<a class="workspace-back-link" href="/board">← Back to Board</a>'


def _progress_step(status_key: str, label: str, current_index: int, index: int, date_label: str | None = None) -> str:
    state = ""
    dot = "○"
    if index < current_index:
        state = " done"
        dot = "✓"
    elif index == current_index:
        state = " active"
        dot = str(index + 1)
    subtitle = f"<span>{escape(date_label)}</span>" if date_label else ""
    return (
        f'<div class="progress-step{state}" data-ui-step="{escape(status_key, quote=True)}">'
        f'<div class="progress-dot">{escape(dot)}</div>'
        f'<div><strong>{escape(label)}</strong>{subtitle}</div>'
        "</div>"
    )


def _application_progress(job: Job) -> str:
    stages = [
        ("saved", "Saved"),
        ("interested", "Interested"),
        ("preparing", "Preparing"),
        ("applied", "Applied"),
        ("interviewing", "Interviewing"),
        ("offer", "Offer"),
    ]
    current_lookup = {key: idx for idx, (key, _) in enumerate(stages)}
    current_index = current_lookup.get(job.status, 0)
    latest_application = max(job.applications, key=lambda item: item.applied_at or datetime.min.replace(tzinfo=UTC), default=None)
    latest_interview = min(
        [item for item in job.interviews if item.scheduled_at is not None],
        key=lambda item: item.scheduled_at or datetime.max.replace(tzinfo=UTC),
        default=None,
    )
    step_dates: dict[str, str] = {}
    if latest_application and latest_application.applied_at:
        step_dates["applied"] = latest_application.applied_at.strftime("%b %d")
    if latest_interview and latest_interview.scheduled_at:
        step_dates["interviewing"] = latest_interview.scheduled_at.strftime("%b %d")
    step_dates["saved"] = job.created_at.strftime("%b %d")
    steps = "".join(
        _progress_step(status_key, label, current_index, index, step_dates.get(status_key))
        for index, (status_key, label) in enumerate(stages)
    )
    timeline_action = '<a class="workspace-inline-link" href="#notes">View Timeline</a>'
    return f"""
    <section class="workspace-progress-card" data-ui-component="application-progress">
      <div class="workspace-progress-head">
        <div class="workspace-side-heading">Application Progress</div>
        {timeline_action}
      </div>
      <div class="workspace-progress-line">{steps}</div>
    </section>
    """


def _next_up_summary(job: Job, ai_outputs: list[AiOutput]) -> str:
    next_interview = min(
        [item for item in job.interviews if item.scheduled_at is not None],
        key=lambda item: item.scheduled_at or datetime.max.replace(tzinfo=UTC),
        default=None,
    )
    if next_interview and next_interview.scheduled_at:
        lead = "Next Up"
        title = next_interview.stage
        when = _value(next_interview.scheduled_at)
        guidance = "Prepare for the next conversation with current role context, materials, and likely questions."
        checklist = [
            ("Review the role narrative and current application state", True),
            ("Prepare questions and follow-up points", True),
            ("Capture any open research items", False),
        ]
        primary_action = '<a class="button-link" href="#interviews">View Details</a>'
    else:
        lead = "Next Up"
        title = "Keep this moving"
        when = "No interview is scheduled yet."
        guidance = "Use the next action, external links, and artefact tools to move the application forward deliberately."
        checklist = [
            ("Check the application route and source link", True),
            ("Confirm the right artefact baseline is attached", bool(linked_artefacts_for_job(job))),
            ("Generate guidance only when it helps the decision", False),
        ]
        primary_action = '<a class="button-link" href="#tasks">View Details</a>'
    recommendation = _latest_ai_output(ai_outputs, "recommendation")
    ai_action = (
        f'<form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs">'
        '<input type="hidden" name="output_type" value="recommendation">'
        '<button type="submit">Prepare with AI</button>'
        '</form>'
    )
    checklist_html = "".join(
        f'<div class="workspace-check{" done" if done else " pending"}">'
        f'<div class="workspace-check-mark">{"✓" if done else ""}</div>'
        f"<div>{escape(label)}</div>"
        "</div>"
        for label, done in checklist
    )
    recommendation_note = ""
    if recommendation is not None:
        recommendation_note = (
            f'<p class="muted">{escape((recommendation.body or "").splitlines()[0][:180])}</p>'
        )
    return f"""
    <section class="workspace-next-up" data-ui-component="next-up">
      <div class="workspace-next-left">
        <p class="eyebrow">{escape(lead)}</p>
        <div class="workspace-next-title">{escape(title)}</div>
        <p class="muted">{escape(when)}</p>
      </div>
      <div class="workspace-next-right">
        <div class="workspace-next-copy">
          <strong>{escape(guidance)}</strong>
          {recommendation_note}
        </div>
        <div class="workspace-checklist">{checklist_html}</div>
        <div class="workspace-split-actions">{primary_action}{ai_action}</div>
      </div>
    </section>
    """


def _workspace_identity_header(job: Job) -> str:
    meta_parts = [
        job.company or "Company not set",
        job.location or "Location not set",
        job.remote_policy or None,
        _salary_range(job) if job.salary_min is not None or job.salary_max is not None else None,
    ]
    meta = " · ".join(escape(part) for part in meta_parts if part)
    return f"""
    <div class="workspace-identity-head" data-ui-component="overview-identity">
      <div>
        <div class="workspace-identity-title">{_editable_title(job)}</div>
        <p class="muted">{meta}</p>
      </div>
      <div class="workspace-identity-status">{_stage_pill(job.status)}</div>
    </div>
    """


def _workspace_overview_section(job: Job, ai_outputs: list[AiOutput]) -> str:
    tags = [
        job.source,
        "Inbox candidate" if job.intake_state == "needs_review" else "Active work",
    ]
    chips = "".join(f'<span class="workspace-chip">{escape(tag)}</span>' for tag in tags if tag)
    insight = _latest_ai_output(ai_outputs, "fit_summary") or _latest_ai_output(ai_outputs, "recommendation")
    insight_block = ""
    if insight is not None:
        insight_line = next((line for line in insight.body.splitlines() if line.strip()), insight.body)
        insight_block = (
            '<div class="workspace-inline-ai" data-ui-component="overview-ai">'
            f'<span class="workspace-ai-pill">{escape(insight.title or "AI insight")}</span>'
            f"<span>{escape(insight_line[:220])}</span>"
            "</div>"
        )
    body = f"""
    {_application_progress(job)}
    {_next_up_summary(job, ai_outputs)}
    <div class="workspace-detail-copy">
      <div class="workspace-text-block workspace-constrained-panel" data-ui-component="job-description-panel">
        <h3>Role &amp; Notes</h3>
        <div class="workspace-constrained-body job-description-body" data-ui-component="job-description-body">
          {_editable_description(job)}
        </div>
      </div>
      <div class="workspace-chip-row">{chips}</div>
      {insight_block}
    </div>
    """
    return _workspace_section(section_id="overview", kicker="Overview", title="Overview", body=body)


def _workspace_role_notes_section(job: Job) -> str:
    chips = [
        job.source,
        job.remote_policy,
        "Inbox candidate" if job.intake_state == "needs_review" else None,
    ]
    chip_html = "".join(f'<span class="workspace-chip">{escape(chip)}</span>' for chip in chips if chip)
    chip_html += '<span class="workspace-add-chip">+ Add tag</span>'
    actions = (
        '<a class="workspace-inline-link" href="#workspace-tools">Edit</a>'
        f'<a class="workspace-inline-link" href="/competencies?source_job_uuid={escape(job.uuid, quote=True)}">'
        "Create evidence from this role</a>"
    )
    body = f"""
    <div class="workspace-text-block">
      {_editable_description(job)}
    </div>
    <div class="workspace-chip-row">{chip_html}</div>
    """
    return _workspace_section(
        section_id="role-notes",
        kicker="Overview",
        title="Role & notes",
        body=body,
        actions=actions,
    )


def _application_state_bar(job: Job) -> str:
    pill = _stage_pill(job.status)
    apply_btn = _button_link("Open apply link ↗", job.apply_url, primary=True)
    source_btn = _button_link("Open source ↗", job.source_url)
    next_action_map = {
        "saved": ("Make a decision", "Mark interested to start spending attention on this role."),
        "interested": ("Prepare your application", "Confirm the description, links, and artefacts are in place."),
        "preparing": ("Submit when ready", "Use the apply link to submit, then record it here."),
        "applied": ("Track the response", "Record recruiter contact, interview scheduling, and follow-ups as they arrive."),
        "interviewing": ("Prepare for interviews", "Keep prep notes, participants, and follow-up actions attached."),
        "offer": ("Decide on the offer", "Record your decision and archive when the outcome is complete."),
        "rejected": ("Capture the learning", "Add notes and archive when no longer needed."),
        "archived": ("Archived", "Restore only if this role needs active work again."),
    }
    action_title, action_body = next_action_map.get(job.status, ("Choose the next step", "Use workflow controls below to move forward."))
    return f"""
    <div class="app-state-bar" data-ui-component="application-state-bar">
      <div class="app-state-context">
        {pill}
        <div>
          <strong class="app-state-title">{escape(action_title)}</strong>
          <p class="muted">{escape(action_body)}</p>
        </div>
      </div>
      <div class="app-state-cta">
        {apply_btn}
        {source_btn}
      </div>
    </div>
    """


def _workspace_application_section(job: Job) -> str:
    has_applications = bool(job.applications)
    history_html = _applications(job.applications) if has_applications else '<p class="empty">No submission recorded yet.</p>'
    body = f"""
    {_application_state_bar(job)}
    <div class="workspace-two-up" data-ui-component="application-workbench">
      <div class="workspace-subpanel">
        <h3>Role details</h3>
        <dl class="overview-grid">
          {_editable_text("Company", "company", job.company)}
          {_editable_text("Location", "location", job.location)}
          {_editable_text("Remote policy", "remote_policy", job.remote_policy)}
          {_editable_text("Salary min", "salary_min", job.salary_min)}
          {_editable_text("Salary max", "salary_max", job.salary_max)}
          {_editable_text("Currency", "salary_currency", job.salary_currency)}
        </dl>
      </div>
      <div class="workspace-subpanel">
        <h3>Application route</h3>
        <dl>
          {_editable_select("Status", "status", job.status)}
          {_editable_text("Source", "source", job.source)}
          {_editable_url("Source URL", "source_url", job.source_url, "Open source")}
          {_editable_url("Apply URL", "apply_url", job.apply_url, "Open apply link")}
        </dl>
      </div>
    </div>
    <div class="workspace-two-up">
      <div class="workspace-subpanel">
        <h3>Submission history</h3>
        {history_html}
        <details class="workspace-form-disclosure">
          <summary>Record a submission</summary>
          {_mark_applied_form(job)}
        </details>
      </div>
      <div class="workspace-subpanel">
        <h3>Advance status</h3>
        <p class="muted">Move this job to the right board position.</p>
        {_status_transition_form(job)}
        <details class="workspace-form-disclosure">
          <summary>Start application externally</summary>
          {_application_started_form(job)}
        </details>
      </div>
    </div>
    """
    return _workspace_section(
        section_id="application",
        kicker="Application",
        title="Application",
        body=body,
    )


def _artefact_type_label(artefact: Artefact) -> str:
    labels = {
        "resume": "Resume",
        "cover_letter": "Cover letter",
        "supporting_statement": "Supporting statement",
        "attestation": "Attestation",
    }
    return labels.get(artefact.kind, artefact.kind.replace("_", " ").title())


def _artefact_primary_badge(artefact: Artefact) -> str:
    if artefact.kind == "resume":
        return '<span class="mini-pill">Primary</span>'
    return ""


def _latest_artefact_ai_output(outputs: list[AiOutput], artefacts: list[Artefact]) -> AiOutput | None:
    artefact_ids = {artefact.id for artefact in artefacts}
    preferred = ("draft", "tailoring_guidance", "artefact_analysis", "artefact_suggestion")
    for output_type in preferred:
        for output in outputs:
            if output.output_type != output_type:
                continue
            if output.artefact_id is None or output.artefact_id in artefact_ids:
                return output
    return None


def _normalize_local_ai_tab(value: str | None) -> str | None:
    valid = {"analyse", "tailor", "draft", "compare"}
    normalized = (value or "").strip().lower()
    return normalized if normalized in valid else None


def _normalize_generation_brief_action(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    return normalized if normalized in {"tailor", "draft"} else None


def _normalize_draft_kind(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized in {
        "resume_draft",
        "cover_letter_draft",
        "supporting_statement_draft",
        "attestation_draft",
    }:
        return normalized
    return "resume_draft"


def _generation_brief_fields(
    *,
    focus_areas: str = "",
    must_include: str = "",
    avoid: str = "",
    tone: str = "",
    extra_context: str = "",
) -> dict[str, str]:
    return {
        "focus_areas": focus_areas,
        "must_include": must_include,
        "avoid": avoid,
        "tone": tone,
        "extra_context": extra_context,
    }


def _generation_brief_summary(source_context: dict[str, object] | None) -> str:
    if not source_context:
        return ""
    brief = source_context.get("generation_brief")
    if not isinstance(brief, dict):
        return ""
    labels = {
        "focus_areas": "Focus",
        "must_include": "Must include",
        "avoid": "Avoid",
        "tone": "Tone",
        "extra_context": "Context",
    }
    parts = []
    for key in ("focus_areas", "must_include", "avoid", "tone", "extra_context"):
        value = brief.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{labels[key]}: {value.strip()}")
    if not parts:
        return ""
    return '<p class="muted">Brief used: ' + " | ".join(escape(part) for part in parts) + "</p>"


def _competency_result_snippet(evidence: CompetencyEvidence) -> str:
    return evidence.result or evidence.action or evidence.situation or "Result not captured yet"


def _selected_competency_evidence_summary(source_context: dict[str, object] | None) -> str:
    if not source_context:
        return ""
    selected = source_context.get("selected_competency_evidence_uuids")
    if not isinstance(selected, list):
        return ""
    count = len([item for item in selected if isinstance(item, str) and item])
    if count == 0:
        return ""
    label = "example" if count == 1 else "examples"
    return f'<p class="muted">Competency evidence used: {count} {label}</p>'


def _generation_brief_items(source_context: dict[str, object] | None) -> list[tuple[str, str]]:
    if not source_context:
        return []
    brief = source_context.get("generation_brief")
    if not isinstance(brief, dict):
        return []
    labels = {
        "focus_areas": "Focus areas",
        "must_include": "Must include",
        "avoid": "Avoid or de-emphasise",
        "tone": "Tone or positioning",
        "extra_context": "Extra context",
    }
    items: list[tuple[str, str]] = []
    for key in ("focus_areas", "must_include", "avoid", "tone", "extra_context"):
        value = brief.get(key)
        if isinstance(value, str) and value.strip():
            items.append((labels[key], value.strip()))
    return items


def _selected_competency_evidence_items(source_context: dict[str, object] | None) -> list[tuple[str, str]]:
    if not source_context:
        return []
    refs = source_context.get("selected_competency_evidence_refs")
    if not isinstance(refs, list):
        return []
    items: list[tuple[str, str]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        title = ref.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        details = []
        competency = ref.get("competency")
        if isinstance(competency, str) and competency.strip():
            details.append(competency.strip())
        strength = ref.get("strength")
        if isinstance(strength, str) and strength.strip():
            details.append(strength.strip())
        shaping_output_id = ref.get("latest_star_shaping_output_id")
        if isinstance(shaping_output_id, int):
            details.append(f"STAR shaping output #{shaping_output_id}")
        value = title.strip()
        if details:
            value = f"{value} ({'; '.join(details)})"
        items.append(("Competency evidence", value))
    return items


def _local_ai_metadata_panel(output: AiOutput, source_context: dict[str, object]) -> str:
    metadata_rows: list[str] = []
    prompt_contract = source_context.get("prompt_contract")
    if isinstance(prompt_contract, str) and prompt_contract:
        metadata_rows.append(f"<div><dt>Prompt contract</dt><dd>{escape(prompt_contract)}</dd></div>")
    content_mode = source_context.get("content_mode")
    if isinstance(content_mode, str) and content_mode:
        metadata_rows.append(f"<div><dt>Content mode</dt><dd>{escape(content_mode)}</dd></div>")
    draft_kind = source_context.get("draft_kind")
    if isinstance(draft_kind, str) and draft_kind:
        metadata_rows.append(f"<div><dt>Draft kind</dt><dd>{escape(draft_kind)}</dd></div>")
    saved_artefact_uuid = source_context.get("saved_artefact_uuid")
    if isinstance(saved_artefact_uuid, str) and saved_artefact_uuid:
        metadata_rows.append(f"<div><dt>Saved artefact</dt><dd>{escape(saved_artefact_uuid)}</dd></div>")
    brief_items = _generation_brief_items(source_context)
    if brief_items:
        metadata_rows.extend(
            f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in brief_items
        )
    evidence_items = _selected_competency_evidence_items(source_context)
    if evidence_items:
        metadata_rows.extend(
            f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in evidence_items
        )
    if not metadata_rows:
        return ""
    return (
        '<details class="workspace-ai-metadata" data-ui-component="ai-generation-metadata">'
        "<summary>Generation metadata</summary>"
        '<dl class="workspace-ai-metadata-grid">'
        + "".join(metadata_rows)
        + "</dl></details>"
    )


def _local_ai_tab_label(tab: str) -> str:
    return {
        "analyse": "Analyse",
        "tailor": "Tailor",
        "draft": "Draft",
        "compare": "Compare",
    }[tab]


def _local_ai_output_tab(output_type: str) -> str | None:
    return {
        "artefact_analysis": "analyse",
        "tailoring_guidance": "tailor",
        "draft": "draft",
        "artefact_suggestion": "compare",
    }.get(output_type)


def _artefact_local_ai_workspace(
    job: Job,
    outputs: list[AiOutput],
    artefact_lookup: dict[str, Artefact],
    *,
    selected_artefact_uuid: str | None = None,
    selected_tab: str | None = None,
) -> str:
    outputs = [output for output in outputs if _local_ai_output_tab(output.output_type) is not None]
    if not outputs:
        body = """
        <div class="workspace-ai-generate-box">
          <div class="workspace-ai-generate-title">Start AI work from an artefact</div>
          <p class="muted">Use one AI action per artefact to tailor, draft, or compare without filling the whole page with output.</p>
        </div>
        <div class="workspace-ai-results">
          <div class="workspace-ai-results-title">No local AI workspace is active yet</div>
          <p class="muted">Choose an artefact action such as tailoring or draft generation to open a focused AI workspace here.</p>
        </div>
        """
        return f"""
        <section class="workspace-local-ai" data-ui-component="artefact-ai-workspace">
          <div class="workspace-local-ai-head">
            <div class="workspace-local-ai-title">AI Workspace</div>
          </div>
          <div class="workspace-local-ai-body inactive">{body}</div>
        </section>
        """

    outputs_by_artefact: dict[str, list[AiOutput]] = {}
    generic_outputs: list[AiOutput] = []
    artefact_by_id = {artefact.id: artefact for artefact in artefact_lookup.values()}
    sole_artefact_uuid = next(iter(artefact_lookup.keys()), None) if len(artefact_lookup) == 1 else None
    for output in outputs:
        source_context = output.source_context or {}
        artefact_uuid = source_context.get("artefact_uuid")
        resolved_uuid: str | None = artefact_uuid if isinstance(artefact_uuid, str) else None
        if resolved_uuid not in artefact_lookup and output.artefact_id is not None:
            resolved_uuid = artefact_by_id.get(output.artefact_id).uuid if output.artefact_id in artefact_by_id else None
        if resolved_uuid not in artefact_lookup:
            resolved_uuid = sole_artefact_uuid
        if resolved_uuid in artefact_lookup:
            outputs_by_artefact.setdefault(resolved_uuid, []).append(output)
        else:
            generic_outputs.append(output)
    if not outputs_by_artefact and not generic_outputs:
        return ""

    default_output = outputs[0]
    default_artefact_uuid = str((default_output.source_context or {}).get("artefact_uuid") or "")
    active_artefact_uuid = selected_artefact_uuid if selected_artefact_uuid in outputs_by_artefact else default_artefact_uuid
    using_generic_outputs = active_artefact_uuid not in outputs_by_artefact
    artefact_outputs = outputs_by_artefact.get(active_artefact_uuid, generic_outputs or outputs)
    output_by_tab = {
        tab: item
        for item in artefact_outputs
        if (tab := _local_ai_output_tab(item.output_type)) is not None
    }
    active_tab = selected_tab if selected_tab in output_by_tab else (_local_ai_output_tab(artefact_outputs[0].output_type) or "draft")
    output = output_by_tab.get(active_tab, artefact_outputs[0])

    source_context = output.source_context or {}
    artefact_name = artefact_lookup.get(active_artefact_uuid).filename if active_artefact_uuid in artefact_lookup else "Workspace"
    tabs = "".join(
        (
            f'<a class="workspace-local-ai-tab{" active" if tab == active_tab else ""}" '
            f'href="/jobs/{escape(job.uuid, quote=True)}?section=documents'
            f'{"&ai_artefact=" + quote(active_artefact_uuid) if not using_generic_outputs and active_artefact_uuid else ""}&ai_tab={tab}">'
            f"{escape(_local_ai_tab_label(tab))}</a>"
        )
        if tab in output_by_tab
        else f'<div class="workspace-local-ai-tab unavailable">{escape(_local_ai_tab_label(tab))}</div>'
        for tab in ("analyse", "tailor", "draft", "compare")
    )
    actions = []
    if output.output_type == "draft":
        actions.append(
            f'<form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs/{output.id}/save-draft">'
            '<button type="submit">Save as artefact</button>'
            "</form>"
        )
    else:
        actions.append('<button class="outline" type="button" disabled>Copy</button>')
    actions.append('<button class="outline" type="button" disabled>Regenerate</button>')
    content_note = ""
    if source_context.get("content_mode") == "metadata_only":
        content_note = '<p class="muted">Generated from metadata and job context because verified document text was not available.</p>'
    links = ""
    if output.output_type == "draft":
        links = _draft_links(output, artefact_lookup)
    elif output.output_type == "artefact_analysis":
        links = _artefact_analysis_links(output, artefact_lookup)
    elif output.output_type == "tailoring_guidance":
        links = _tailoring_guidance_links(output, artefact_lookup)
    elif output.output_type == "artefact_suggestion":
        links = _artefact_suggestion_links(output, artefact_lookup)
    provider_line = f'<p class="muted">From {escape(output.model_name or output.provider or "AI")}</p>'
    brief_line = _generation_brief_summary(source_context)
    competency_line = _selected_competency_evidence_summary(source_context)
    metadata_panel = _local_ai_metadata_panel(output, source_context)
    body = f"""
    <div class="workspace-ai-results">
      <div class="workspace-ai-results-title">{escape(output.title or output.output_type.replace('_', ' ').title())}</div>
      {provider_line}
      {brief_line}
      {competency_line}
      {metadata_panel}
      {_render_ai_markdown(output.body)}
      {content_note}
      {links}
    </div>
    """
    return f"""
    <section class="workspace-local-ai" data-ui-component="artefact-ai-workspace">
      <div class="workspace-local-ai-head">
        <div class="workspace-local-ai-title">AI Workspace - {escape(artefact_name)}</div>
        <div class="generated-ok">Visible AI output</div>
      </div>
      <div class="workspace-local-ai-tabs">{tabs}</div>
      <div class="workspace-local-ai-body">{body}</div>
      <div class="workspace-local-ai-foot">{"".join(actions)}</div>
    </section>
    """


def _generation_brief_modal(
    job: Job,
    artefact: Artefact | None,
    *,
    action: str | None,
    draft_kind: str = "resume_draft",
    fields: dict[str, str] | None = None,
    competency_evidence_items: list[CompetencyEvidence] | None = None,
) -> str:
    if artefact is None or action not in {"tailor", "draft"}:
        return ""
    fields = fields or _generation_brief_fields()
    draft_kind = _normalize_draft_kind(draft_kind)
    title = "Tailor with optional brief" if action == "tailor" else "Draft with optional brief"
    submit_label = "Generate tailoring guidance" if action == "tailor" else "Generate draft"
    target = (
        f"/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/tailoring-guidance"
        if action == "tailor"
        else f"/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/drafts"
    )
    kind_input = (
        ""
        if action == "tailor"
        else f'<input type="hidden" name="draft_kind" value="{escape(draft_kind, quote=True)}">'
    )
    evidence_items = competency_evidence_items or []
    if evidence_items:
        evidence_rows = "".join(
            f"""
            <label class="competency-selector-row">
              <input type="checkbox" name="selected_competency_evidence_uuids" value="{escape(evidence.uuid, quote=True)}">
              <span>
                <strong>{escape(evidence.title)}</strong>
                <span>{escape(evidence.competency or "Competency not set")} · {escape(evidence.strength)}</span>
                <small>{escape(_competency_result_snippet(evidence))}</small>
              </span>
            </label>
            """
            for evidence in evidence_items[:8]
        )
        evidence_selector = f"""
          <details class="competency-selector" data-ui-component="generation-brief-competency-selector">
            <summary>Use competency evidence</summary>
            <div class="competency-selector-list">
              {evidence_rows}
            </div>
          </details>
        """
    else:
        evidence_selector = """
          <details class="competency-selector" data-ui-component="generation-brief-competency-selector">
            <summary>Use competency evidence</summary>
            <p class="muted">No competency evidence saved yet.</p>
          </details>
        """
    cancel_href = _job_detail_redirect(
        job.uuid,
        section="documents",
        ai_artefact=artefact.uuid,
        ai_tab="tailor" if action == "tailor" else "draft",
    )
    return f"""
    <div class="workspace-modal-backdrop" data-ui-component="generation-brief-modal">
      <section class="workspace-modal-card">
        <div class="workspace-modal-head">
          <div>
            <div class="workspace-modal-title">{escape(title)}</div>
            <p class="muted">Optional guidance can steer emphasis, tone, and examples. Leave everything blank to use the current default AI behaviour.</p>
          </div>
          <a class="button-link" href="{escape(cancel_href, quote=True)}">Close</a>
        </div>
        <form class="workspace-brief-form" method="post" action="{target}">
          {kind_input}
          <label>Focus areas
            <textarea name="focus_areas" rows="3" placeholder="Specific accomplishments, competencies, or themes to foreground">{escape(fields.get("focus_areas", ""))}</textarea>
          </label>
          <label>Must include
            <textarea name="must_include" rows="3" placeholder="Skills, tools, role requirements, or examples that must appear">{escape(fields.get("must_include", ""))}</textarea>
          </label>
          <label>Avoid or de-emphasise
            <textarea name="avoid" rows="2" placeholder="Material to keep brief, downplay, or leave out">{escape(fields.get("avoid", ""))}</textarea>
          </label>
          <div class="inline-fields brief-inline-fields">
            <label>Tone or positioning
              <input type="text" name="tone" value="{escape(fields.get("tone", ""), quote=True)}" placeholder="Concise, assertive, leadership-focused, formal">
            </label>
            <label>Extra context
              <input type="text" name="extra_context" value="{escape(fields.get("extra_context", ""), quote=True)}" placeholder="Anything specific for this role or application">
            </label>
          </div>
          {evidence_selector}
          <div class="workspace-modal-actions">
            <button type="submit">{escape(submit_label)}</button>
            <button class="outline" type="submit" name="skip_brief" value="1">Generate without brief</button>
          </div>
        </form>
      </section>
    </div>
    """


def _workspace_artefact_item(job: Job, artefact: Artefact) -> str:
    updated = escape(_value(artefact.updated_at))
    badges = _artefact_primary_badge(artefact)
    return f"""
    <article class="workspace-artefact-item">
      <div class="workspace-artefact-left">
        <div class="workspace-doc-icon">▣</div>
        <div>
          <div class="workspace-artefact-name" title="{escape(artefact.filename, quote=True)}">{escape(artefact.filename)}</div>
          <div class="meta-row">
            <span>{escape(_artefact_type_label(artefact))}</span>
            <span>•</span>
            <span>Updated {updated}</span>
            {badges}
          </div>
        </div>
      </div>
      <div class="workspace-artefact-actions">
        <a class="action-btn" href="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}">Open</a>
        <a class="action-btn" href="/artefacts/{escape(artefact.uuid, quote=True)}/download">↓</a>
        <details class="workspace-ai-menu">
          <summary class="action-btn ai">✦ AI ⌄</summary>
          <div class="workspace-ai-menu-body">
            <a class="button-link menu-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents&ai_artefact={escape(artefact.uuid, quote=True)}&ai_tab=tailor&brief_action=tailor">Tailor</a>
            <a class="button-link menu-link" href="/competencies?source_artefact_uuid={escape(artefact.uuid, quote=True)}">Create evidence</a>
            <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/analysis">
              <button class="outline" type="submit">Analyse</button>
            </form>
            <a class="button-link menu-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents&ai_artefact={escape(artefact.uuid, quote=True)}&ai_tab=draft&brief_action=draft&brief_draft_kind=resume_draft">Draft tailored resume</a>
            <a class="button-link menu-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents&ai_artefact={escape(artefact.uuid, quote=True)}&ai_tab=draft&brief_action=draft&brief_draft_kind=cover_letter_draft">Draft cover letter</a>
            <a class="button-link menu-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents&ai_artefact={escape(artefact.uuid, quote=True)}&ai_tab=draft&brief_action=draft&brief_draft_kind=supporting_statement_draft">Draft supporting statement</a>
            <a class="button-link menu-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents&ai_artefact={escape(artefact.uuid, quote=True)}&ai_tab=draft&brief_action=draft&brief_draft_kind=attestation_draft">Draft attestation</a>
          </div>
        </details>
      </div>
    </article>
    """


def _workspace_artefacts_section(
    job: Job,
    artefacts: list[Artefact],
    available_artefacts: list[Artefact],
    ai_outputs: list[AiOutput],
    artefact_lookup: dict[str, Artefact],
    *,
    selected_artefact_uuid: str | None = None,
    selected_ai_tab: str | None = None,
) -> str:
    artefact_list = "".join(_workspace_artefact_item(job, artefact) for artefact in artefacts)
    if not artefact_list:
        artefact_list = '<p class="empty">No artefacts uploaded yet.</p>'
    body = f"""
    <div class="workspace-two-up" data-ui-component="documents-workbench">
      <div class="workspace-subpanel">
        <h3>Active documents</h3>
        <div class="workspace-artefact-list" data-ui-component="artefact-list">
          {artefact_list}
        </div>
      </div>
      <div class="workspace-subpanel">
        <h3>Document actions</h3>
        <details id="documents-attach-tools">
          <summary>Attach or upload</summary>
          <div class="workspace-stack">
            {_link_existing_artefact_form(job, available_artefacts)}
            {_artefact_form(job)}
          </div>
        </details>
        <details>
          <summary>Competency evidence</summary>
          <a class="button-link" href="/competencies?source_job_uuid={escape(job.uuid, quote=True)}">Create evidence from this role</a>
        </details>
      </div>
    </div>
    {_artefact_local_ai_workspace(job, ai_outputs, artefact_lookup, selected_artefact_uuid=selected_artefact_uuid, selected_tab=selected_ai_tab)}
    """
    return _workspace_section(
        section_id="documents",
        kicker="Documents",
        title="Artefacts",
        body=body,
    )


def _interview_card(interview: InterviewEvent) -> str:
    scheduled = _value(interview.scheduled_at) if interview.scheduled_at else "Time not set"
    location = escape(interview.location or "No location")
    participants = escape(interview.participants or "")
    notes_html = f'<p class="muted">{escape(interview.notes)}</p>' if interview.notes else ""
    return f"""
    <article class="interview-card">
      <div class="interview-card-head">
        <strong>{escape(interview.stage)}</strong>
        <span class="workspace-ai-pill">{escape(scheduled)}</span>
      </div>
      <p class="muted">{location}{(" · " + participants) if interview.participants else ""}</p>
      {notes_html}
    </article>
    """


def _interview_cards(interviews: list[InterviewEvent]) -> str:
    if not interviews:
        return '<p class="empty">No interviews scheduled yet.</p>'
    sorted_interviews = sorted(
        interviews,
        key=lambda item: item.scheduled_at or datetime.max.replace(tzinfo=UTC),
    )
    return "".join(_interview_card(i) for i in sorted_interviews)


def _workspace_interviews_section(job: Job) -> str:
    next_interview = min(
        (i for i in job.interviews if i.scheduled_at),
        key=lambda i: i.scheduled_at,
        default=None,
    )
    state_hint = ""
    if next_interview and next_interview.scheduled_at:
        state_hint = f"""
        <div class="app-state-bar">
          <div class="app-state-context">
            <span class="stage-pill active">Upcoming</span>
            <div>
              <strong class="app-state-title">{escape(next_interview.stage)}</strong>
              <p class="muted">{escape(_value(next_interview.scheduled_at))} · {escape(next_interview.location or "No location")}</p>
            </div>
          </div>
          <div class="app-state-cta">
            {_compact_status_form(job, "offer", "Record offer", variant="outline") if job.status == "interviewing" else ""}
          </div>
        </div>
        """
    body = f"""
    {state_hint}
    <div class="workspace-two-up" data-ui-component="interviews-workbench">
      <div class="workspace-subpanel">
        <h3>Interview loop</h3>
        <div class="interview-card-list">
          {_interview_cards(job.interviews)}
        </div>
      </div>
      <div class="workspace-subpanel">
        <h3>Schedule interview</h3>
        {_schedule_interview_form(job)}
      </div>
    </div>
    """
    return _workspace_section(section_id="interviews", kicker="Interviews", title="Interviews", body=body)


def _follow_up_list(job: Job) -> str:
    follow_ups = _follow_up_events(job)
    if not follow_ups:
        return '<p class="empty">No follow-ups scheduled yet.</p>'
    items = []
    for event in follow_ups:
        items.append(
            "<li>"
            f"<strong>{escape(event.subject or 'Follow-up')}</strong>"
            f"<p>{escape(_value(event.follow_up_at))}</p>"
            f"{f'<p>{escape(event.notes)}</p>' if event.notes else ''}"
            "</li>"
        )
    return "<ol>" + "".join(items) + "</ol>"


def _follow_up_card(event: Communication) -> str:
    due = event.follow_up_at
    now = datetime.now(UTC)
    if due and due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    is_overdue = due is not None and due < now
    pill_class = "stage-pill active" if is_overdue else "workspace-ai-pill"
    pill_label = "Overdue" if is_overdue else _value(due)
    notes_html = f'<p class="muted">{escape(event.notes)}</p>' if event.notes else ""
    return f"""
    <article class="follow-up-card{' overdue' if is_overdue else ''}">
      <div class="follow-up-card-head">
        <strong>{escape(event.subject or "Follow-up")}</strong>
        <span class="{pill_class}">{escape(pill_label)}</span>
      </div>
      {notes_html}
    </article>
    """


def _follow_up_cards(job: Job) -> str:
    follow_ups = _follow_up_events(job)
    if not follow_ups:
        return '<p class="empty">No follow-ups scheduled yet.</p>'
    return "".join(_follow_up_card(e) for e in follow_ups)


def _workspace_follow_ups_section(job: Job) -> str:
    count = len(_follow_up_events(job))
    state_label = f"{count} scheduled" if count else "None scheduled"
    body = f"""
    <div class="workspace-two-up" data-ui-component="follow-ups-workbench">
      <div class="workspace-subpanel">
        <h3>Follow-up queue <span class="workspace-nav-count">{escape(str(count)) if count else "0"}</span></h3>
        <div class="follow-up-card-list">
          {_follow_up_cards(job)}
        </div>
      </div>
      <div class="workspace-subpanel">
        <h3>Add a note or follow-up</h3>
        {_note_form(job)}
      </div>
    </div>
    <div class="workspace-two-up">
      <div class="workspace-subpanel">
        <details class="workspace-form-disclosure">
          <summary>Record a blocker</summary>
          {_blocker_form(job)}
        </details>
        <details class="workspace-form-disclosure">
          <summary>Record a return note</summary>
          {_return_note_form(job)}
        </details>
      </div>
      <div class="workspace-subpanel">
        <details class="workspace-form-disclosure">
          <summary>Mark application started</summary>
          {_application_started_form(job)}
        </details>
      </div>
    </div>
    """
    return _workspace_section(section_id="follow-ups", kicker="Follow-ups", title="Follow-ups", body=body)


def _workspace_tasks_section(job: Job, artefacts: list[Artefact]) -> str:
    done, total = _workspace_readiness_score(job, artefacts)
    readiness_pill = f'<span class="workspace-ai-pill">Ready {done}/{total}</span>'
    body = f"""
    <div class="workspace-two-up" data-ui-component="tasks-workbench">
      <div class="workspace-subpanel">
        <h3>Next action</h3>
        {_next_action(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Readiness {readiness_pill}</h3>
        <ol class="readiness-list">
          {_readiness_item("Role captured", bool(job.title and job.description_raw), "Title and description in place." if job.description_raw else "Add the job description.")}
          {_readiness_item("Application link", bool(job.apply_url or job.source_url), "External route is set." if job.apply_url or job.source_url else "Add a source or apply URL.")}
          {_readiness_item("Artefacts attached", bool(artefacts), "Files are attached." if artefacts else "Upload a resume or prep file.")}
          {_readiness_item("Application recorded", bool(job.applications), "Submission on record." if job.applications else "Mark applied once submitted.")}
        </ol>
        <a class="workspace-inline-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents">Open documents ›</a>
      </div>
    </div>
    <div class="workspace-two-up">
      <div class="workspace-subpanel">
        <h3>Workflow actions</h3>
        <details class="workspace-form-disclosure">
          <summary>Record submission</summary>
          {_mark_applied_form(job)}
        </details>
        <details class="workspace-form-disclosure">
          <summary>Advance status</summary>
          {_status_transition_form(job)}
        </details>
        <details class="workspace-form-disclosure">
          <summary>Schedule interview</summary>
          {_schedule_interview_form(job)}
        </details>
      </div>
      <div class="workspace-subpanel">
        <h3>Maintenance</h3>
        <details class="workspace-form-disclosure">
          <summary>Archive this job</summary>
          {_archive_form(job)}
        </details>
        <details class="workspace-form-disclosure">
          <summary>Restore archived job</summary>
          {_unarchive_form(job)}
        </details>
      </div>
    </div>
    """
    return _workspace_section(section_id="tasks", kicker="Tasks", title="Tasks", body=body)


def _recent_activity(job: Job, events: list[Communication], artefacts: list[Artefact]) -> str:
    entries: list[tuple[datetime, str, str, str]] = []
    for event in events[:6]:
        occurred_at = event.occurred_at or event.created_at
        entries.append((occurred_at, "◷", event.subject or event.event_type, _value(occurred_at)))
    for application in job.applications:
        if application.applied_at:
            entries.append((application.applied_at, "✓", "Application submitted", _value(application.applied_at)))
    for artefact in artefacts:
        entries.append((artefact.updated_at, "▣", f"{artefact.filename} available", _value(artefact.updated_at)))
    entries.sort(key=lambda item: item[0], reverse=True)
    if not entries:
        return '<p class="empty">No recent activity yet.</p>'
    rows = []
    for _, icon, title, detail in entries[:5]:
        rows.append(
            '<div class="workspace-activity-row">'
            f'<div class="workspace-activity-icon">{escape(icon)}</div>'
            f'<div><strong>{escape(title)}</strong><p class="muted">{escape(detail)}</p></div>'
            "</div>"
        )
    return '<div class="workspace-activity-list" data-ui-component="recent-activity">' + "".join(rows) + "</div>"


def _workspace_notes_section(job: Job, events: list[Communication], artefacts: list[Artefact]) -> str:
    event_count = len(events)
    body = f"""
    <div class="workspace-two-up" data-ui-component="notes-workbench">
      <div class="workspace-subpanel">
        <h3>Add note or follow-up</h3>
        {_note_form(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Recent activity</h3>
        {_recent_activity(job, events, artefacts)}
      </div>
    </div>
    <section class="workspace-subpanel">
      <details class="timeline-panel">
        <summary>Journal <span class="workspace-nav-count">{event_count}</span></summary>
        {_timeline(events)}
      </details>
    </section>
    {_provenance(job)}
    """
    return _workspace_section(section_id="notes", kicker="Notes", title="Notes", body=body)


def _workspace_ai_assessment(ai_outputs: list[AiOutput]) -> str:
    fit_output = _latest_ai_output(ai_outputs, "fit_summary")
    if fit_output is None:
        return """
        <section class="workspace-rail-panel" data-ui-component="ai-assessment">
          <div class="workspace-side-heading">Fit summary</div>
          <p class="muted">No current fit read yet. Generate one when you want a quick view of strengths, gaps, and watch-outs.</p>
        </section>
        """
    rendered = _render_ai_markdown(fit_output.body)
    return f"""
    <section class="workspace-rail-panel emphasis" data-ui-component="ai-assessment">
      <div class="workspace-side-heading">Fit summary</div>
      <div class="workspace-constrained-body ai-assessment-body" data-ui-component="ai-assessment-body">
        {rendered}
      </div>
    </section>
    """


def _workspace_ai_sidebar(job: Job, ai_outputs: list[AiOutput], artefact_lookup: dict[str, Artefact]) -> str:
    return f"""
    <aside class="workspace-right-rail" data-ui-component="ai-rail">
      <section class="workspace-rail-shell">
        <div class="workspace-rail-head">
          <span>AI Assistant</span>
          <span class="muted">Visible output</span>
        </div>
        <div class="workspace-rail-body">
          {_workspace_ai_assessment(ai_outputs)}
        </div>
      </section>
      <section class="workspace-side-card" data-ui-component="ai-help-list">
        <div class="workspace-side-heading">AI actions</div>
        <div class="workspace-help-list">
          <a class="workspace-help-item" href="/jobs/{escape(job.uuid, quote=True)}?section=documents"><strong>Tailor documents</strong><span>Open documents</span></a>
          <a class="workspace-help-item" href="/jobs/{escape(job.uuid, quote=True)}?section=interviews"><strong>Prepare interviews</strong><span>Open interviews</span></a>
          <a class="workspace-help-item" href="/jobs/{escape(job.uuid, quote=True)}?section=follow-ups"><strong>Draft follow-up notes</strong><span>Open follow-ups</span></a>
          <form class="workspace-help-action" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs">
            <input type="hidden" name="output_type" value="fit_summary">
            <button class="workspace-help-item workspace-help-button" type="submit"><strong>Analyse role fit</strong><span>Generate fit summary</span></button>
          </form>
        </div>
        <p class="muted">AI stays visible and does not change workflow state on its own.</p>
      </section>
    </aside>
    """




def _workspace_utility_strip(job: Job, artefacts: list[Artefact]) -> str:
    done, total = _workspace_readiness_score(job, artefacts)
    return f"""
    <section class="workspace-panel workspace-utility-strip" data-ui-component="utility-strip">
      <div class="workspace-utility-readiness">
        <span class="workspace-ai-pill">Ready {done}/{total}</span>
        <span class="muted">Key inputs in place for the next move.</span>
      </div>
      <div class="workspace-utility-actions">
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs">
          <input type="hidden" name="output_type" value="fit_summary">
          <button class="outline compact" type="submit">✦ Fit</button>
        </form>
        <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/ai-outputs">
          <input type="hidden" name="output_type" value="recommendation">
          <button class="outline compact" type="submit">✦ Next step</button>
        </form>
      </div>
    </section>
    """


def _next_action(job: Job) -> str:
    if job.status == "archived":
        title = "Restore or leave archived"
        body = "This job is off the active board. Restore it only if it needs work again."
        action = ""
    elif job.intake_state == "needs_review":
        title = "Review this opportunity"
        body = "Decide whether this intake belongs in active work before preparing an application."
        action = _compact_status_form(job, "interested", "Keep as interested")
    elif job.status == "saved":
        title = "Make the first decision"
        body = "This is still a prospect. Mark it interested when it is worth spending attention on."
        action = _compact_status_form(job, "interested", "Mark interested")
    elif job.status in {"interested", "preparing"}:
        title = "Prepare the application"
        body = "Check the description, source link, and artefacts before submitting externally."
        action = _button_link("Open apply link", job.apply_url or job.source_url, primary=True)
    elif job.status == "applied":
        title = "Track the response"
        body = "Record follow-ups, recruiter updates, and interview scheduling as they arrive."
        action = _compact_status_form(job, "interviewing", "Move to interviewing")
    elif job.status == "interviewing":
        title = "Prepare for the interview"
        body = "Keep interview notes, participants, and follow-up actions attached to this job."
        action = _compact_status_form(job, "offer", "Record offer", variant="outline")
    elif job.status == "offer":
        title = "Decide on the offer"
        body = "Record decision notes and archive when the outcome is complete."
        action = _compact_status_form(job, "archived", "Archive when complete", variant="outline")
    elif job.status == "rejected":
        title = "Capture the learning"
        body = "Add any useful rejection notes, then archive when this no longer needs attention."
        action = _compact_status_form(job, "archived", "Archive", variant="outline")
    else:
        title = "Choose the next action"
        body = "Use the workflow controls to move this job to the right state."
        action = ""
    return f"""
    <section class="workspace-panel next-action">
      <div>
        <p class="eyebrow">Next action</p>
        <h2>{escape(title)}</h2>
        <p>{escape(body)}</p>
      </div>
      <div class="next-action-controls">
        {action}
      </div>
    </section>
    """


def _readiness_item(label: str, ready: bool, detail: str) -> str:
    state = "done" if ready else "todo"
    return f"""
    <li class="readiness-item {state}">
      <span>{escape(label)}</span>
      <p>{escape(detail)}</p>
    </li>
    """


def _readiness(job: Job, artefacts: list[Artefact] | None = None) -> str:
    artefacts = artefacts if artefacts is not None else job.artefacts
    items = [
        _readiness_item(
            "Role captured",
            bool(job.title and job.description_raw),
            "Title and description are available." if job.description_raw else "Add or import the job description.",
        ),
        _readiness_item(
            "Application link",
            bool(job.apply_url or job.source_url),
            "External route is ready." if job.apply_url or job.source_url else "Add a source or apply URL.",
        ),
        _readiness_item(
            "Artefacts",
            bool(artefacts),
            "Reusable files are attached." if artefacts else "Upload a resume, cover letter, or prep file.",
        ),
        _readiness_item(
            "Application record",
            bool(job.applications),
            "Submission history exists." if job.applications else "Mark applied once submitted.",
        ),
    ]
    return f"""
    <section class="workspace-panel">
      <div class="section-heading">
        <p class="eyebrow">Readiness</p>
        <h2>Application readiness</h2>
      </div>
      <ol class="readiness-list">
        {"".join(items)}
      </ol>
    </section>
    """


def _external_links(job: Job) -> str:
    actions = "\n".join(
        action
        for action in [
            _button_link("Open apply link", job.apply_url, primary=True),
            _button_link("Open source", job.source_url),
        ]
        if action
    )
    if not actions:
        actions = '<p class="empty">No external links set yet.</p>'
    return f"""
    <section class="workspace-panel">
      <div class="section-heading">
        <p class="eyebrow">External workflow</p>
        <h2>Leave and return</h2>
      </div>
      <div class="action-stack">
        {actions}
      </div>
    </section>
    """


def _provenance(job: Job) -> str:
    data = job.structured_data or {}
    email_data = data.get("email_capture") if isinstance(data, dict) else None
    email = job.email_intake
    if not email and not email_data and not job.intake_source:
        return ""

    email_rows = ""
    if email:
        email_rows = f"""
        {_field("Email subject", email.subject)}
        {_field("Sender", email.sender)}
        {_field("Received", email.received_at)}
        {_field("Provider", email.source_provider)}
        """

    extracted_urls = ""
    if isinstance(email_data, dict):
        urls = email_data.get("extracted_urls") or []
        if urls:
            links = "\n".join(
                f'<li><a href="{escape(str(url), quote=True)}" target="_blank" rel="noreferrer">{escape(str(url))}</a></li>'
                for url in urls
            )
            extracted_urls = f"<h3>Extracted links</h3><ol class=\"provenance-links\">{links}</ol>"

    email_body = ""
    if email and email.body_text:
        email_body = f"<h3>Email body</h3><pre>{escape(email.body_text)}</pre>"

    return f"""
    <section class="workspace-panel">
      <details class="timeline-panel provenance-panel">
        <summary>Capture provenance</summary>
        <dl>
          {_field("Intake source", job.intake_source)}
          {_field("Intake confidence", job.intake_confidence)}
          {_field("Intake state", job.intake_state)}
          {email_rows}
        </dl>
        {extracted_urls}
        {email_body}
      </details>
    </section>
    """


def _clean_optional(value: str) -> str | None:
    cleaned = value.strip()
    return cleaned or None


def _parse_decimal(value: str, *, field_name: str) -> Decimal | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be a valid number",
        ) from exc


def _parse_follow_up_date(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Follow-up date must be a valid date",
        ) from exc
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _form_value(form: FormData, key: str) -> str | None:
    if key not in form:
        return None
    value = form[key]
    return str(value)


def _apply_job_form_update(
    job: Job,
    *,
    title: str | None,
    company: str | None,
    job_status: str | None,
    source: str | None,
    source_url: str | None,
    apply_url: str | None,
    location: str | None,
    remote_policy: str | None,
    salary_min: str | None,
    salary_max: str | None,
    salary_currency: str | None,
    description_raw: str | None,
) -> tuple[str, str]:
    old_status = job.status

    if title is not None:
        job_title = title.strip()
        if not job_title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job title is required")
        job.title = job_title
    if company is not None:
        job.company = _clean_optional(company)
    if job_status is not None:
        target_status = job_status.strip() or "saved"
        if target_status not in JOB_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported job status",
            )
        update_job_board_state(job, status=target_status)
    if source is not None:
        job.source = _clean_optional(source)
    if source_url is not None:
        job.source_url = _clean_optional(source_url)
    if apply_url is not None:
        job.apply_url = _clean_optional(apply_url)
    if location is not None:
        job.location = _clean_optional(location)
    if remote_policy is not None:
        job.remote_policy = _clean_optional(remote_policy)
    if salary_min is not None:
        job.salary_min = _parse_decimal(salary_min, field_name="Salary min")
    if salary_max is not None:
        job.salary_max = _parse_decimal(salary_max, field_name="Salary max")
    if salary_currency is not None:
        job.salary_currency = _clean_optional(salary_currency)
    if description_raw is not None:
        job.description_raw = _clean_optional(description_raw)
        job.description_clean = _clean_optional(description_raw)
    return old_status, job.status


def _next_board_position(db: DbSession, user: User, job_status: str) -> int:
    return (
        db.scalar(
            select(func.max(Job.board_position)).where(
                Job.owner_user_id == user.id,
                Job.status == job_status,
            )
        )
        or -1
    ) + 1


def render_new_job(user: User) -> str:
    extra_styles = """
    h1 { font-size: 1.6rem; font-weight: 500; line-height: 1.15; }
    .job-entry-panel {
      max-height: 100%;
      min-height: 0;
      overflow-y: auto;
    }
    .job-form { display: grid; gap: 14px; }
    .inline-fields {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    label { display: grid; font-weight: 500; gap: 6px; }
    input, select, textarea {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }
    textarea { resize: vertical; }
    button {
      background: var(--accent);
      border: 0.5px solid var(--accent-strong);
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      min-height: 34px;
      padding: 0 14px;
      transition: background 120ms ease-out;
    }
    button:hover { background: var(--accent-strong); }
    @media (max-width: 720px) {
      .inline-fields { display: grid; }
    }
    """
    return render_shell_page(
        user,
        page_title="Add Job",
        title="Add job",
        subtitle="",
        active=None,
        body=f'<section class="page-panel job-entry-panel">{_new_job_form()}</section>',
        container="workspace",
        extra_styles=extra_styles,
    )


def render_job_detail(
    job: Job,
    *,
    available_artefacts: list[Artefact] | None = None,
    ai_status: str | None = None,
    ai_error: str | None = None,
    ai_debug: str | None = None,
    active_section: str = "overview",
    selected_ai_artefact_uuid: str | None = None,
    selected_ai_tab: str | None = None,
    generation_brief_action: str | None = None,
    generation_brief_draft_kind: str | None = None,
    competency_evidence_items: list[CompetencyEvidence] | None = None,
) -> str:
    active_section = _normalize_workspace_section(active_section)
    events = sorted(
        job.communications,
        key=lambda event: event.occurred_at or event.created_at,
        reverse=True,
    )
    artefacts = linked_artefacts_for_job(job)
    available_artefacts = available_artefacts or []
    artefact_lookup = {artefact.uuid: artefact for artefact in artefacts}
    artefact_lookup.update({artefact.uuid: artefact for artefact in available_artefacts})
    ai_outputs = [
        output
        for output in sorted(job.ai_outputs, key=lambda item: item.updated_at, reverse=True)
        if output.status == "active"
    ]
    brief_action = _normalize_generation_brief_action(generation_brief_action)
    brief_draft_kind = _normalize_draft_kind(generation_brief_draft_kind)
    brief_artefact = artefact_lookup.get(selected_ai_artefact_uuid) if brief_action else None

    css_prefix = ""
    extra_styles = f"""
    {css_prefix}
    h1, h2, h3, p {{ margin: 0; }}
    a {{ color: var(--accent-strong); font-weight: 500; }}
    button {{
      background: var(--accent);
      border: 0.5px solid var(--accent-strong);
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      min-height: 34px;
      padding: 0 14px;
      transition: background 120ms ease-out;
    }}
    button:hover:not(:disabled) {{ background: var(--accent-strong); }}
    button.outline, .button-link {{
      background: #ffffff;
      border: 0.5px solid rgba(0,0,0,0.10);
      color: var(--ink);
      text-decoration: none;
    }}
    button.outline:hover, .button-link:hover {{ background: #f3f4f9; }}
    input, select, textarea {{
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }}
    textarea {{ resize: vertical; }}
    label {{ display: grid; font-weight: 500; gap: 6px; }}
    .note-form, .job-form, .quick-action-form {{ display: grid; gap: 12px; }}
    .inline-fields {{ display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .eyebrow {{
      color: var(--muted);
      font-size: 0.76rem;
      letter-spacing: 0.04em;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}
    .muted, .empty, time {{ color: var(--muted); }}
    .stage-pill {{
      border-radius: 999px;
      display: inline-flex;
      font-size: 0.73rem;
      font-weight: 500;
      line-height: 1;
      padding: 4px 8px;
    }}
    .stage-pill.inbox {{ background: var(--accent-soft); border: 0.5px solid #C3CCF0; color: var(--accent-strong); }}
    .stage-pill.active {{ background: var(--amber-soft); border: 0.5px solid #f9d9a0; color: #8c5000; }}
    .stage-pill.success {{ background: var(--success-soft); border: 0.5px solid #b6dfc5; color: var(--success); }}
    .stage-pill.closed {{ background: #f1f0ed; border: 0.5px solid #d8d8d4; color: #5f5e5a; }}
    .workspace-grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: 248px minmax(0, 1fr) 332px;
    }}
    .workspace-left-rail,
    .workspace-center,
    .workspace-right-rail {{
      display: grid;
      gap: 16px;
      align-content: start;
      min-width: 0;
      position: relative;
    }}
    .workspace-side-card,
    .workspace-surface,
    .workspace-rail-shell,
    .workspace-rail-panel,
    .workspace-progress-card,
    .workspace-next-up,
    .workspace-subpanel,
    .workspace-panel {{
      background: #ffffff;
      border: 0.5px solid rgba(0,0,0,0.09);
      border-radius: var(--radius-xl);
      box-shadow: none;
    }}
    .flash {{ margin-bottom: 18px; padding: 18px 20px; }}
    .flash-detail {{
      color: var(--text-muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.8rem;
      margin-top: 8px;
      overflow-wrap: anywhere;
    }}
    .flash-success {{
      background: var(--success-soft);
      border-color: #b6dfc5;
    }}
    .flash-error {{
      background: var(--danger-soft);
      border-color: #f8c4be;
    }}
    .workspace-side-card {{ padding: 16px; }}
    .workspace-quick-actions {{
      position: relative;
    }}
    .workspace-quick-trigger {{
      align-items: center;
      background: #ffffff;
      border: 0.5px solid rgba(0,0,0,0.09);
      border-radius: var(--radius-xl);
      color: var(--ink);
      cursor: pointer;
      display: flex;
      font-weight: 500;
      justify-content: space-between;
      list-style: none;
      min-height: 40px;
      padding: 0 16px;
    }}
    .workspace-quick-trigger::-webkit-details-marker {{ display: none; }}
    .workspace-quick-actions[open] .workspace-quick-trigger {{
      border-bottom-left-radius: 12px;
      border-bottom-right-radius: 12px;
    }}
    .workspace-quick-panel {{
      background: #ffffff;
      border: 0.5px solid rgba(0,0,0,0.09);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 10px;
      left: 0;
      margin-top: 8px;
      padding: 16px;
      position: absolute;
      right: 0;
      top: 100%;
      z-index: 8;
    }}
    .workspace-left-rail {{
      gap: 12px;
    }}
    .workspace-center {{
      z-index: 2;
    }}
    .workspace-back-link {{
      align-items: center;
      color: var(--muted);
      display: inline-flex;
      font-size: 0.85rem;
      font-weight: 400;
      gap: 6px;
      min-height: 26px;
      text-decoration: none;
    }}
    .workspace-back-link:hover {{ color: var(--ink); }}
    .workspace-anchor-nav {{
      display: grid;
      gap: 4px;
    }}
    .workspace-nav-link,
    .workspace-quick-link {{
      align-items: center;
      border-radius: 8px;
      color: var(--muted);
      display: flex;
      font-size: 0.88rem;
      justify-content: space-between;
      min-height: 34px;
      padding: 0 10px;
      text-decoration: none;
    }}
    .workspace-quick-link {{
      background: rgba(79, 103, 228, 0.03);
      border: 0.5px solid rgba(79, 103, 228, 0.10);
    }}
    .workspace-nav-link.active {{
      background: var(--accent-soft);
      border: 0.5px solid #C3CCF0;
      color: var(--accent-strong);
      font-weight: 500;
    }}
    .workspace-nav-count {{
      align-items: center;
      background: var(--accent-soft);
      border: 0.5px solid #C3CCF0;
      border-radius: 999px;
      color: var(--accent-strong);
      display: inline-flex;
      font-size: 0.7rem;
      font-weight: 500;
      height: 18px;
      justify-content: center;
      min-width: 18px;
      padding: 0 5px;
    }}
    .workspace-side-heading {{ font-size: 0.92rem; font-weight: 500; margin-bottom: 10px; }}
    .workspace-score-card {{
      align-items: center;
      display: grid;
      gap: 14px;
      grid-template-columns: 86px 1fr;
    }}
    .workspace-score-ring {{
      align-items: center;
      background: conic-gradient(var(--accent) calc(var(--score) * 1%), #ebe9f8 0);
      border-radius: 50%;
      display: inline-flex;
      height: 86px;
      justify-content: center;
      position: relative;
      width: 86px;
    }}
    .workspace-score-ring::before {{
      background: #ffffff;
      border-radius: 50%;
      content: "";
      inset: 11px;
      position: absolute;
    }}
    .workspace-score-ring span {{
      font-size: 1.2rem;
      font-weight: 500;
      position: relative;
      z-index: 1;
    }}
    .workspace-center-top {{
      display: grid;
      gap: 14px;
    }}
    .workspace-page-actions,
    .workspace-inline-actions,
    .workspace-split-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .button-link {{
      align-items: center;
      border-radius: 12px;
      display: inline-flex;
      justify-content: center;
      min-height: 38px;
      padding: 0 14px;
      text-decoration: none;
    }}
    .button-link.primary {{
      background: var(--accent);
      border: 0.5px solid var(--accent-strong);
      color: #ffffff;
    }}
    .button-link.primary:hover {{ background: var(--accent-strong); }}
    .workspace-surface {{
      display: grid;
      gap: 16px;
      padding: 18px 20px;
    }}
    .workspace-surface-head {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
    }}
    .workspace-surface-body {{
      display: grid;
      gap: 16px;
      min-width: 0;
    }}
    .workspace-identity-head {{
      align-items: start;
      display: flex;
      gap: 16px;
      justify-content: space-between;
    }}
    .workspace-identity-title {{
      font-size: 1.25rem;
      font-weight: 500;
      line-height: 1.15;
      margin: 0 0 6px;
      overflow-wrap: anywhere;
    }}
    .workspace-identity-status {{
      display: inline-flex;
      flex-shrink: 0;
    }}
    .workspace-progress-card {{ display: grid; gap: 14px; padding: 18px; }}
    .workspace-progress-head {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
    }}
    .workspace-inline-link {{
      border: 1px solid var(--line);
      border-radius: 12px;
      color: var(--ink);
      min-height: 36px;
      padding: 8px 12px;
      text-decoration: none;
    }}
    .workspace-progress-line {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(6, minmax(0, 1fr));
    }}
    .progress-step {{
      color: var(--muted);
      display: grid;
      gap: 8px;
      justify-items: center;
      position: relative;
      text-align: center;
    }}
    .progress-step::before {{
      background: #e5e7f2;
      content: "";
      height: 2px;
      left: -50%;
      position: absolute;
      right: 50%;
      top: 12px;
      z-index: 0;
    }}
    .progress-step:first-child::before {{ display: none; }}
    .progress-dot {{
      align-items: center;
      background: #ffffff;
      border: 2px solid #d8dcec;
      border-radius: 999px;
      display: inline-flex;
      font-size: 0.72rem;
      font-weight: 800;
      height: 24px;
      justify-content: center;
      position: relative;
      width: 24px;
      z-index: 1;
    }}
    .progress-step.done .progress-dot {{
      background: #1ea86f;
      border-color: #1ea86f;
      color: #ffffff;
    }}
    .progress-step.active .progress-dot {{
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }}
    .progress-step strong {{ display: block; font-size: 0.86rem; }}
    .progress-step span {{ font-size: 0.78rem; }}
    .workspace-next-up {{
      border-color: rgba(112, 87, 232, 0.2);
      display: grid;
      gap: 0;
      grid-template-columns: 240px 1fr;
      overflow: hidden;
    }}
    .workspace-next-left,
    .workspace-next-right {{ padding: 20px; }}
    .workspace-next-left {{ border-right: 1px solid rgba(112, 87, 232, 0.14); }}
    .workspace-next-title {{ font-size: 1rem; font-weight: 500; margin-bottom: 6px; }}
    .workspace-checklist {{ display: grid; gap: 10px; margin-top: 14px; }}
    .workspace-check {{
      align-items: start;
      color: var(--text-muted);
      display: grid;
      gap: 10px;
      grid-template-columns: 20px 1fr;
    }}
    .workspace-check-mark {{
      border: 2px solid #d7daea;
      border-radius: 999px;
      display: inline-flex;
      font-size: 0.72rem;
      height: 18px;
      justify-content: center;
      width: 18px;
      align-items: center;
    }}
    .workspace-check.done .workspace-check-mark {{
      background: #1ea86f;
      border-color: #1ea86f;
      color: #ffffff;
    }}
    .workspace-two-up,
    .workspace-three-up {{
      display: grid;
      gap: 16px;
    }}
    .workspace-two-up {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .workspace-two-up[data-ui-component="documents-workbench"] {{
      align-items: start;
    }}
    .workspace-three-up {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .workspace-subpanel {{
      display: grid;
      gap: 14px;
      min-width: 0;
      padding: 18px;
    }}
    .workspace-subpanel h3 {{ font-size: 1rem; }}
    .workspace-detail-copy {{ display: grid; gap: 14px; }}
    .workspace-constrained-panel {{
      min-width: 0;
    }}
    .workspace-constrained-body {{
      max-height: 260px;
      min-width: 0;
      overflow: auto;
      padding-right: 4px;
    }}
    .job-description-body {{
      border-top: 1px solid #f0f1f6;
      margin-top: 8px;
      padding-top: 12px;
    }}
    .workspace-chip-row, .artefact-actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .workspace-chip {{
      align-items: center;
      background: var(--accent-soft);
      border: 0.5px solid #C3CCF0;
      border-radius: 8px;
      color: var(--accent-strong);
      display: inline-flex;
      font-size: 0.76rem;
      font-weight: 500;
      min-height: 24px;
      padding: 0 8px;
    }}
    .workspace-add-chip {{
      align-items: center;
      border: 1px dashed var(--line-strong);
      border-radius: 10px;
      color: var(--text-soft);
      display: inline-flex;
      font-size: 0.78rem;
      font-weight: 700;
      min-height: 28px;
      padding: 0 10px;
    }}
    .workspace-inline-ai {{
      align-items: center;
      background: #fbfaff;
      border: 1px solid #e1dcff;
      border-radius: 12px;
      color: var(--text-muted);
      display: flex;
      gap: 10px;
      min-height: 42px;
      padding: 0 12px;
    }}
    .workspace-utility-strip {{
      align-items: center;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      padding: 14px 16px;
    }}
    .workspace-utility-readiness,
    .workspace-utility-actions {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    button.compact {{
      min-height: 28px;
      padding: 0 10px;
      font-size: 0.85rem;
    }}
    .workspace-ai-pill {{
      align-items: center;
      background: var(--accent-soft);
      border: 0.5px solid #C3CCF0;
      border-radius: 999px;
      color: var(--accent-strong);
      display: inline-flex;
      font-size: 0.73rem;
      font-weight: 500;
      min-height: 22px;
      padding: 0 7px;
    }}
    .overview-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin: 0;
    }}
    dl {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 0;
    }}
    .field {{ min-width: 0; }}
    dt {{
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 500;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    .editable {{
      border: 1px solid transparent;
      border-radius: 10px;
      cursor: text;
      margin: -5px;
      padding: 5px;
    }}
    .editable:hover, .editable:focus {{ border-color: var(--line); outline: 0; }}
    .editable.is-editing {{ background: #ffffff; border-color: var(--accent); cursor: default; }}
    .editable-control {{ display: none; }}
    .editable.is-editing > .editable-control,
    .editable.is-editing .editable-control {{ display: block; }}
    .editable.is-editing > .editable-display,
    .editable.is-editing .editable-display {{ display: none; }}
    .editable-heading .editable-control {{
      font-size: 1.9rem;
      font-weight: 700;
      line-height: 1.05;
    }}
    pre {{
      font-family: inherit;
      line-height: 1.5;
      margin: 0;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}
    .description-editor {{ min-height: 420px; }}
    .savebar {{
      align-items: center;
      background: rgba(22, 30, 50, 0.94);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-lg);
      bottom: 18px;
      color: #ffffff;
      display: none;
      gap: 10px;
      left: 50%;
      padding: 8px 12px;
      position: fixed;
      transform: translateX(-50%);
      z-index: 20;
    }}
    .savebar.is-visible {{ display: flex; }}
    .savebar p {{ font-size: 0.9rem; font-weight: 500; }}
    .savebar button {{ background: rgba(255,255,255,0.15); border: 0.5px solid rgba(255,255,255,0.30); }}
    .savebar button:hover {{ background: rgba(255,255,255,0.25); }}
    .savebar .secondary {{ background: transparent; border: 0.5px solid rgba(255,255,255,0.22); }}
    .readiness-list {{ display: grid; gap: 0; }}
    .readiness-item {{
      border-left: 0;
      border-top: 1px solid var(--line);
      display: grid;
      gap: 3px;
      padding: 12px 0 12px 26px;
      position: relative;
    }}
    .readiness-item:first-child {{ border-top: 0; }}
    .readiness-item::before {{
      border: 0.5px solid var(--line);
      border-radius: 999px;
      content: "";
      height: 12px;
      left: 0;
      position: absolute;
      top: 16px;
      width: 12px;
    }}
    .readiness-item.done::before {{ background: #2a8a58; border-color: #2a8a58; }}
    .readiness-item span {{ font-weight: 500; }}
    .readiness-item p {{ color: var(--muted); }}
    .next-action {{
      align-items: start;
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1fr) auto;
    }}
    .next-action-controls {{
      align-items: center;
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }}
    .inline-action-form {{ margin: 0; }}
    .action-stack {{ display: grid; gap: 8px; }}
    .timeline-panel summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-weight: 500;
    }}
    .workspace-activity-list {{ display: grid; gap: 12px; }}
    .workspace-activity-row {{
      align-items: center;
      border-top: 1px solid #f0f1f6;
      display: grid;
      gap: 12px;
      grid-template-columns: 36px 1fr;
      padding: 8px 0;
    }}
    .workspace-activity-row:first-child {{ border-top: 0; }}
    .workspace-activity-icon {{
      align-items: center;
      background: rgba(112, 87, 232, 0.1);
      border-radius: 999px;
      color: var(--accent);
      display: inline-flex;
      font-weight: 800;
      height: 36px;
      justify-content: center;
      width: 36px;
    }}
    .provenance-panel dl {{ margin-top: 14px; }}
    .provenance-panel h3 {{ font-size: 0.95rem; margin: 18px 0 8px; }}
    .provenance-links li {{ border-left: 0; padding-left: 0; overflow-wrap: anywhere; }}
    .workspace-rail-shell {{ overflow: hidden; padding: 0; }}
    .workspace-rail-head {{
      align-items: center;
      border-bottom: 0.5px solid rgba(0,0,0,0.09);
      display: flex;
      gap: 12px;
      justify-content: space-between;
      padding: 14px 16px;
      font-weight: 500;
    }}
    .workspace-rail-body {{ display: grid; gap: 12px; padding: 12px; }}
    .workspace-rail-panel {{ display: grid; gap: 12px; padding: 16px; }}
    .workspace-rail-panel.emphasis {{
      background: linear-gradient(180deg, rgba(246,242,255,0.98), rgba(251,249,255,0.98));
      border-color: rgba(112, 87, 232, 0.18);
    }}
    .ai-assessment-body {{
      max-height: 320px;
    }}
    .workspace-help-list {{ display: grid; gap: 12px; }}
    .workspace-help-action {{ margin: 0; }}
    .workspace-help-item {{
      align-items: center;
      border-top: 1px solid #f0f1f6;
      color: var(--text-muted);
      display: flex;
      font-size: 0.9rem;
      gap: 12px;
      justify-content: space-between;
      text-decoration: none;
      padding: 14px 0;
    }}
    .workspace-help-item:first-child {{ border-top: 0; }}
    .workspace-help-item strong {{ color: var(--accent-strong); }}
    .workspace-help-item span {{ color: var(--muted); font-size: 0.82rem; }}
    .workspace-help-button {{
      background: transparent;
      border: 0;
      border-top: 1px solid #f0f1f6;
      cursor: pointer;
      padding-left: 0;
      padding-right: 0;
      text-align: left;
      width: 100%;
    }}
    .workspace-artefact-list {{
      border: 1px solid var(--line);
      border-radius: 16px;
      display: grid;
      overflow: visible;
      position: relative;
    }}
    .workspace-artefact-item {{
      align-items: start;
      background: #ffffff;
      border-top: 1px solid #f0f1f6;
      display: grid;
      gap: 12px;
      grid-template-columns: 1fr;
      padding: 14px 16px;
      position: relative;
    }}
    .workspace-artefact-item:first-child {{ border-top: 0; }}
    .workspace-artefact-item:first-child {{
      border-top-left-radius: 16px;
      border-top-right-radius: 16px;
    }}
    .workspace-artefact-item:last-child {{
      border-bottom-left-radius: 16px;
      border-bottom-right-radius: 16px;
    }}
    .workspace-artefact-left {{
      align-items: center;
      display: grid;
      gap: 12px;
      grid-template-columns: 32px 1fr;
      min-width: 0;
    }}
    .workspace-doc-icon {{
      align-items: center;
      background: #f2f4fb;
      border-radius: 10px;
      color: var(--accent);
      display: inline-flex;
      font-weight: 800;
      height: 32px;
      justify-content: center;
      width: 32px;
    }}
    .workspace-artefact-name {{ font-size: 0.9rem; font-weight: 500; margin-bottom: 3px; overflow-wrap: anywhere; }}
    @media (min-width: 761px) {{
      .workspace-artefact-name {{
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
    }}
    .meta-row {{
      color: var(--text-muted);
      display: flex;
      flex-wrap: wrap;
      font-size: 0.82rem;
      gap: 8px;
    }}
    .mini-pill {{
      align-items: center;
      background: #eaf8f1;
      border-radius: 999px;
      color: var(--green);
      display: inline-flex;
      font-size: 0.7rem;
      font-weight: 700;
      min-height: 22px;
      padding: 0 8px;
    }}
    .workspace-artefact-actions {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-start;
      min-width: 0;
      padding-left: 44px;
    }}
    .action-btn {{
      align-items: center;
      background: #ffffff;
      border: 0.5px solid rgba(0,0,0,0.10);
      border-radius: 8px;
      color: var(--ink);
      display: inline-flex;
      font-weight: 500;
      font-size: 0.85rem;
      gap: 6px;
      min-height: 30px;
      padding: 0 10px;
      text-decoration: none;
    }}
    .action-btn.ai {{
      background: var(--accent-soft);
      border-color: #C3CCF0;
      color: var(--accent-strong);
    }}
    .workspace-ai-menu {{
      position: relative;
    }}
    .workspace-ai-menu[open] {{
      z-index: 50;
    }}
    .workspace-ai-menu > summary {{
      list-style: none;
      cursor: pointer;
    }}
    .workspace-ai-menu > summary::-webkit-details-marker {{ display: none; }}
    .workspace-ai-menu-body {{
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 8px;
      padding: 10px;
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      width: 240px;
      z-index: 60;
    }}
    .menu-link {{
      align-items: center;
      border-radius: 10px;
      display: flex;
      justify-content: flex-start;
      min-height: 38px;
      padding: 0 12px;
    }}
    .workspace-local-ai {{
      background: linear-gradient(180deg, #fcfbff, #faf8ff);
      border: 1px solid #ded8ff;
      border-radius: 16px;
      overflow: hidden;
    }}
    .workspace-local-ai-head {{
      align-items: center;
      border-bottom: 1px solid #e7e2ff;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      padding: 14px 16px;
    }}
    .workspace-local-ai-title {{
      color: var(--accent-strong);
      font-weight: 500;
    }}
    .generated-ok {{
      color: var(--green);
      font-size: 0.82rem;
      font-weight: 700;
    }}
    .workspace-local-ai-tabs {{
      background: rgba(255,255,255,0.35);
      border-bottom: 1px solid #ece7ff;
      display: flex;
      gap: 18px;
      padding: 0 16px;
    }}
    .workspace-local-ai-tab {{
      color: var(--text-muted);
      display: inline-flex;
      font-size: 0.82rem;
      font-weight: 700;
      padding: 14px 0 12px;
      position: relative;
      text-decoration: none;
    }}
    .workspace-local-ai-tab.unavailable {{
      opacity: 0.45;
    }}
    .workspace-local-ai-tab.active {{
      color: var(--accent-strong);
    }}
    .workspace-local-ai-tab.active::after {{
      background: var(--accent);
      border-radius: 999px;
      bottom: -1px;
      content: "";
      height: 2px;
      left: 0;
      position: absolute;
      right: 0;
    }}
    .workspace-local-ai-body {{
      align-items: start;
      display: grid;
      gap: 16px;
      grid-template-columns: 1fr;
      padding: 16px;
    }}
    .workspace-local-ai-body.inactive {{
      grid-template-columns: 1fr;
    }}
    .workspace-ai-side {{
      display: grid;
      gap: 10px;
    }}
    .workspace-ai-generate-box,
    .workspace-ai-results {{
      background: #ffffff;
      border: 1px solid #ece7ff;
      border-radius: 14px;
      display: grid;
      gap: 10px;
      padding: 14px;
    }}
    .workspace-ai-results {{
      max-height: 360px;
      overflow: auto;
    }}
    .workspace-ai-generate-title,
    .workspace-ai-results-title {{
      font-weight: 800;
    }}
    .workspace-ai-metadata {{
      border-top: 1px solid #ece7ff;
      padding-top: 10px;
    }}
    .workspace-ai-metadata > summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-size: 0.88rem;
      font-weight: 700;
    }}
    .workspace-ai-metadata-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 10px 0 0;
    }}
    .workspace-ai-metadata-grid dt {{
      color: var(--muted);
      font-size: 0.74rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .workspace-ai-metadata-grid dd {{
      margin: 4px 0 0;
      overflow-wrap: anywhere;
    }}
    .workspace-local-ai-foot {{
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      padding: 0 16px 16px;
    }}
    .workspace-modal-backdrop {{
      align-items: center;
      background: rgba(17, 24, 39, 0.38);
      display: flex;
      inset: 0;
      justify-content: center;
      padding: 20px;
      position: fixed;
      z-index: 80;
    }}
    .workspace-modal-card {{
      background: #fff;
      border: 0.5px solid var(--line);
      border-radius: 12px;
      box-shadow: 0 20px 48px rgba(15, 23, 42, 0.24);
      display: grid;
      gap: 16px;
      max-width: 760px;
      padding: 18px;
      width: min(100%, 760px);
    }}
    .workspace-modal-head {{
      align-items: flex-start;
      display: flex;
      gap: 12px;
      justify-content: space-between;
    }}
    .workspace-modal-title {{
      font-size: 1rem;
      font-weight: 500;
    }}
    .workspace-brief-form {{
      display: grid;
      gap: 12px;
    }}
    .brief-inline-fields {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .workspace-modal-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }}
    .competency-selector {{
      border: 0.5px solid var(--line);
      border-radius: 8px;
      padding: 10px;
    }}
    .competency-selector > summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-weight: 600;
    }}
    .competency-selector-list {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
      max-height: 220px;
      overflow: auto;
    }}
    .competency-selector-row {{
      align-items: flex-start;
      border: 0.5px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 8px;
      grid-template-columns: auto minmax(0, 1fr);
      padding: 8px;
    }}
    .competency-selector-row span,
    .competency-selector-row small {{
      color: var(--muted);
      display: block;
      overflow-wrap: anywhere;
    }}
    .competency-selector-row strong {{
      color: var(--ink);
      display: block;
    }}
    .workspace-support-tools details > summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-weight: 700;
      margin-bottom: 12px;
    }}
    .ai-output-list {{ display: grid; gap: 12px; }}
    .ai-output-card {{
      background: linear-gradient(180deg, rgba(232,239,255,0.96), rgba(244,247,255,0.98));
      border: 1px solid var(--ai-line);
      border-radius: var(--radius-lg);
      display: grid;
      gap: 10px;
      padding: 16px;
    }}
    .ai-output-links {{
      border-top: 1px solid var(--line-soft);
      display: grid;
      gap: 8px;
      margin-top: 4px;
      padding-top: 10px;
    }}
    .ai-output-links ul, ol {{
      display: grid;
      gap: 12px;
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    li {{ border-left: 4px solid var(--accent); padding-left: 12px; }}
    li strong {{ display: block; margin: 4px 0; }}
    .ai-markdown, .description-markdown {{
      display: grid;
      gap: 10px;
    }}
    .ai-markdown h2, .ai-markdown h3, .ai-markdown h4,
    .ai-markdown p,
    .description-markdown h2, .description-markdown h3, .description-markdown h4,
    .description-markdown p {{ margin: 0; }}
    .ai-markdown ul, .description-markdown ul {{
      display: grid;
      gap: 8px;
      list-style: disc;
      margin: 0;
      padding-left: 22px;
    }}
    .ai-markdown li, .description-markdown li {{
      border-left: 0;
      padding-left: 0;
    }}
    .timeline-panel ol {{ margin-top: 12px; }}
    .app-state-bar {{
      align-items: start;
      background: rgba(247,249,252,0.72);
      border: 0.5px solid var(--line);
      border-radius: var(--radius-lg);
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: space-between;
      padding: 14px 16px;
    }}
    .app-state-context {{
      align-items: flex-start;
      display: flex;
      flex: 1;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .app-state-title {{
      display: block;
      font-size: 0.93rem;
      font-weight: 500;
      margin-bottom: 2px;
    }}
    .app-state-bar .muted {{ margin: 0; font-size: 0.84rem; }}
    .app-state-cta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .interview-card-list,
    .follow-up-card-list {{
      display: grid;
      gap: 8px;
    }}
    .interview-card,
    .follow-up-card {{
      background: rgba(247,249,252,0.72);
      border: 0.5px solid var(--line);
      border-radius: var(--radius-md);
      display: grid;
      gap: 4px;
      padding: 12px 14px;
    }}
    .follow-up-card.overdue {{
      background: var(--amber-soft);
      border-color: #f9d9a0;
    }}
    .interview-card-head,
    .follow-up-card-head {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}
    .interview-card p,
    .follow-up-card p {{ font-size: 0.84rem; margin: 0; }}
    .workspace-form-disclosure {{
      border: 0.5px solid var(--line);
      border-radius: var(--radius-md);
      overflow: hidden;
    }}
    .workspace-form-disclosure > summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-size: 0.88rem;
      font-weight: 500;
      list-style: none;
      padding: 10px 14px;
    }}
    .workspace-form-disclosure > summary::-webkit-details-marker {{ display: none; }}
    .workspace-form-disclosure[open] > summary {{
      border-bottom: 0.5px solid var(--line);
    }}
    .workspace-form-disclosure .note-form,
    .workspace-form-disclosure .quick-action-form,
    .workspace-form-disclosure .job-form {{
      padding: 14px;
    }}
    .workspace-inline-link {{
      color: var(--accent-strong);
      font-size: 0.88rem;
      font-weight: 500;
      text-decoration: none;
    }}
    .workspace-inline-link:hover {{ text-decoration: underline; }}
    @media (max-width: 1360px) {{
      .workspace-grid {{ grid-template-columns: 220px minmax(0, 1fr) 300px; }}
    }}
    @media (min-width: 1081px) {{
      .page-main.standard {{
        overflow: hidden;
      }}
      .workspace-grid {{
        align-items: stretch;
        height: 100%;
        min-height: 0;
      }}
      .workspace-left-rail,
      .workspace-center,
      .workspace-right-rail {{
        max-height: 100%;
        min-height: 0;
        overflow: auto;
        overscroll-behavior: contain;
        scrollbar-gutter: stable;
      }}
      .workspace-center {{
        padding-right: 4px;
      }}
    }}
    @media (max-width: 1080px) {{
      .workspace-grid {{ grid-template-columns: 1fr; }}
      .workspace-left-rail {{ order: 2; }}
      .workspace-center {{ order: 1; }}
      .workspace-right-rail {{ order: 3; }}
      .workspace-info-grid, .workspace-two-up, .workspace-three-up, .overview-grid, .workspace-local-ai-body {{
        grid-template-columns: 1fr 1fr;
      }}
    }}
    @media (max-width: 760px) {{
      .inline-fields,
      .workspace-info-grid,
      .workspace-two-up,
      .workspace-three-up,
      .overview-grid,
      dl,
      .workspace-progress-line,
      .workspace-next-up,
      .next-action {{
        grid-template-columns: 1fr;
      }}
      .workspace-progress-line {{ row-gap: 18px; }}
      .workspace-next-left {{ border-right: 0; border-bottom: 1px solid rgba(112, 87, 232, 0.14); }}
      .workspace-page-head,
      .workspace-surface-head,
      .workspace-progress-head {{
        align-items: start;
        flex-direction: column;
      }}
      .workspace-identity-head,
      .workspace-utility-strip {{
        align-items: start;
        flex-direction: column;
      }}
      .workspace-page-actions,
      .workspace-inline-actions,
      .workspace-split-actions,
      .next-action-controls {{
        width: 100%;
      }}
      .workspace-page-actions > *,
      .workspace-inline-actions > *,
      .workspace-split-actions > *,
      .next-action-controls > *,
      .button-link {{
        width: 100%;
      }}
      .editable-heading .editable-control {{ font-size: 1.5rem; }}
      .description-editor {{ min-height: 280px; }}
      .workspace-constrained-body,
      .ai-assessment-body {{
        max-height: 220px;
      }}
      .workspace-artefact-item,
      .workspace-local-ai-body {{
        grid-template-columns: 1fr;
      }}
      .workspace-artefact-actions {{
        padding-left: 0;
        width: 100%;
      }}
      .workspace-artefact-actions > * {{
        flex: 1 1 140px;
      }}
      .workspace-ai-menu-body {{
        position: static;
        width: 100%;
      }}
      .workspace-modal-backdrop {{
        align-items: stretch;
        padding: 10px;
      }}
      .brief-inline-fields {{
        grid-template-columns: 1fr;
      }}
      .workspace-quick-panel {{
        position: static;
      }}
      .savebar {{
        bottom: 12px;
        display: none;
        gap: 8px;
        left: 12px;
        right: 12px;
        transform: none;
      }}
      .savebar.is-visible {{ display: grid; }}
      .savebar button {{ width: 100%; }}
    }}
    """
    section_map = {
        "overview": _workspace_overview_section(job, ai_outputs),
        "application": _workspace_application_section(job),
        "interviews": _workspace_interviews_section(job),
        "follow-ups": _workspace_follow_ups_section(job),
        "tasks": _workspace_tasks_section(job, artefacts),
        "notes": _workspace_notes_section(job, events, artefacts),
        "documents": _workspace_artefacts_section(
            job,
            artefacts,
            available_artefacts,
            ai_outputs,
            artefact_lookup,
            selected_artefact_uuid=selected_ai_artefact_uuid,
            selected_ai_tab=_normalize_local_ai_tab(selected_ai_tab),
        ),
    }
    body = f"""
    {(_flash_message(ai_status, tone="success") if ai_status else "")}
    {(_flash_message(ai_error, tone="error", detail=ai_debug) if ai_error else "")}
    <div class="workspace-grid" data-ui="job-workspace" data-ui-active-section="{escape(active_section, quote=True)}">
      <aside class="workspace-left-rail" data-ui-component="left-rail">
        {_workspace_back_link_card()}
        {_workspace_anchor_nav(job, artefacts, events, active_section)}
        {_workspace_score_card(job, artefacts)}
        {_workspace_quick_actions(job)}
      </aside>
      <section class="workspace-center" data-ui-component="main-column">
        <div class="workspace-center-top" data-ui-component="workspace-frame">
          {_workspace_identity_header(job)}
          {_workspace_utility_strip(job, artefacts)}
        </div>
        {section_map[active_section]}
      </section>
      {_workspace_ai_sidebar(job, ai_outputs, artefact_lookup)}
    </div>
    <div id="edit-savebar" class="savebar" aria-live="polite">
      <p>Unsaved changes</p>
      <button id="save-inline-edits" type="button">Save</button>
      <button id="cancel-inline-edits" class="secondary" type="button">Cancel</button>
    </div>
    {_generation_brief_modal(
        job,
        brief_artefact,
        action=brief_action,
        draft_kind=brief_draft_kind,
        competency_evidence_items=competency_evidence_items,
    )}
    """
    scripts = f"""
  <script>
    try {{
      var _jt = JSON.parse(sessionStorage.getItem('at-recents') || '[]');
      var _ju = {json.dumps(job.uuid)};
      _jt = _jt.filter(function(j) {{ return j.u !== _ju; }});
      _jt.unshift({{ u: _ju, t: {json.dumps(job.title)}, h: {json.dumps('/jobs/' + job.uuid)} }});
      if (_jt.length > 5) _jt.length = 5;
      sessionStorage.setItem('at-recents', JSON.stringify(_jt));
    }} catch(e) {{}}
  </script>
  <script>
    (() => {{
      const jobUuid = "{escape(job.uuid, quote=True)}";
      const dirty = new Map();
      const savebar = document.getElementById("edit-savebar");
      const saveButton = document.getElementById("save-inline-edits");
      const cancelButton = document.getElementById("cancel-inline-edits");

      function controlFor(editor) {{
        return editor.querySelector(".editable-control");
      }}

      function displayFor(editor) {{
        return editor.querySelector(".editable-display");
      }}

      function showSavebar() {{
        savebar.classList.toggle("is-visible", dirty.size > 0);
      }}

      function activate(editor) {{
        editor.classList.add("is-editing");
        const control = controlFor(editor);
        if (!control) {{
          return;
        }}
        control.focus();
        if (typeof control.select === "function") {{
          control.select();
        }}
      }}

      function markDirty(editor) {{
        const control = controlFor(editor);
        if (!control) {{
          return;
        }}
        const field = editor.dataset.field;
        const original = editor.dataset.original || "";
        const value = control.value;
        if (value === original) {{
          dirty.delete(field);
        }} else {{
          dirty.set(field, {{ editor, value }});
        }}
        showSavebar();
      }}

      function updateDisplay(editor) {{
        const control = controlFor(editor);
        const display = displayFor(editor);
        if (!control || !display) {{
          return;
        }}
        const value = control.value.trim();
        display.textContent = value || "Not set";
      }}

      function normalize(field, value) {{
        if (field === "title" || field === "status") {{
          return value;
        }}
        return value.trim() === "" ? null : value;
      }}

      document.querySelectorAll(".local-time").forEach((element) => {{
        const parsed = new Date(element.dateTime);
        if (Number.isNaN(parsed.getTime())) {{
          return;
        }}
        element.textContent = new Intl.DateTimeFormat(undefined, {{
          dateStyle: "medium",
          timeStyle: "short",
        }}).format(parsed);
        element.title = `${{element.dateTime}} UTC`;
      }});

      document.querySelectorAll(".editable").forEach((editor) => {{
        editor.addEventListener("dblclick", (event) => {{
          event.preventDefault();
          activate(editor);
        }});
        editor.addEventListener("keydown", (event) => {{
          if (event.key === "Enter" && editor.dataset.kind !== "textarea") {{
            event.preventDefault();
            editor.classList.remove("is-editing");
            updateDisplay(editor);
          }}
          if (event.key === "Escape") {{
            window.location.reload();
          }}
        }});
        const control = controlFor(editor);
        if (control) {{
          control.addEventListener("input", () => markDirty(editor));
          control.addEventListener("change", () => {{
            markDirty(editor);
            updateDisplay(editor);
          }});
          control.addEventListener("blur", () => updateDisplay(editor));
        }}
      }});

      saveButton.addEventListener("click", async () => {{
        const payload = {{}};
        dirty.forEach((entry, field) => {{
          payload[field] = normalize(field, entry.value);
        }});
        saveButton.disabled = true;
        try {{
          const response = await fetch(`/api/jobs/${{jobUuid}}`, {{
            method: "PATCH",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload),
          }});
          if (!response.ok) {{
            const error = await response.json().catch(() => ({{ detail: "Unable to save changes" }}));
            throw new Error(error.detail || "Unable to save changes");
          }}
          window.location.reload();
        }} catch (error) {{
          alert(error.message);
          saveButton.disabled = false;
        }}
      }});

      cancelButton.addEventListener("click", () => window.location.reload());
    }})();
  </script>
"""
    return render_shell_page(
        job.owner,
        page_title=job.title,
        title="Job Workspace",
        subtitle=job.title,
        active=None,
        actions=(("Add job", "/jobs/new", "add-job"),),
        body=body,
        kicker="Execution surface",
        goal=None,
        container="standard",
        extra_styles=extra_styles,
        scripts=scripts,
        show_hero=False,
    )


def _job_detail_redirect(
    job_uuid: str,
    *,
    section: str | None = None,
    ai_status: str | None = None,
    ai_error: str | None = None,
    ai_debug: str | None = None,
    ai_artefact: str | None = None,
    ai_tab: str | None = None,
) -> str:
    params = []
    normalized_section = _normalize_workspace_section(section)
    if normalized_section != "overview":
        params.append(f"section={quote(normalized_section)}")
    if ai_status:
        params.append(f"ai_status={quote(ai_status)}")
    if ai_error:
        params.append(f"ai_error={quote(ai_error)}")
    if ai_debug:
        params.append(f"ai_debug={quote(ai_debug)}")
    if ai_artefact:
        params.append(f"ai_artefact={quote(ai_artefact)}")
    normalized_tab = _normalize_local_ai_tab(ai_tab)
    if normalized_tab:
        params.append(f"ai_tab={quote(normalized_tab)}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return f"/jobs/{job_uuid}{suffix}"


def _submitted_generation_brief(
    *,
    skip_brief: str = "",
    focus_areas: str = "",
    must_include: str = "",
    avoid: str = "",
    tone: str = "",
    extra_context: str = "",
) -> dict[str, str] | None:
    if (skip_brief or "").strip():
        return None
    cleaned = {
        "focus_areas": focus_areas.strip(),
        "must_include": must_include.strip(),
        "avoid": avoid.strip(),
        "tone": tone.strip(),
        "extra_context": extra_context.strip(),
    }
    return {key: value for key, value in cleaned.items() if value} or None


def _generation_brief_notes(source_context: dict[str, object]) -> str:
    brief = source_context.get("generation_brief")
    if not isinstance(brief, dict):
        return ""
    labels = {
        "focus_areas": "Focus areas",
        "must_include": "Must include",
        "avoid": "Avoid or de-emphasise",
        "tone": "Tone or positioning",
        "extra_context": "Extra context",
    }
    parts = []
    for key in ("focus_areas", "must_include", "avoid", "tone", "extra_context"):
        value = brief.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{labels[key]}={value.strip()}")
    if not parts:
        return ""
    return " Generation brief: " + " | ".join(parts) + "."


@router.get("/jobs/new", response_class=HTMLResponse)
def new_job(
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return HTMLResponse(render_new_job(current_user))


@router.post("/jobs/new", include_in_schema=False)
def create_job_form(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    title: Annotated[str, Form()] = "",
    company: Annotated[str, Form()] = "",
    job_status: Annotated[str, Form()] = "saved",
    source_url: Annotated[str, Form()] = "",
    apply_url: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    remote_policy: Annotated[str, Form()] = "",
    salary_min: Annotated[str, Form()] = "",
    salary_max: Annotated[str, Form()] = "",
    salary_currency: Annotated[str, Form()] = "",
    description_raw: Annotated[str, Form()] = "",
    initial_note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    job_title = title.strip()
    if not job_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job title is required")

    target_status = job_status.strip() or "saved"
    if target_status not in BOARD_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New job status must be an active board status",
        )

    job = Job(
        owner_user_id=current_user.id,
        title=job_title,
        company=_clean_optional(company),
        status=target_status,
        board_position=_next_board_position(db, current_user, target_status),
        source="manual",
        intake_source="manual",
        intake_confidence="high",
        intake_state="accepted",
        source_url=_clean_optional(source_url),
        apply_url=_clean_optional(apply_url),
        location=_clean_optional(location),
        remote_policy=_clean_optional(remote_policy),
        salary_min=_parse_decimal(salary_min, field_name="Salary min"),
        salary_max=_parse_decimal(salary_max, field_name="Salary max"),
        salary_currency=_clean_optional(salary_currency),
        description_raw=_clean_optional(description_raw),
        description_clean=_clean_optional(description_raw),
    )
    db.add(job)
    db.flush()
    if initial_note.strip():
        create_job_note(db, job, subject="Created manually", notes=initial_note.strip())
    db.commit()
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs/{job_uuid}", response_class=HTMLResponse)
def job_detail(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    ai_status: Annotated[str | None, Query()] = None,
    ai_error: Annotated[str | None, Query()] = None,
    ai_debug: Annotated[str | None, Query()] = None,
    ai_artefact: Annotated[str | None, Query()] = None,
    ai_tab: Annotated[str | None, Query()] = None,
    brief_action: Annotated[str | None, Query()] = None,
    brief_draft_kind: Annotated[str | None, Query()] = None,
    section: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    return HTMLResponse(
        render_job_detail(
            job,
            available_artefacts=list_user_unlinked_artefacts_for_job(db, current_user, job),
            ai_status=ai_status,
            ai_error=ai_error,
            ai_debug=ai_debug,
            active_section=section or "overview",
            selected_ai_artefact_uuid=ai_artefact,
            selected_ai_tab=ai_tab,
            generation_brief_action=brief_action,
            generation_brief_draft_kind=brief_draft_kind,
            competency_evidence_items=list_competency_evidence(db, current_user),
        )
    )


@router.post("/jobs/{job_uuid}/edit", include_in_schema=False)
async def edit_job_form(
    job_uuid: str,
    request: Request,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    form = await request.form()
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status, new_status = _apply_job_form_update(
        job,
        title=_form_value(form, "title"),
        company=_form_value(form, "company"),
        job_status=_form_value(form, "job_status"),
        source=_form_value(form, "source"),
        source_url=_form_value(form, "source_url"),
        apply_url=_form_value(form, "apply_url"),
        location=_form_value(form, "location"),
        remote_policy=_form_value(form, "remote_policy"),
        salary_min=_form_value(form, "salary_min"),
        salary_max=_form_value(form, "salary_max"),
        salary_currency=_form_value(form, "salary_currency"),
        description_raw=_form_value(form, "description_raw"),
    )
    record_job_status_change(db, job, old_status=old_status, new_status=new_status)
    create_job_note(db, job, subject="Job edited", notes="Job details were updated.")
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="overview"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs/{job_uuid}/artefacts/{artefact_uuid}", include_in_schema=False)
def download_job_artefact(
    job_uuid: str,
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    artefact = get_user_job_artefact_by_uuid(db, current_user, job, artefact_uuid)
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    content = get_storage_provider().load(artefact.storage_key)
    filename = quote(artefact.filename)
    return Response(
        content=content,
        media_type=artefact.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/jobs/{job_uuid}/notes", include_in_schema=False)
def create_job_note_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    subject: Annotated[str, Form()] = "Note",
    notes: Annotated[str, Form()] = "",
    follow_up_at: Annotated[str, Form()] = "",
) -> RedirectResponse:
    note_text = notes.strip()
    if not note_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note text is required")

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    create_job_note(
        db,
        job,
        subject=subject.strip() or "Note",
        notes=note_text,
        follow_up_at=_parse_follow_up_date(follow_up_at),
    )
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="notes"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/status", include_in_schema=False)
def update_job_status_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    target_status: Annotated[str, Form()] = "saved",
) -> RedirectResponse:
    new_status = target_status.strip() or "saved"
    if new_status not in JOB_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported job status")

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status = job.status
    update_job_board_state(job, status=new_status)
    record_job_status_change(db, job, old_status=old_status, new_status=job.status)
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="application"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/mark-applied", include_in_schema=False)
def mark_job_applied_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    channel: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status = job.status
    mark_job_applied(
        db,
        job,
        channel=channel.strip() or None,
        notes=notes.strip() or None,
    )
    update_job_board_state(job, status="applied")
    record_job_status_change(db, job, old_status=old_status, new_status=job.status)
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="application"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/application-started", include_in_schema=False)
def mark_application_started_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status = job.status
    if job.status in {"saved", "interested"}:
        update_job_board_state(job, status="preparing")
        record_job_status_change(db, job, old_status=old_status, new_status=job.status)
    note_text = notes.strip() or "Started work on the external application flow."
    create_job_note(db, job, subject="Application started", notes=note_text)
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="follow-ups"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/blockers", include_in_schema=False)
def record_job_blocker_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    notes: Annotated[str, Form()] = "",
    follow_up_at: Annotated[str, Form()] = "",
) -> RedirectResponse:
    blocker_note = notes.strip()
    if not blocker_note:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Blocker note is required")

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    create_job_note(
        db,
        job,
        subject="Blocker recorded",
        notes=blocker_note,
        follow_up_at=_parse_follow_up_date(follow_up_at),
    )
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="follow-ups"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/return-note", include_in_schema=False)
def record_return_note_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    notes: Annotated[str, Form()] = "",
    follow_up_at: Annotated[str, Form()] = "",
) -> RedirectResponse:
    return_note = notes.strip()
    if not return_note:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Return note is required")

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    create_job_note(
        db,
        job,
        subject="Return note",
        notes=return_note,
        follow_up_at=_parse_follow_up_date(follow_up_at),
    )
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="follow-ups"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/ai-outputs", include_in_schema=False)
def create_job_ai_output_route(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    output_type: Annotated[str, Form()] = "fit_summary",
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    try:
        generate_job_ai_output(
            db,
            current_user,
            job,
            output_type=output_type,
            profile=get_user_profile(db, current_user),
        )
    except AiExecutionError as exc:
        db.rollback()
        ai_debug = _log_ai_route_error(route_action=output_type, section="overview", job=job, exc=exc)
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="overview", ai_error=str(exc), ai_debug=ai_debug),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="overview", ai_status="AI output generated"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/artefact-suggestions", include_in_schema=False)
def create_job_artefact_suggestion_route(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    try:
        generate_job_artefact_suggestion(
            db,
            current_user,
            job,
            profile=get_user_profile(db, current_user),
        )
    except AiExecutionError as exc:
        db.rollback()
        ai_debug = _log_ai_route_error(route_action="artefact_suggestion", section="documents", job=job, exc=exc)
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="documents", ai_error=str(exc), ai_debug=ai_debug, ai_tab="compare"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="documents", ai_status="Artefact suggestion generated", ai_tab="compare"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/artefacts/{artefact_uuid}/tailoring-guidance", include_in_schema=False)
def create_job_artefact_tailoring_guidance_route(
    job_uuid: str,
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    focus_areas: Annotated[str, Form()] = "",
    must_include: Annotated[str, Form()] = "",
    avoid: Annotated[str, Form()] = "",
    tone: Annotated[str, Form()] = "",
    extra_context: Annotated[str, Form()] = "",
    skip_brief: Annotated[str, Form()] = "",
    selected_competency_evidence_uuids: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    artefact = get_user_job_artefact_by_uuid(db, current_user, job, artefact_uuid)
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artefact not found")
    prior_suggestion = db.scalar(
        select(AiOutput)
        .where(
            AiOutput.owner_user_id == current_user.id,
            AiOutput.job_id == job.id,
            AiOutput.output_type == "artefact_suggestion",
            AiOutput.status == "active",
        )
        .order_by(AiOutput.updated_at.desc(), AiOutput.created_at.desc())
    )
    try:
        generate_job_artefact_tailoring_guidance(
            db,
            current_user,
            job,
            artefact,
            profile=get_user_profile(db, current_user),
            prior_suggestion=prior_suggestion,
            generation_brief=_submitted_generation_brief(
                skip_brief=skip_brief,
                focus_areas=focus_areas,
                must_include=must_include,
                avoid=avoid,
                tone=tone,
                extra_context=extra_context,
            ),
            selected_competency_evidence_uuids=selected_competency_evidence_uuids,
        )
    except AiExecutionError as exc:
        db.rollback()
        ai_debug = _log_ai_route_error(route_action="tailoring_guidance", section="documents", job=job, exc=exc)
        return RedirectResponse(
            url=_job_detail_redirect(
                job.uuid,
                section="documents",
                ai_error=str(exc),
                ai_debug=ai_debug,
                ai_artefact=artefact.uuid,
                ai_tab="tailor",
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(
            job.uuid,
            section="documents",
            ai_status="Tailoring guidance generated",
            ai_artefact=artefact.uuid,
            ai_tab="tailor",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/artefacts/{artefact_uuid}/analysis", include_in_schema=False)
def create_job_artefact_analysis_route(
    job_uuid: str,
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    artefact = get_user_job_artefact_by_uuid(db, current_user, job, artefact_uuid)
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artefact not found")
    try:
        generate_job_artefact_analysis(
            db,
            current_user,
            job,
            artefact,
            profile=get_user_profile(db, current_user),
        )
    except AiExecutionError as exc:
        db.rollback()
        ai_debug = _log_ai_route_error(route_action="artefact_analysis", section="documents", job=job, exc=exc)
        return RedirectResponse(
            url=_job_detail_redirect(
                job.uuid,
                section="documents",
                ai_error=str(exc),
                ai_debug=ai_debug,
                ai_artefact=artefact.uuid,
                ai_tab="analyse",
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(
            job.uuid,
            section="documents",
            ai_status="Artefact analysis generated",
            ai_artefact=artefact.uuid,
            ai_tab="analyse",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/artefacts/{artefact_uuid}/drafts", include_in_schema=False)
def create_job_artefact_draft_route(
    job_uuid: str,
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    draft_kind: Annotated[str, Form()] = "resume_draft",
    focus_areas: Annotated[str, Form()] = "",
    must_include: Annotated[str, Form()] = "",
    avoid: Annotated[str, Form()] = "",
    tone: Annotated[str, Form()] = "",
    extra_context: Annotated[str, Form()] = "",
    skip_brief: Annotated[str, Form()] = "",
    selected_competency_evidence_uuids: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    artefact = get_user_job_artefact_by_uuid(db, current_user, job, artefact_uuid)
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artefact not found")
    prior_suggestion = db.scalar(
        select(AiOutput)
        .where(
            AiOutput.owner_user_id == current_user.id,
            AiOutput.job_id == job.id,
            AiOutput.output_type == "artefact_suggestion",
            AiOutput.status == "active",
        )
        .order_by(AiOutput.updated_at.desc(), AiOutput.created_at.desc())
    )
    tailoring_guidance = db.scalar(
        select(AiOutput)
        .where(
            AiOutput.owner_user_id == current_user.id,
            AiOutput.job_id == job.id,
            AiOutput.artefact_id == artefact.id,
            AiOutput.output_type == "tailoring_guidance",
            AiOutput.status == "active",
        )
        .order_by(AiOutput.updated_at.desc(), AiOutput.created_at.desc())
    )
    try:
        generate_job_artefact_draft(
            db,
            current_user,
            job,
            artefact,
            draft_kind=draft_kind,
            profile=get_user_profile(db, current_user),
            tailoring_guidance=tailoring_guidance,
            prior_suggestion=prior_suggestion,
            generation_brief=_submitted_generation_brief(
                skip_brief=skip_brief,
                focus_areas=focus_areas,
                must_include=must_include,
                avoid=avoid,
                tone=tone,
                extra_context=extra_context,
            ),
            selected_competency_evidence_uuids=selected_competency_evidence_uuids,
        )
    except AiExecutionError as exc:
        db.rollback()
        ai_debug = _log_ai_route_error(route_action=draft_kind, section="documents", job=job, exc=exc)
        return RedirectResponse(
            url=_job_detail_redirect(
                job.uuid,
                section="documents",
                ai_error=str(exc),
                ai_debug=ai_debug,
                ai_artefact=artefact.uuid,
                ai_tab="draft",
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(
            job.uuid,
            section="documents",
            ai_status="Draft generated",
            ai_artefact=artefact.uuid,
            ai_tab="draft",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _draft_kind_to_artefact_kind(draft_kind: str | None) -> str:
    mapping = {
        "resume_draft": "resume",
        "cover_letter_draft": "cover_letter",
        "supporting_statement_draft": "supporting_statement",
        "attestation_draft": "attestation",
    }
    return mapping.get((draft_kind or "").strip(), "other")


def _draft_filename(job: Job, draft_kind: str | None) -> str:
    slug_source = re.sub(r"[^a-z0-9]+", "-", (job.title or "job").strip().lower()).strip("-") or "job"
    suffix = {
        "resume_draft": "resume-draft",
        "cover_letter_draft": "cover-letter-draft",
        "supporting_statement_draft": "supporting-statement-draft",
        "attestation_draft": "attestation-draft",
    }.get((draft_kind or "").strip(), "draft")
    return f"{slug_source}-{suffix}.md"


@router.post("/jobs/{job_uuid}/ai-outputs/{output_id}/save-draft", include_in_schema=False)
def save_job_draft_as_artefact_route(
    job_uuid: str,
    output_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    output = db.scalar(
        select(AiOutput).where(
            AiOutput.id == output_id,
            AiOutput.owner_user_id == current_user.id,
            AiOutput.job_id == job.id,
            AiOutput.output_type == "draft",
            AiOutput.status == "active",
        )
    )
    if output is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    source_context = output.source_context or {}
    draft_kind = source_context.get("draft_kind") if isinstance(source_context, dict) else None
    artefact = store_job_artefact(
        db,
        job,
        kind=_draft_kind_to_artefact_kind(draft_kind if isinstance(draft_kind, str) else None),
        filename=_draft_filename(job, draft_kind if isinstance(draft_kind, str) else None),
        content=output.body.encode("utf-8"),
        content_type="text/markdown",
    )
    baseline_uuid = source_context.get("artefact_uuid") if isinstance(source_context, dict) else None
    notes = f"Saved from AI draft output #{output.id}."
    if isinstance(baseline_uuid, str) and baseline_uuid:
        notes += f" Baseline artefact UUID: {baseline_uuid}."
    notes += _generation_brief_notes(source_context if isinstance(source_context, dict) else {})
    update_artefact_metadata(
        artefact,
        purpose=output.title or "AI draft",
        version_label="ai-draft-v1",
        notes=notes,
        outcome_context="Generated from visible AI draft output.",
    )
    output.source_context = {
        **source_context,
        "saved_artefact_uuid": artefact.uuid,
    }
    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="documents", ai_status="Draft saved as artefact"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/interviews", include_in_schema=False)
def schedule_interview_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    stage: Annotated[str, Form()] = "",
    scheduled_at: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    participants: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    interview_stage = stage.strip()
    if not interview_stage:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Interview stage is required")

    parsed_scheduled_at = None
    if scheduled_at.strip():
        parsed_scheduled_at = datetime.fromisoformat(scheduled_at.strip())

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status = job.status
    schedule_interview(
        db,
        job,
        stage=interview_stage,
        scheduled_at=parsed_scheduled_at,
        location=location.strip() or None,
        participants=participants.strip() or None,
        notes=notes.strip() or None,
    )
    if job.status in {"saved", "interested", "preparing", "applied"}:
        update_job_board_state(job, status="interviewing")
        record_job_status_change(db, job, old_status=old_status, new_status=job.status)
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="interviews"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/archive", include_in_schema=False)
def archive_job_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status = job.status
    update_job_board_state(job, status="archived")
    record_job_status_change(db, job, old_status=old_status, new_status=job.status)
    if notes.strip():
        create_job_note(
            db,
            job,
            subject="Archived",
            notes=notes.strip(),
        )
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="notes"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/artefacts", include_in_schema=False)
def upload_job_artefact_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    kind: Annotated[str, Form()] = "other",
    file: UploadFile = File(...),
) -> RedirectResponse:
    filename = file.filename or ""
    if not filename.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    artefact = store_job_artefact(
        db,
        job,
        kind=kind,
        filename=filename,
        content=content,
        content_type=file.content_type,
    )
    create_job_note(db, job, subject="Artefact uploaded", notes=f"Uploaded {artefact.filename}.")
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="documents"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/artefact-links", include_in_schema=False)
def link_existing_artefact_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    artefact_uuid: Annotated[str, Form()] = "",
) -> RedirectResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    artefact = get_user_artefact_by_uuid(db, current_user, artefact_uuid.strip())
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artefact not found")
    link_artefact_to_job(db, current_user, job, artefact)
    create_job_note(db, job, subject="Artefact attached", notes=f"Attached {artefact.filename}.")
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="documents"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/{job_uuid}/unarchive", include_in_schema=False)
def unarchive_job_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    target_status: Annotated[str, Form()] = "saved",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    restore_status = target_status.strip() or "saved"
    if restore_status not in BOARD_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported unarchive target status",
        )

    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    old_status = job.status
    update_job_board_state(job, status=restore_status)
    record_job_status_change(db, job, old_status=old_status, new_status=job.status)
    if notes.strip():
        create_job_note(
            db,
            job,
            subject="Unarchived",
            notes=notes.strip(),
        )
    db.commit()
    return RedirectResponse(url=_job_detail_redirect(job.uuid, section="notes"), status_code=status.HTTP_303_SEE_OTHER)
