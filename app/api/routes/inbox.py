from datetime import datetime
from html import escape
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
from app.db.models.email_intake import EmailIntake
from app.db.models.job import Job
from app.db.models.user import User
from app.services.email_intake import create_email_inbox_candidate
from app.services.jobs import BOARD_STATUSES, create_job_note, update_job_board_state

router = APIRouter(tags=["inbox"])


class EmailCaptureRequest(BaseModel):
    subject: str = Field(max_length=500)
    sender: str | None = Field(default=None, max_length=500)
    received_at: datetime | None = None
    body_text: str | None = None
    body_html: str | None = None


class EmailCaptureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email_intake_uuid: str
    job_uuid: str
    created: bool
    intake_state: str


def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _list_inbox_jobs(db: DbSession, user: User) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(
                Job.owner_user_id == user.id,
                Job.intake_state == "needs_review",
                Job.status != "archived",
            )
            .order_by(Job.captured_at.desc().nullslast(), Job.created_at.desc())
        )
    )


def _get_inbox_job(db: DbSession, user: User, job_uuid: str) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.uuid == job_uuid,
            Job.owner_user_id == user.id,
            Job.intake_state == "needs_review",
            Job.status != "archived",
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inbox job not found")
    return job


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


def _source_label(job: Job) -> str:
    if job.intake_source == "email_capture":
        return "Email capture"
    if job.source_url:
        hostname = urlparse(job.source_url).hostname
        if hostname:
            return hostname.removeprefix("www.")
    return job.intake_source.replace("_", " ")


def _source_action(job: Job) -> str:
    url = job.source_url or job.apply_url
    if not url:
        return '<span class="meta">No source link captured</span>'
    return f'<a class="external-link" href="{escape(url, quote=True)}" target="_blank" rel="noreferrer">Open source ↗</a>'


def _job_card(job: Job) -> str:
    source = _source_label(job)
    confidence = job.intake_confidence.replace("_", " ")
    return f"""
    <article class="inbox-card">
      <div>
        <p class="meta">{escape(source)} · {escape(confidence)} confidence</p>
        <h2><a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></h2>
        <p>{escape(job.company or "Company not set")} · {escape(job.location or "Location not set")}</p>
        <p>{_source_action(job)}</p>
        <p class="meta">Captured {_value(job.captured_at or job.created_at)}</p>
      </div>
      <div class="actions">
        <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/accept">
          <button type="submit">Accept</button>
        </form>
        <a class="secondary" href="/jobs/{escape(job.uuid, quote=True)}">Review</a>
        <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/dismiss">
          <button class="ghost" type="submit">Dismiss</button>
        </form>
      </div>
    </article>
    """


def render_inbox(user: User, jobs: list[Job]) -> HTMLResponse:
    cards = "\n".join(_job_card(job) for job in jobs)
    if not cards:
        cards = """
        <section class="empty-state">
          <h2>Inbox is clear</h2>
          <p>Captured and recommended jobs that need review will appear here before they move into active work.</p>
          <div class="empty-actions">
            <a class="button" href="/inbox/email/new">Paste email</a>
            <a class="secondary" href="/api/capture/bookmarklet">Set up capture</a>
          </div>
        </section>
        """
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Inbox - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f9f9f7;
      --panel: #ffffff;
      --ink: #111111;
      --muted: #5f5e5a;
      --line: rgba(0, 0, 0, 0.10);
      --accent: #4f67e4;
      --accent-strong: #2d3a9a;
      --warn: #a43d2b;
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
      max-width: 980px;
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

    nav,
    .actions {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    h1, h2, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
    }}

    h2 {{
      font-size: 1.1rem;
      line-height: 1.3;
    }}

    p,
    .meta {{
      color: var(--muted);
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .inbox-list {{
      display: grid;
      gap: 12px;
    }}

    .inbox-card,
    .empty-state {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 16px;
    }}

    .inbox-card {{
      grid-template-columns: minmax(0, 1fr) auto;
    }}

    .inbox-card > div {{
      min-width: 0;
    }}

    .source-url {{
      overflow-wrap: anywhere;
      word-break: break-word;
    }}

    button,
    .button,
    .secondary,
    nav a {{
      border: 1px solid var(--line);
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      font: inherit;
      font-weight: 500;
      padding: 8px 10px;
      text-decoration: none;
    }}

    button,
    .button {{
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }}

    .secondary,
    nav a {{
      background: transparent;
      color: var(--accent-strong);
    }}

    .ghost {{
      background: transparent;
      border-color: var(--line);
      color: var(--warn);
    }}

    @media (max-width: 760px) {{
      main {{
        padding: 16px;
      }}

      .topbar,
      .inbox-card {{
        align-items: start;
        display: grid;
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        <h1>Inbox</h1>
        <p>{escape(user.email)} · Review captured opportunities before they become active work</p>
      </div>
      <nav>
        <a href="/focus">Focus</a>
        <a href="/board">Board</a>
        <a href="/jobs/new">Add job</a>
        <a href="/inbox/email/new">Paste email</a>
        <a href="/api/capture/bookmarklet">Capture</a>
        <a href="/settings">Settings</a>
        {'<a href="/admin">Admin</a>' if user.is_admin else ""}
      </nav>
    </header>
    <div class="inbox-list">
      {cards}
    </div>
  </main>
</body>
</html>"""
    )


@router.get("/inbox", response_class=HTMLResponse, include_in_schema=False)
def inbox(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return render_inbox(current_user, _list_inbox_jobs(db, current_user))


def render_email_capture_form(user: User, *, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Paste email - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f9f9f7;
      --panel: #ffffff;
      --ink: #111111;
      --muted: #5f5e5a;
      --line: rgba(0, 0, 0, 0.10);
      --accent: #4f67e4;
      --accent-strong: #2d3a9a;
      --warn: #a43d2b;
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
      max-width: 860px;
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
      flex-wrap: wrap;
      gap: 10px;
    }}

    h1, h2, p {{
      margin: 0;
    }}

    p,
    .hint {{
      color: var(--muted);
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    form {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 18px;
    }}

    label {{
      display: grid;
      font-weight: 500;
      gap: 6px;
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
      min-height: 160px;
      resize: vertical;
    }}

    button,
    nav a {{
      border: 1px solid var(--line);
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      font: inherit;
      font-weight: 500;
      padding: 8px 10px;
      text-decoration: none;
    }}

    button {{
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
      justify-self: start;
    }}

    nav a {{
      background: transparent;
      color: var(--accent-strong);
    }}

    .error {{
      color: var(--warn);
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        <h1>Paste email</h1>
        <p>{escape(user.email)} · Add an interesting job email to Inbox</p>
      </div>
      <nav>
        <a href="/inbox">Inbox</a>
        <a href="/focus">Focus</a>
        <a href="/board">Board</a>
      </nav>
    </header>
    <form method="post" action="/inbox/email">
      {error_block}
      <label>
        Subject
        <input name="subject" maxlength="500" required>
      </label>
      <label>
        Sender
        <input name="sender" maxlength="500" placeholder="jobs@example.com">
      </label>
      <label>
        Received
        <input name="received_at" type="datetime-local">
      </label>
      <label>
        Plain text body
        <textarea name="body_text" placeholder="Paste the email body here"></textarea>
      </label>
      <label>
        HTML body
        <textarea name="body_html" placeholder="Optional raw HTML"></textarea>
      </label>
      <p class="hint">The first meaningful job URL becomes the source link. Raw email content is preserved for later review and provider integrations.</p>
      <button type="submit">Add to Inbox</button>
    </form>
  </main>
</body>
</html>"""
    )


def _parse_form_datetime(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    return datetime.fromisoformat(stripped)


def _email_response(email_intake: EmailIntake, job: Job, *, created: bool) -> EmailCaptureResponse:
    return EmailCaptureResponse(
        email_intake_uuid=email_intake.uuid,
        job_uuid=job.uuid,
        created=created,
        intake_state=job.intake_state,
    )


@router.get("/inbox/email/new", response_class=HTMLResponse, include_in_schema=False)
def email_capture_form(
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return render_email_capture_form(current_user)


@router.post("/inbox/email", response_model=None, include_in_schema=False)
def submit_email_capture_form(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    subject: Annotated[str, Form()],
    sender: Annotated[str, Form()] = "",
    received_at: Annotated[str, Form()] = "",
    body_text: Annotated[str, Form()] = "",
    body_html: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    if not subject.strip():
        return render_email_capture_form(current_user, error="Subject is required")
    if not body_text.strip() and not body_html.strip():
        return render_email_capture_form(current_user, error="Paste the email body")

    try:
        received = _parse_form_datetime(received_at)
    except ValueError:
        return render_email_capture_form(current_user, error="Received must be a valid date and time")

    create_email_inbox_candidate(
        db,
        current_user,
        subject=subject,
        sender=sender,
        received_at=received,
        body_text=body_text,
        body_html=body_html,
    )
    db.commit()
    return RedirectResponse(url="/inbox", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/inbox/email-captures", response_model=EmailCaptureResponse)
def create_email_capture(
    payload: EmailCaptureRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> EmailCaptureResponse:
    if not payload.subject.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subject is required")
    if not (payload.body_text and payload.body_text.strip()) and not (
        payload.body_html and payload.body_html.strip()
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email body is required")

    email_intake, job, created = create_email_inbox_candidate(
        db,
        current_user,
        subject=payload.subject,
        sender=payload.sender,
        received_at=payload.received_at,
        body_text=payload.body_text,
        body_html=payload.body_html,
    )
    db.commit()
    return _email_response(email_intake, job, created=created)


@router.post("/inbox/{job_uuid}/accept", include_in_schema=False)
def accept_inbox_job(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    job = _get_inbox_job(db, current_user, job_uuid)
    target_status = "interested"
    if target_status not in BOARD_STATUSES:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    job.intake_state = "accepted"
    update_job_board_state(
        job,
        status=target_status,
        board_position=_next_board_position(db, current_user, target_status),
    )
    create_job_note(db, job, subject="Inbox accepted", notes="Accepted from Inbox.")
    db.commit()
    return RedirectResponse(url="/inbox", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/inbox/{job_uuid}/dismiss", include_in_schema=False)
def dismiss_inbox_job(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    job = _get_inbox_job(db, current_user, job_uuid)
    job.intake_state = "dismissed"
    update_job_board_state(job, status="archived")
    create_job_note(db, job, subject="Inbox dismissed", notes="Dismissed from Inbox.")
    db.commit()
    return RedirectResponse(url="/inbox", status_code=status.HTTP_303_SEE_OTHER)
