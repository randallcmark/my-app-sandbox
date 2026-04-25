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
) -> str:
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
    h1, h2, p {{ margin: 0; }}
    h1 {{ font-size: 2rem; line-height: 1.1; overflow-wrap: anywhere; }}

    h2 {{
      font-size: 1.1rem;
      margin-bottom: 12px;
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      min-height: 38px;
      padding: 0 14px;
    }}

    input,
    select,
    textarea {{
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }}

    textarea {{
      resize: vertical;
    }}

    label {{
      display: grid;
      font-weight: 500;
      gap: 6px;
    }}

    .note-form,
    .job-form,
    .quick-action-form {{
      display: grid;
      gap: 12px;
    }}

    .inline-fields {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    .subhead {{
      color: var(--muted);
      margin-top: 6px;
    }}

    .workspace-hero {{
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-2xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 16px;
      margin-bottom: 18px;
      padding: 24px;
    }}

    .hero-meta,
    .meta-row {{
      align-items: center;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .hero-meta span:not(:last-child)::after,
    .meta-row span:not(:last-child)::after {{
      content: "·";
      margin-left: 8px;
    }}

    .layout {{
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    }}

    .workspace-main,
    .workspace-aside {{
      align-content: start;
      display: grid;
      gap: 18px;
    }}

    .workspace-panel {{
      border-radius: var(--radius-xl);
      border: 1px solid var(--line-soft);
      box-shadow: var(--shadow-md);
      padding: 20px;
    }}

    .flash {{
      margin-bottom: 18px;
    }}

    .flash-success {{
      background: linear-gradient(180deg, rgba(234,244,238,0.98), rgba(244,249,246,0.98));
      border-color: rgba(59,167,134,0.28);
    }}

    .flash-error {{
      background: linear-gradient(180deg, rgba(253,239,237,0.98), rgba(255,246,244,0.98));
      border-color: rgba(226,91,76,0.28);
    }}

    .section-heading {{
      margin-bottom: 14px;
    }}

    .eyebrow {{
      color: var(--muted);
      font-size: 0.76rem;
      letter-spacing: 0.04em;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}

    .stage-pill {{
      border-radius: 999px;
      display: inline-flex;
      font-size: 0.82rem;
      line-height: 1;
      padding: 6px 10px;
    }}

    .stage-pill.inbox {{
      background: #e8ebf8;
      color: #2d3a9a;
    }}

    .stage-pill.active {{
      background: #fdf3e6;
      color: #8c4a00;
    }}

    .stage-pill.success {{
      background: #eaf4ee;
      color: #1a5c38;
    }}

    .stage-pill.closed {{
      background: #f1f0ed;
      color: #5f5e5a;
    }}

    .next-action {{
      align-items: start;
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1fr) auto;
    }}

    .next-action h2 {{
      margin-bottom: 6px;
    }}

    .next-action p:not(.eyebrow) {{
      color: var(--muted);
    }}

    .next-action-controls {{
      align-items: center;
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }}

    .inline-action-form {{
      margin: 0;
    }}

    .action-stack {{
      display: grid;
      gap: 8px;
    }}

    .button-link {{
      align-items: center;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      color: var(--ink);
      display: inline-flex;
      justify-content: center;
      min-height: 38px;
      padding: 0 14px;
      text-decoration: none;
    }}

    .button-link.primary {{
      background: linear-gradient(180deg, #2a81e7, var(--accent));
      border-color: #1b6fce;
      color: #ffffff;
    }}

    button.outline {{
      background: transparent;
      border: 0.5px solid var(--line);
      color: var(--ink);
    }}

    button.outline:hover,
    .button-link:hover {{
      background: #f1f0ed;
    }}

    .button-link.primary:hover {{
      background: var(--accent-strong);
      color: #ffffff;
    }}

    .overview-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin: 0;
    }}

    .readiness-list {{
      display: grid;
      gap: 0;
    }}

    .readiness-item {{
      border-left: 0;
      border-top: 1px solid var(--line);
      display: grid;
      gap: 3px;
      padding: 12px 0 12px 26px;
      position: relative;
    }}

    .readiness-item:first-child {{
      border-top: 0;
    }}

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

    .readiness-item.done::before {{
      background: #2a8a58;
      border-color: #2a8a58;
    }}

    .readiness-item span {{
      font-weight: 500;
    }}

    .readiness-item p {{
      color: var(--muted);
    }}

    .activity-grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    .artefact-actions {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    .provenance-panel dl {{
      margin-top: 14px;
    }}

    .provenance-panel h3 {{
      font-size: 0.95rem;
      margin: 18px 0 8px;
    }}

    .provenance-links li {{
      border-left: 0;
      padding-left: 0;
      overflow-wrap: anywhere;
    }}

    dl {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 0;
    }}

    .field {{
      min-width: 0;
    }}

    dt {{
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 500;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}

    dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}

    .editable {{
      border: 1px solid transparent;
      border-radius: 10px;
      cursor: text;
      margin: -5px;
      padding: 5px;
    }}

    .editable:hover,
    .editable:focus {{
      border-color: var(--line);
      outline: 0;
    }}

    .editable.is-editing {{
      background: #ffffff;
      border-color: var(--accent);
      cursor: default;
    }}

    .editable-control {{
      display: none;
    }}

    .editable.is-editing > .editable-control,
    .editable.is-editing .editable-control {{
      display: block;
    }}

    .editable.is-editing > .editable-display,
    .editable.is-editing .editable-display {{
      display: none;
    }}

    .editable-heading .editable-control {{
      font-size: 2rem;
      font-weight: 500;
      line-height: 1.1;
    }}

    pre {{
      font-family: inherit;
      line-height: 1.5;
      margin: 0;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}

    .description-editor {{
      min-height: 420px;
    }}

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

    .savebar.is-visible {{
      display: flex;
    }}

    .savebar p {{
      font-weight: 500;
    }}

    .savebar .secondary {{
      background: transparent;
      border: 1px solid rgba(255, 255, 255, 0.45);
    }}

    .timeline-panel summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-weight: 500;
    }}

    .ai-output-list {{
      display: grid;
      gap: 12px;
    }}

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

    .ai-output-links ul {{
      display: grid;
      gap: 6px;
      list-style: none;
      margin: 0;
      padding: 0;
    }}

    .ai-markdown {{
      display: grid;
      gap: 10px;
    }}

    .description-markdown {{
      display: grid;
      gap: 12px;
    }}

    .description-markdown h2,
    .description-markdown h3,
    .description-markdown h4 {{
      margin: 0;
    }}

    .description-markdown p {{
      margin: 0;
    }}

    .description-markdown ul {{
      display: grid;
      gap: 8px;
      list-style: disc;
      margin: 0;
      padding-left: 22px;
    }}

    .description-markdown li {{
      border-left: 0;
      padding-left: 0;
    }}

    .ai-markdown h2,
    .ai-markdown h3,
    .ai-markdown h4 {{
      margin: 0;
    }}

    .ai-markdown p {{
      margin: 0;
    }}

    .ai-markdown ul {{
      display: grid;
      gap: 8px;
      list-style: disc;
      margin: 0;
      padding-left: 22px;
    }}

    .ai-markdown li {{
      border-left: 0;
      padding-left: 0;
    }}

    .timeline-panel ol {{
      margin-top: 12px;
    }}

    ol {{
      display: grid;
      gap: 12px;
      list-style: none;
      margin: 0;
      padding: 0;
    }}

    li {{
      border-left: 4px solid var(--accent);
      padding-left: 12px;
    }}

    time,
    .muted,
    .empty {{
      color: var(--muted);
    }}

    li strong {{
      display: block;
      margin: 4px 0;
    }}

    @media (max-width: 800px) {{
      .layout,
      .inline-fields {{
        display: grid;
      }}

      .layout {{
        grid-template-columns: 1fr;
      }}

      .workspace-main,
      .workspace-aside,
      .workspace-panel,
      .workspace-hero {{
        min-width: 0;
      }}

      .workspace-aside {{
        order: 2;
      }}

      .workspace-main {{
        order: 1;
      }}

      .next-action,
      .overview-grid,
      .activity-grid {{
        grid-template-columns: 1fr;
      }}

      .next-action-controls {{
        justify-content: stretch;
      }}

      .next-action-controls > *,
      .button-link {{
        width: 100%;
      }}

      .editable-heading .editable-control {{
        font-size: 1.5rem;
      }}

      .description-editor {{
        min-height: 280px;
      }}

      .savebar {{
        bottom: 12px;
        display: none;
        gap: 8px;
        left: 12px;
        right: 12px;
        transform: none;
      }}

      .savebar.is-visible {{
        display: grid;
      }}

      .savebar button {{
        width: 100%;
      }}

      dl {{
        grid-template-columns: 1fr;
      }}
    }}
    """
    body = f"""
    {(_flash_message(ai_status, tone="success") if ai_status else "")}
    {(_flash_message(ai_error, tone="error") if ai_error else "")}
    <section class="workspace-hero">
      <div>
        {_editable_title(job)}
        <div class="hero-meta">
          <span>{escape(job.company or "Company not set")}</span>
          <span>{escape(job.location or "Location not set")}</span>
          <span>{escape(_salary_range(job))}</span>
          {_stage_pill(job.status)}
        </div>
      </div>
    </section>

    <div class="layout">
      <div class="workspace-main">
        {_next_action(job)}
        <section class="workspace-panel">
          <div class="section-heading">
            <p class="eyebrow">Role overview</p>
            <h2>What this opportunity is</h2>
          </div>
          <dl class="overview-grid">
            {_editable_text("Company", "company", job.company)}
            {_editable_text("Location", "location", job.location)}
            {_editable_text("Remote policy", "remote_policy", job.remote_policy)}
            {_editable_text("Salary min", "salary_min", job.salary_min)}
            {_editable_text("Salary max", "salary_max", job.salary_max)}
            {_editable_text("Currency", "salary_currency", job.salary_currency)}
          </dl>
        </section>
        <section class="workspace-panel">
          <div class="section-heading">
            <p class="eyebrow">Description</p>
            <h2>Role description</h2>
          </div>
          {_editable_description(job)}
        </section>
        {_readiness(job, artefacts)}
        <section class="workspace-panel">
          <div class="section-heading">
            <p class="eyebrow">AI guidance</p>
            <h2>Visible AI output</h2>
          </div>
          {_ai_outputs_panel(ai_outputs, artefact_lookup=artefact_lookup)}
        </section>
        <section class="workspace-panel">
          <div class="section-heading">
            <p class="eyebrow">Activity</p>
            <h2>Application and interviews</h2>
          </div>
          <div class="activity-grid">
            <div>
              <h3>Applications</h3>
              {_applications(job.applications)}
            </div>
            <div>
              <h3>Interviews</h3>
              {_interviews(job.interviews)}
            </div>
          </div>
        </section>
      </div>
      <aside class="workspace-aside">
        {_external_links(job)}
        <section class="workspace-panel">
          <div class="section-heading">
            <p class="eyebrow">AI actions</p>
            <h2>Generate guidance</h2>
          </div>
          {_ai_actions(job)}
        </section>
        <section class="workspace-panel">
          <div class="section-heading">
            <p class="eyebrow">State</p>
            <h2>Workflow</h2>
          </div>
          <dl>
            {_editable_select("Status", "status", job.status)}
            {_field("Board position", job.board_position)}
            {_editable_text("Source", "source", job.source)}
            {_field("Captured", job.captured_at)}
            {_editable_url("Source URL", "source_url", job.source_url, "Open source")}
            {_editable_url("Apply URL", "apply_url", job.apply_url, "Open apply link")}
          </dl>
        </section>
        <section class="workspace-panel">
          <h2>Move status</h2>
          {_status_transition_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>Artefacts</h2>
          {_artefacts(job, artefacts)}
          <h2>AI artefact help</h2>
          {_artefact_ai_action(job)}
          <h2>Attach Existing</h2>
          {_link_existing_artefact_form(job, available_artefacts)}
          {_artefact_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>Schedule Interview</h2>
          {_schedule_interview_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>Mark Applied</h2>
          {_mark_applied_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>External workflow actions</h2>
          {_application_started_form(job)}
          {_blocker_form(job)}
          {_return_note_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>Archive</h2>
          {_archive_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>Unarchive</h2>
          {_unarchive_form(job)}
        </section>
        <section class="workspace-panel">
          <h2>Add Note</h2>
          {_note_form(job)}
        </section>
        {_provenance(job)}
        <section class="workspace-panel">
          <details class="timeline-panel">
            <summary>Journal</summary>
            {_timeline(events)}
          </details>
        </section>
      </aside>
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
        goal=f"<span>Company:</span> <strong>{escape(job.company or 'Not set')}</strong> | <span>{escape(job.status)}</span>",
        container="standard",
        extra_styles=extra_styles,
        scripts=scripts,
    )


def _job_detail_redirect(job_uuid: str, *, ai_status: str | None = None, ai_error: str | None = None) -> str:
    params = []
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
) -> HTMLResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    return HTMLResponse(
        render_job_detail(
            job,
            available_artefacts=list_user_unlinked_artefacts_for_job(db, current_user, job),
            ai_status=ai_status,
            ai_error=ai_error,
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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
            url=_job_detail_redirect(job.uuid, ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, ai_status="AI output generated"),
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
            url=_job_detail_redirect(job.uuid, ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, ai_status="Artefact suggestion generated"),
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
            url=_job_detail_redirect(job.uuid, ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, ai_status="Tailoring guidance generated"),
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
            url=_job_detail_redirect(job.uuid, ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.commit()
    return RedirectResponse(
        url=_job_detail_redirect(job.uuid, ai_status="Draft generated"),
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
        url=_job_detail_redirect(job.uuid, ai_status="Draft saved as artefact"),
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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/jobs/{job.uuid}", status_code=status.HTTP_303_SEE_OTHER)
