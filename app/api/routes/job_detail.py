from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import DbSession, get_current_user
from app.api.ownership import require_owner
from app.db.models.application import Application
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User
from app.services.applications import mark_job_applied
from app.services.interviews import schedule_interview
from app.services.jobs import (
    create_job_note,
    get_user_job_by_uuid,
    record_job_status_change,
    update_job_board_state,
)

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


def _field(label: str, value: object) -> str:
    return f"""
    <div class="field">
      <dt>{escape(label)}</dt>
      <dd>{escape(_value(value))}</dd>
    </div>
    """


def _timeline_event(event: Communication) -> str:
    occurred_at = event.occurred_at or event.created_at
    notes = f"<p>{escape(event.notes)}</p>" if event.notes else ""
    return f"""
    <li>
      <time>{escape(_value(occurred_at))}</time>
      <strong>{escape(event.subject or event.event_type)}</strong>
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
      <button type="submit">Add note</button>
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


def render_job_detail(job: Job) -> str:
    events = sorted(
        job.communications,
        key=lambda event: event.occurred_at or event.created_at,
        reverse=True,
    )
    salary = "Not set"
    if job.salary_min is not None or job.salary_max is not None:
        low = _value(job.salary_min) if job.salary_min is not None else ""
        high = _value(job.salary_max) if job.salary_max is not None else ""
        currency = job.salary_currency or ""
        salary = f"{currency} {low}-{high}".strip(" -")

    description = (
        f"<pre>{escape(job.description_raw)}</pre>"
        if job.description_raw
        else '<p class="empty">No description captured yet.</p>'
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
    .quick-action-form {{
      display: grid;
      gap: 12px;
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

    pre {{
      font-family: inherit;
      line-height: 1.5;
      margin: 0;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
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
      .layout {{
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
        <h1>{escape(job.title)}</h1>
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
          {description}
        </section>
      </div>
      <aside>
        <section>
          <h2>Details</h2>
          <dl>
            {_field("Status", job.status)}
            {_field("Board position", job.board_position)}
            {_field("Company", job.company)}
            {_field("Location", job.location)}
            {_field("Remote policy", job.remote_policy)}
            {_field("Salary", salary)}
            {_field("Source", job.source)}
            {_field("Captured", job.captured_at)}
            <div class="field">
              <dt>Source URL</dt>
              <dd>{_link("Open source", job.source_url)}</dd>
            </div>
            <div class="field">
              <dt>Apply URL</dt>
              <dd>{_link("Open apply link", job.apply_url)}</dd>
            </div>
          </dl>
        </section>
        <section>
          <h2>Application</h2>
          {_applications(job.applications)}
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
          <h2>Add Note</h2>
          {_note_form(job)}
        </section>
        <section>
          <h2>Timeline</h2>
          {_timeline(events)}
        </section>
      </aside>
    </div>
  </main>
</body>
</html>"""


@router.get("/jobs/{job_uuid}", response_class=HTMLResponse)
def job_detail(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    job = require_owner(get_user_job_by_uuid(db, current_user, job_uuid), current_user)
    return HTMLResponse(render_job_detail(job))


@router.post("/jobs/{job_uuid}/notes", include_in_schema=False)
def create_job_note_form(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    subject: Annotated[str, Form()] = "Note",
    notes: Annotated[str, Form()] = "",
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
