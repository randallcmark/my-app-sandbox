from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
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
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User
from app.services.ai import (
    AiExecutionError,
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
from app.services.interviews import schedule_interview
from app.services.jobs import (
    BOARD_STATUSES,
    JOB_STATUSES,
    create_job_note,
    get_user_job_by_uuid,
    record_job_status_change,
    update_job_board_state,
)
from app.services.profiles import get_user_profile
from app.storage.provider import get_storage_provider

router = APIRouter(tags=["job-detail"])


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


def _render_inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(.+?)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def _render_markdown_blocks(text: str, *, class_name: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("### "):
            blocks.append(f"<h4>{_render_inline_markdown(line[4:])}</h4>")
            i += 1
            continue
        if line.startswith("## "):
            blocks.append(f"<h3>{_render_inline_markdown(line[3:])}</h3>")
            i += 1
            continue
        if line.startswith("# "):
            blocks.append(f"<h2>{_render_inline_markdown(line[2:])}</h2>")
            i += 1
            continue
        if line.startswith(("* ", "- ")):
            items: list[str] = []
            while i < len(lines):
                bullet = lines[i].strip()
                if not bullet.startswith(("* ", "- ")):
                    break
                items.append(f"<li>{_render_inline_markdown(bullet[2:])}</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue
        paragraph_lines: list[str] = []
        while i < len(lines):
            paragraph = lines[i].strip()
            if not paragraph:
                break
            if paragraph.startswith(("# ", "## ", "### ", "* ", "- ")):
                break
            paragraph_lines.append(paragraph)
            i += 1
        blocks.append(f"<p>{_render_inline_markdown(' '.join(paragraph_lines))}</p>")
    return f'<div class="{escape(class_name, quote=True)}">' + "".join(blocks) + "</div>"


def _render_ai_markdown(text: str) -> str:
    return _render_markdown_blocks(text, class_name="ai-markdown")


def _render_description_markdown(text: str) -> str:
    return _render_markdown_blocks(text, class_name="description-markdown")


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
        '<p class="muted">Analyzed artefact</p>'
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


def _flash_message(message: str, *, tone: str) -> str:
    return f"""
    <section class="workspace-panel flash flash-{escape(tone, quote=True)}">
      <p>{escape(message)}</p>
    </section>
    """


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
    return f"""
    <section class="workspace-side-card workspace-back-card" data-ui-component="job-summary">
      <a class="workspace-back-link" href="/board">← Back to Board</a>
    </section>
    """


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
    actions = '<a class="workspace-inline-link" href="#workspace-tools">Edit</a>'
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


def _workspace_application_section(job: Job) -> str:
    actions = f"""
    <div class="workspace-inline-actions">
      {_button_link("Open apply link", job.apply_url, primary=True)}
      {_button_link("Open source", job.source_url)}
    </div>
    """
    body = f"""
    <div class="workspace-two-up">
      <div class="workspace-subpanel">
        <h3>What this opportunity is</h3>
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
        <h3>Workflow</h3>
        <dl>
          {_editable_select("Status", "status", job.status)}
          {_field("Board position", job.board_position)}
          {_editable_text("Source", "source", job.source)}
          {_editable_url("Source URL", "source_url", job.source_url, "Open source")}
          {_editable_url("Apply URL", "apply_url", job.apply_url, "Open apply link")}
        </dl>
      </div>
    </div>
    <div class="workspace-three-up">
      <div class="workspace-subpanel">
        <h3>Applications</h3>
        {_applications(job.applications)}
      </div>
      <div class="workspace-subpanel">
        <h3>Move status</h3>
        {_status_transition_form(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Mark applied</h3>
        {_mark_applied_form(job)}
      </div>
    </div>
    """
    return _workspace_section(
        section_id="application",
        kicker="Application",
        title="Application state and route",
        body=body,
        actions=actions,
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


def _artefact_local_ai_workspace(job: Job, output: AiOutput | None, artefact_lookup: dict[str, Artefact]) -> str:
    if output is None:
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

    source_context = output.source_context or {}
    tab_map = {
        "artefact_analysis": "Analyze",
        "tailoring_guidance": "Tailor",
        "draft": "Draft",
        "artefact_suggestion": "Compare",
    }
    active_tab = tab_map.get(output.output_type, "Draft")
    artefact_name = "Current selection"
    if output.artefact_id is not None:
        matching = next((item for item in artefact_lookup.values() if item.id == output.artefact_id), None)
        if matching is not None:
            artefact_name = matching.filename
    tabs = "".join(
        f'<div class="workspace-local-ai-tab{" active" if label == active_tab else ""}">{escape(label)}</div>'
        for label in ("Analyze", "Tailor", "Improve", "Draft", "Compare", "Score")
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
    body = f"""
    <div class="workspace-ai-side">
      <div class="workspace-ai-generate-box">
        <div class="workspace-ai-generate-title">{escape(output.title or 'AI output')}</div>
        <p class="muted">This local workspace keeps artefact-specific AI output attached to the document instead of the global page rail.</p>
      </div>
    </div>
    <div class="workspace-ai-results">
      <div class="workspace-ai-results-title">{escape(output.title or output.output_type.replace('_', ' ').title())}</div>
      {provider_line}
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


def _workspace_artefact_item(job: Job, artefact: Artefact) -> str:
    version = escape(artefact.version_label) if artefact.version_label else escape(_artefact_type_label(artefact))
    updated = escape(_value(artefact.updated_at))
    badges = _artefact_primary_badge(artefact)
    return f"""
    <article class="workspace-artefact-item">
      <div class="workspace-artefact-left">
        <div class="workspace-doc-icon">▣</div>
        <div>
          <div class="workspace-artefact-name">{escape(artefact.filename)}</div>
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
            <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/tailoring-guidance">
              <button class="outline" type="submit">Tailor</button>
            </form>
            <form class="inline-action-form" method="post" action="/jobs/{escape(job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}/analysis">
              <button class="outline" type="submit">Analyze</button>
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
) -> str:
    artefact_list = "".join(_workspace_artefact_item(job, artefact) for artefact in artefacts)
    if not artefact_list:
        artefact_list = '<p class="empty">No artefacts uploaded yet.</p>'
    body = f"""
    <div class="workspace-artefact-list" data-ui-component="artefact-list">
      {artefact_list}
    </div>
    {_artefact_local_ai_workspace(job, _latest_artefact_ai_output(ai_outputs, artefacts), artefact_lookup)}
    <div class="workspace-support-tools">
      <details>
        <summary>Document tools</summary>
        <div class="workspace-two-up">
          <div class="workspace-subpanel">
            <h3>Attach Existing</h3>
            {_link_existing_artefact_form(job, available_artefacts)}
          </div>
          <div class="workspace-subpanel">
            <h3>Upload artefact</h3>
            {_artefact_form(job)}
          </div>
        </div>
      </details>
    </div>
    """
    return _workspace_section(
        section_id="documents",
        kicker="Documents",
        title="Artefacts",
        body=body,
    )


def _workspace_interviews_section(job: Job) -> str:
    body = f"""
    <div class="workspace-two-up">
      <div class="workspace-subpanel">
        <h3>Interviews</h3>
        {_interviews(job.interviews)}
      </div>
      <div class="workspace-subpanel">
        <h3>Schedule Interview</h3>
        {_schedule_interview_form(job)}
      </div>
    </div>
    """
    return _workspace_section(section_id="interviews", kicker="Interviews", title="Conversation planning", body=body)


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


def _workspace_follow_ups_section(job: Job) -> str:
    body = f"""
    <div class="workspace-three-up">
      <div class="workspace-subpanel">
        <h3>Scheduled follow-ups</h3>
        {_follow_up_list(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Application started</h3>
        {_application_started_form(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Blockers</h3>
        {_blocker_form(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Return note</h3>
        {_return_note_form(job)}
      </div>
    </div>
    """
    return _workspace_section(section_id="follow-ups", kicker="Follow-ups", title="External workflow and return path", body=body)


def _workspace_tasks_section(job: Job, artefacts: list[Artefact]) -> str:
    body = f"""
    {_next_action(job)}
    {_readiness(job, artefacts)}
    """
    return _workspace_section(section_id="tasks", kicker="Tasks", title="Next action and readiness", body=body)


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
    body = f"""
    <div class="workspace-two-up">
      <div class="workspace-subpanel">
        <h3>Recent Activity</h3>
        {_recent_activity(job, events, artefacts)}
      </div>
      <div class="workspace-subpanel">
        <h3>Add Note</h3>
        {_note_form(job)}
      </div>
    </div>
    {_provenance(job)}
    <section class="workspace-subpanel">
      <details class="timeline-panel">
        <summary>Journal</summary>
        {_timeline(events)}
      </details>
    </section>
    """
    return _workspace_section(section_id="notes", kicker="Notes", title="Activity, context, and provenance", body=body)


def _workspace_ai_assessment(ai_outputs: list[AiOutput]) -> str:
    fit_output = _latest_ai_output(ai_outputs, "fit_summary")
    if fit_output is None:
        return """
        <section class="workspace-rail-panel" data-ui-component="ai-assessment">
          <div class="workspace-side-heading">Overall Assessment</div>
          <p class="muted">No fit summary yet. Generate one when you want a current read on the match.</p>
        </section>
        """
    return f"""
    <section class="workspace-rail-panel emphasis" data-ui-component="ai-assessment">
      <div class="workspace-side-heading">Overall Assessment</div>
      {_ai_badge(fit_output.output_type)}
      <p class="muted">From {escape(fit_output.model_name or fit_output.provider or "AI")}</p>
      <div class="workspace-constrained-body ai-assessment-body" data-ui-component="ai-assessment-body">
        {_render_ai_markdown(fit_output.body)}
      </div>
    </section>
    """


def _workspace_ai_sidebar(job: Job, ai_outputs: list[AiOutput], artefact_lookup: dict[str, Artefact]) -> str:
    return f"""
    <aside class="workspace-right-rail" data-ui-component="ai-rail">
      <section class="workspace-rail-shell">
        <div class="workspace-rail-head">
          <span>AI Assistant</span>
          <span class="muted">Visible only</span>
        </div>
        <div class="workspace-rail-body">
          {_workspace_ai_assessment(ai_outputs)}
        </div>
      </section>
      <section class="workspace-side-card" data-ui-component="ai-help-list">
        <div class="workspace-side-heading">AI can help you with</div>
        <div class="workspace-help-list">
          <div class="workspace-help-item"><strong>Tailor your resume</strong><span>›</span></div>
          <div class="workspace-help-item"><strong>Prepare for interviews</strong><span>›</span></div>
          <div class="workspace-help-item"><strong>Draft follow-up email</strong><span>›</span></div>
          <div class="workspace-help-item"><strong>Analyze role fit</strong><span>›</span></div>
        </div>
        <p class="muted">AI uses your job, artefacts, and profile information to generate insights.</p>
      </section>
    </aside>
    """


def _workspace_tools_section(job: Job, artefacts: list[Artefact]) -> str:
    body = f"""
    <div class="workspace-two-up" data-ui-component="tasks-workbench">
      <div class="workspace-subpanel">
        <h3>Current focus</h3>
        {_next_action(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Workflow actions</h3>
        {_mark_applied_form(job)}
        {_status_transition_form(job)}
        {_schedule_interview_form(job)}
        {_application_started_form(job)}
      </div>
    </div>
    <div class="workspace-three-up">
      <div class="workspace-subpanel">
        <h3>Follow-through</h3>
        {_blocker_form(job)}
        {_return_note_form(job)}
      </div>
      <div class="workspace-subpanel" id="workspace-tools">
        <h3>Maintenance</h3>
        {_archive_form(job)}
        {_unarchive_form(job)}
      </div>
      <div class="workspace-subpanel">
        <h3>Document work</h3>
        <p class="muted">Go to Documents when you need uploads, existing artefacts, or local AI drafting.</p>
        <a class="button-link" href="/jobs/{escape(job.uuid, quote=True)}?section=documents">Open documents</a>
      </div>
    </div>
    """
    return _workspace_section(section_id="tasks", kicker="Tasks", title="Tasks", body=body)


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
    h1 { font-size: 2rem; line-height: 1.1; }
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
      border: 0;
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      min-height: 38px;
      padding: 0 14px;
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
        subtitle="Create an intentional job entry",
        active=None,
        body=f'<section class="page-panel">{_new_job_form()}</section>',
        kicker="Manual entry",
        container="workspace",
        extra_styles=extra_styles,
    )


def render_job_detail(
    job: Job,
    *,
    available_artefacts: list[Artefact] | None = None,
    ai_status: str | None = None,
    ai_error: str | None = None,
    active_section: str = "overview",
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

    extra_styles = f"""
    h1, h2, h3, p {{ margin: 0; }}
    a {{ color: var(--accent-strong); font-weight: 500; }}
    button {{
      background: linear-gradient(180deg, #7a66ef, var(--accent));
      border: 0;
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 600;
      min-height: 38px;
      padding: 0 14px;
    }}
    button:hover {{ background: var(--accent-strong); }}
    button.outline, .button-link {{
      background: #ffffff;
      border: 0.5px solid var(--line);
      color: var(--ink);
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
      font-size: 0.82rem;
      line-height: 1;
      padding: 6px 10px;
    }}
    .stage-pill.inbox {{ background: #e8ebf8; color: #2d3a9a; }}
    .stage-pill.active {{ background: #fdf3e6; color: #8c4a00; }}
    .stage-pill.success {{ background: #eaf4ee; color: #1a5c38; }}
    .stage-pill.closed {{ background: #f1f0ed; color: #5f5e5a; }}
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
    }}
    .workspace-side-card,
    .workspace-surface,
    .workspace-rail-shell,
    .workspace-rail-panel,
    .workspace-progress-card,
    .workspace-next-up,
    .workspace-subpanel,
    .workspace-panel {{
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
    }}
    .flash {{ margin-bottom: 18px; padding: 18px 20px; }}
    .flash-success {{
      background: linear-gradient(180deg, rgba(234,244,238,0.98), rgba(244,249,246,0.98));
      border-color: rgba(59,167,134,0.28);
    }}
    .flash-error {{
      background: linear-gradient(180deg, rgba(253,239,237,0.98), rgba(255,246,244,0.98));
      border-color: rgba(226,91,76,0.28);
    }}
    .workspace-side-card {{ padding: 16px; }}
    .workspace-quick-actions {{
      position: relative;
    }}
    .workspace-quick-trigger {{
      align-items: center;
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      color: var(--ink);
      cursor: pointer;
      display: flex;
      font-weight: 800;
      justify-content: space-between;
      list-style: none;
      min-height: 46px;
      padding: 0 16px;
    }}
    .workspace-quick-trigger::-webkit-details-marker {{ display: none; }}
    .workspace-quick-actions[open] .workspace-quick-trigger {{
      border-bottom-left-radius: 12px;
      border-bottom-right-radius: 12px;
    }}
    .workspace-quick-panel {{
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.99));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-lg);
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
    .workspace-back-link {{
      color: var(--muted);
      display: inline-flex;
      font-size: 0.92rem;
      gap: 8px;
      margin-bottom: 14px;
      text-decoration: none;
    }}
    .workspace-back-card {{
      padding: 12px 16px;
    }}
    .workspace-anchor-nav {{
      display: grid;
      gap: 4px;
    }}
    .workspace-nav-link,
    .workspace-quick-link {{
      align-items: center;
      border-radius: 10px;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      min-height: 38px;
      padding: 0 12px;
      text-decoration: none;
    }}
    .workspace-quick-link {{
      background: rgba(112, 87, 232, 0.03);
      border: 1px solid rgba(112, 87, 232, 0.08);
    }}
    .workspace-nav-link.active {{
      background: rgba(112, 87, 232, 0.08);
      border: 1px solid rgba(112, 87, 232, 0.22);
      color: var(--accent-strong);
    }}
    .workspace-nav-count {{
      align-items: center;
      background: rgba(112, 87, 232, 0.1);
      border-radius: 999px;
      color: var(--accent);
      display: inline-flex;
      font-size: 0.75rem;
      height: 22px;
      justify-content: center;
      min-width: 22px;
      padding: 0 6px;
    }}
    .workspace-side-heading {{ font-size: 0.98rem; font-weight: 800; margin-bottom: 12px; }}
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
      font-size: 1.35rem;
      font-weight: 800;
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
      background: linear-gradient(180deg, #7a66ef, var(--accent));
      border-color: #6c59dd;
      color: #ffffff;
    }}
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
      font-size: 1.45rem;
      line-height: 1.08;
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
    .workspace-next-title {{ font-size: 1.1rem; font-weight: 800; margin-bottom: 6px; }}
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
    .workspace-three-up {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .workspace-subpanel {{
      display: grid;
      gap: 14px;
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
      background: rgba(112, 87, 232, 0.08);
      border-radius: 10px;
      color: var(--accent);
      display: inline-flex;
      font-size: 0.78rem;
      font-weight: 700;
      min-height: 28px;
      padding: 0 10px;
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
      min-height: 34px;
      padding: 0 12px;
    }}
    .workspace-ai-pill {{
      align-items: center;
      background: rgba(112, 87, 232, 0.1);
      border-radius: 999px;
      color: var(--accent);
      display: inline-flex;
      font-size: 0.75rem;
      font-weight: 800;
      min-height: 24px;
      padding: 0 8px;
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
      background: rgba(31, 52, 71, 0.96);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-lg);
      bottom: 18px;
      color: #ffffff;
      display: none;
      gap: 12px;
      left: 50%;
      padding: 10px 12px;
      position: fixed;
      transform: translateX(-50%);
      z-index: 20;
    }}
    .savebar.is-visible {{ display: flex; }}
    .savebar p {{ font-weight: 500; }}
    .savebar .secondary {{ background: transparent; border: 1px solid rgba(255,255,255,0.45); }}
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
      border-bottom: 1px solid var(--line);
      display: flex;
      gap: 12px;
      justify-content: space-between;
      padding: 16px 18px;
      font-weight: 800;
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
    .workspace-help-item {{
      align-items: center;
      border-top: 1px solid #f0f1f6;
      color: var(--text-muted);
      display: flex;
      font-size: 0.9rem;
      gap: 12px;
      justify-content: space-between;
      padding: 14px 0;
    }}
    .workspace-help-item:first-child {{ border-top: 0; }}
    .workspace-help-item strong {{ color: var(--accent-strong); }}
    .workspace-artefact-list {{
      border: 1px solid var(--line);
      border-radius: 16px;
      display: grid;
      overflow: hidden;
    }}
    .workspace-artefact-item {{
      align-items: center;
      background: #ffffff;
      border-top: 1px solid #f0f1f6;
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 14px 16px;
    }}
    .workspace-artefact-item:first-child {{ border-top: 0; }}
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
    .workspace-artefact-name {{ font-size: 0.95rem; font-weight: 800; margin-bottom: 3px; overflow-wrap: anywhere; }}
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
      gap: 10px;
    }}
    .action-btn {{
      align-items: center;
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 10px;
      color: var(--text);
      display: inline-flex;
      font-weight: 700;
      gap: 8px;
      min-height: 36px;
      padding: 0 12px;
      text-decoration: none;
    }}
    .action-btn.ai {{
      background: #fbfaff;
      border-color: #dbd5ff;
      color: var(--accent);
    }}
    .workspace-ai-menu {{
      position: relative;
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
      margin-top: 8px;
      padding: 10px;
      position: absolute;
      right: 0;
      width: 220px;
      z-index: 2;
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
      font-weight: 800;
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
      font-size: 0.82rem;
      font-weight: 700;
      padding: 14px 0 12px;
      position: relative;
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
      grid-template-columns: 320px 1fr;
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
    .workspace-ai-generate-title,
    .workspace-ai-results-title {{
      font-weight: 800;
    }}
    .workspace-local-ai-foot {{
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      padding: 0 16px 16px;
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
    @media (max-width: 1360px) {{
      .workspace-grid {{ grid-template-columns: 220px minmax(0, 1fr) 300px; }}
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
      .workspace-ai-menu-body {{
        position: static;
        width: 100%;
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
        "documents": _workspace_artefacts_section(job, artefacts, available_artefacts, ai_outputs, artefact_lookup),
    }
    body = f"""
    {(_flash_message(ai_status, tone="success") if ai_status else "")}
    {(_flash_message(ai_error, tone="error") if ai_error else "")}
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
        {_workspace_tools_section(job, artefacts) if active_section == "tasks" else ""}
      </section>
      {_workspace_ai_sidebar(job, ai_outputs, artefact_lookup)}
    </div>
    <div id="edit-savebar" class="savebar" aria-live="polite">
      <p>Unsaved changes</p>
      <button id="save-inline-edits" type="button">Save</button>
      <button id="cancel-inline-edits" class="secondary" type="button">Cancel</button>
    </div>
    """
    scripts = f"""
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
) -> str:
    params = []
    normalized_section = _normalize_workspace_section(section)
    if normalized_section != "overview":
        params.append(f"section={quote(normalized_section)}")
    if ai_status:
        params.append(f"ai_status={quote(ai_status)}")
    if ai_error:
        params.append(f"ai_error={quote(ai_error)}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return f"/jobs/{job_uuid}{suffix}"


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
    section: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    return HTMLResponse(
        render_job_detail(
            job,
            available_artefacts=list_user_unlinked_artefacts_for_job(db, current_user, job),
            ai_status=ai_status,
            ai_error=ai_error,
            active_section=section or "overview",
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
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="overview", ai_error=str(exc)),
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
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="documents", ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="documents", ai_status="Artefact suggestion generated"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/artefacts/{artefact_uuid}/tailoring-guidance", include_in_schema=False)
def create_job_artefact_tailoring_guidance_route(
    job_uuid: str,
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
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
        )
    except AiExecutionError as exc:
        db.rollback()
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="documents", ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="documents", ai_status="Tailoring guidance generated"),
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
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="documents", ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="documents", ai_status="Artefact analysis generated"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_uuid}/artefacts/{artefact_uuid}/drafts", include_in_schema=False)
def create_job_artefact_draft_route(
    job_uuid: str,
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    draft_kind: Annotated[str, Form()] = "resume_draft",
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
        )
    except AiExecutionError as exc:
        db.rollback()
        return RedirectResponse(
            url=_job_detail_redirect(job.uuid, section="documents", ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, section="documents", ai_status="Draft generated"),
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
