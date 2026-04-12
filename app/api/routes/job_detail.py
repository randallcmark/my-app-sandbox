from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from starlette.datastructures import FormData

from app.api.deps import DbSession, get_current_user
from app.api.ownership import require_owner
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User
from app.services.applications import mark_job_applied
from app.services.artefacts import get_user_job_artefact_by_uuid, store_job_artefact
from app.services.interviews import schedule_interview
from app.services.jobs import (
    BOARD_STATUSES,
    JOB_STATUSES,
    create_job_note,
    get_user_job_by_uuid,
    record_job_status_change,
    update_job_board_state,
)
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
        f"<pre>{escape(job.description_raw)}</pre>"
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
        f'<p class="follow-up">Follow-up: {escape(_value(event.follow_up_at))}</p>'
        if event.follow_up_at
        else ""
    )
    notes = f"<p>{escape(event.notes)}</p>" if event.notes else ""
    return f"""
    <li>
      <time>{escape(_value(occurred_at))}</time>
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


def _artefact(artefact: Artefact) -> str:
    size = f"{artefact.size_bytes} bytes" if artefact.size_bytes is not None else "Size not set"
    return f"""
    <li>
      <strong>{escape(artefact.filename)}</strong>
      <p>{escape(artefact.kind)} · {escape(size)}</p>
      <p><a href="/jobs/{escape(artefact.job.uuid, quote=True)}/artefacts/{escape(artefact.uuid, quote=True)}">Download</a></p>
    </li>
    """


def _artefacts(artefacts: list[Artefact]) -> str:
    if not artefacts:
        return '<p class="empty">No artefacts uploaded yet.</p>'
    items = "\n".join(_artefact(artefact) for artefact in artefacts)
    return f"<ol>{items}</ol>"


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


def render_new_job() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Add Job - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
    }}

    main {{
      margin: 0 auto;
      max-width: 840px;
      min-height: 100vh;
      padding: 24px;
    }}

    .topbar {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 24px;
    }}

    h1, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 700;
    }}

    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }}

    .job-form {{
      display: grid;
      gap: 14px;
    }}

    .inline-fields {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}

    label {{
      display: grid;
      font-weight: 700;
      gap: 6px;
    }}

    input,
    select,
    textarea {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }}

    textarea {{
      resize: vertical;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      min-height: 38px;
      padding: 0 14px;
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    @media (max-width: 720px) {{
      main {{
        padding: 16px;
      }}

      .topbar,
      .inline-fields {{
        display: grid;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <h1>Add job</h1>
      <a href="/board">Board</a>
    </header>
    <section>
      {_new_job_form()}
    </section>
  </main>
</body>
</html>"""


def render_job_detail(job: Job) -> str:
    events = sorted(
        job.communications,
        key=lambda event: event.occurred_at or event.created_at,
        reverse=True,
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(job.title)} - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
    }}

    main {{
      margin: 0 auto;
      max-width: 1120px;
      min-height: 100vh;
      padding: 24px;
    }}

    .topbar {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 24px;
    }}

    nav {{
      align-items: center;
      display: flex;
      gap: 12px;
    }}

    h1, h2, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }}

    h2 {{
      font-size: 1.1rem;
      margin-bottom: 12px;
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 700;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      min-height: 38px;
      padding: 0 14px;
    }}

    input,
    select,
    textarea {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }}

    textarea {{
      resize: vertical;
    }}

    label {{
      display: grid;
      font-weight: 700;
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

    .layout {{
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    }}

    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
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
      font-weight: 700;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}

    dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}

    .editable {{
      border: 1px solid transparent;
      border-radius: 8px;
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
      font-weight: 700;
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
      background: var(--ink);
      border-radius: 8px;
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
      font-weight: 700;
    }}

    .savebar .secondary {{
      background: transparent;
      border: 1px solid rgba(255, 255, 255, 0.45);
    }}

    .timeline-panel summary {{
      color: var(--accent-strong);
      cursor: pointer;
      font-weight: 700;
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
      main {{
        padding: 16px;
      }}

      .topbar,
      .layout,
      .inline-fields {{
        display: grid;
      }}

      dl {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        {_editable_title(job)}
        <p class="subhead">{escape(job.company or "Company not set")} · {escape(job.status)}</p>
      </div>
      <nav>
        <a href="/board">Board</a>
        <form method="post" action="/logout">
          <button type="submit">Sign out</button>
        </form>
      </nav>
    </header>

    <div class="layout">
      <div>
        <section>
          <h2>Description</h2>
          {_editable_description(job)}
        </section>
      </div>
      <aside>
        <section>
          <h2>Details</h2>
          <dl>
            {_editable_select("Status", "status", job.status)}
            {_field("Board position", job.board_position)}
            {_editable_text("Company", "company", job.company)}
            {_editable_text("Location", "location", job.location)}
            {_editable_text("Remote policy", "remote_policy", job.remote_policy)}
            {_editable_text("Salary min", "salary_min", job.salary_min)}
            {_editable_text("Salary max", "salary_max", job.salary_max)}
            {_editable_text("Currency", "salary_currency", job.salary_currency)}
            {_editable_text("Source", "source", job.source)}
            {_field("Captured", job.captured_at)}
            {_editable_url("Source URL", "source_url", job.source_url, "Open source")}
            {_editable_url("Apply URL", "apply_url", job.apply_url, "Open apply link")}
          </dl>
        </section>
        <section>
          <h2>Application</h2>
          {_applications(job.applications)}
        </section>
        <section>
          <h2>Artefacts</h2>
          {_artefacts(job.artefacts)}
        </section>
        <section>
          <h2>Upload Artefact</h2>
          {_artefact_form(job)}
        </section>
        <section>
          <h2>Interviews</h2>
          {_interviews(job.interviews)}
        </section>
        <section>
          <h2>Schedule Interview</h2>
          {_schedule_interview_form(job)}
        </section>
        <section>
          <h2>Mark Applied</h2>
          {_mark_applied_form(job)}
        </section>
        <section>
          <h2>Archive</h2>
          {_archive_form(job)}
        </section>
        <section>
          <h2>Unarchive</h2>
          {_unarchive_form(job)}
        </section>
        <section>
          <h2>Add Note</h2>
          {_note_form(job)}
        </section>
        <section>
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
  </main>
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
</body>
</html>"""


@router.get("/jobs/new", response_class=HTMLResponse)
def new_job(
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    _ = current_user
    return HTMLResponse(render_new_job())


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
) -> HTMLResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    return HTMLResponse(render_job_detail(job))


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
