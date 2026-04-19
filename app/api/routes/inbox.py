from datetime import datetime
from html import escape
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import app_header, app_shell_styles
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
        <a class="secondary" href="/inbox/{escape(job.uuid, quote=True)}/review">Review</a>
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

      .actions {{
        width: 100%;
      }}

      .actions > *,
      .actions button,
      .actions a {{
        width: 100%;
      }}
    }}
    {app_shell_styles()}
  </style>
</head>
<body>
  <main>
    {app_header(user, title="Inbox", subtitle="Review captured opportunities before they become active work", active="inbox", actions=(("Paste email", "/inbox/email/new", "paste-email"), ("Add job", "/jobs/new", "add-job")))}
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


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _selected_source_url(job: Job) -> str:
    return job.source_url or job.apply_url or ""


def _provenance_summary(job: Job) -> str:
    parts = [
        f"<li><strong>Source</strong><span>{escape(_source_label(job))}</span></li>",
        f"<li><strong>Confidence</strong><span>{escape(job.intake_confidence.replace('_', ' '))}</span></li>",
        f"<li><strong>Captured</strong><span>{escape(_value(job.captured_at or job.created_at))}</span></li>",
    ]
    if job.email_intake:
        parts.extend(
            [
                f"<li><strong>Email subject</strong><span>{escape(job.email_intake.subject)}</span></li>",
                f"<li><strong>Sender</strong><span>{escape(job.email_intake.sender or 'Not set')}</span></li>",
            ]
        )

    urls = []
    structured_data = job.structured_data or {}
    email_capture = structured_data.get("email_capture")
    if isinstance(email_capture, dict):
        urls = [url for url in email_capture.get("all_urls", []) if isinstance(url, str)]
    capture_data = structured_data.get("capture")
    if isinstance(capture_data, dict):
        raw_url = capture_data.get("source_url")
        urls = [raw_url] if isinstance(raw_url, str) and raw_url else urls

    if urls:
        url_items = "".join(
            f'<li><a href="{escape(url, quote=True)}" target="_blank" rel="noreferrer">{escape(url)}</a></li>'
            for url in urls[:6]
        )
        parts.append(f"<li><strong>Captured links</strong><ol>{url_items}</ol></li>")

    return "<ul>" + "".join(parts) + "</ul>"


def render_inbox_review(user: User, job: Job, *, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    source_url = _selected_source_url(job)
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Review Inbox Item - Application Tracker</title>
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
      max-width: 1120px;
      min-height: 100vh;
      padding: 24px;
    }}

    h1, h2, p {{
      margin: 0;
    }}

    p,
    .hint,
    .meta {{
      color: var(--muted);
      line-height: 1.45;
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .review-layout {{
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
    }}

    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 18px;
    }}

    form {{
      display: grid;
      gap: 14px;
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
      min-height: 320px;
      resize: vertical;
    }}

    .field-grid,
    .actions {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    button,
    .button,
    .secondary {{
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      font: inherit;
      font-weight: 500;
      justify-content: center;
      min-height: 38px;
      padding: 0 14px;
      text-decoration: none;
    }}

    button,
    .button {{
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }}

    .secondary {{
      background: transparent;
      color: var(--accent-strong);
    }}

    .ghost {{
      background: transparent;
      border-color: var(--line);
      color: var(--warn);
    }}

    .provenance ul,
    .provenance ol {{
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 0;
    }}

    .provenance li {{
      display: grid;
      gap: 3px;
      min-width: 0;
    }}

    .provenance strong {{
      font-weight: 500;
    }}

    .provenance span,
    .provenance a {{
      overflow-wrap: anywhere;
    }}

    .error {{
      color: var(--warn);
    }}

    @media (max-width: 800px) {{
      main {{
        padding: 16px;
      }}

      .review-layout,
      .field-grid,
      .actions {{
        grid-template-columns: 1fr;
      }}
    }}
    {app_shell_styles()}
  </style>
</head>
<body>
  <main>
    {app_header(user, title="Review Inbox Item", subtitle="Clean up extracted fields before accepting or dismissing", active="inbox")}
    <div class="review-layout">
      <section>
        <h2>Opportunity fields</h2>
        <p class="hint">These edits update the Inbox candidate only. The item stays in Inbox until you accept or dismiss it.</p>
        <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/review">
          {error_block}
          <label>
            Title
            <input name="title" maxlength="300" required value="{escape(job.title, quote=True)}">
          </label>
          <div class="field-grid">
            <label>
              Company
              <input name="company" maxlength="300" value="{escape(job.company or "", quote=True)}">
            </label>
            <label>
              Location
              <input name="location" maxlength="300" value="{escape(job.location or "", quote=True)}">
            </label>
            <label>
              Source
              <input name="source" maxlength="100" value="{escape(job.source or "", quote=True)}">
            </label>
            <label>
              Source or apply URL
              <input name="source_url" maxlength="2048" value="{escape(source_url, quote=True)}">
            </label>
          </div>
          <label>
            Description
            <textarea name="description_raw">{escape(job.description_raw or "")}</textarea>
          </label>
          <div class="actions">
            <button type="submit">Save review</button>
            <a class="secondary" href="/jobs/{escape(job.uuid, quote=True)}">Open workspace</a>
          </div>
        </form>
      </section>
      <aside class="provenance">
        <section>
          <h2>Captured context</h2>
          {_provenance_summary(job)}
        </section>
        <section>
          <h2>Decision</h2>
          <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/accept">
            <button type="submit">Accept to Interested</button>
          </form>
          <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/dismiss">
            <button class="ghost" type="submit">Dismiss and archive</button>
          </form>
          <a class="secondary" href="/inbox">Back to Inbox</a>
        </section>
      </aside>
    </div>
  </main>
</body>
</html>"""
    )


def _apply_inbox_review_update(
    db: DbSession,
    job: Job,
    *,
    title: str,
    company: str,
    location: str,
    source: str,
    source_url: str,
    description_raw: str,
) -> None:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("Title is required")

    before = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source": job.source,
        "source_url": job.source_url,
        "apply_url": job.apply_url,
        "description_raw": job.description_raw,
    }

    cleaned_source_url = _clean_optional(source_url)
    job.title = cleaned_title
    job.company = _clean_optional(company)
    job.location = _clean_optional(location)
    job.source = _clean_optional(source)
    job.source_url = cleaned_source_url
    job.apply_url = cleaned_source_url
    job.description_raw = _clean_optional(description_raw)
    job.description_clean = _clean_optional(description_raw)

    changed = [
        label
        for field_name, label in (
            ("title", "title"),
            ("company", "company"),
            ("location", "location"),
            ("source", "source"),
            ("source_url", "source/apply URL"),
            ("description_raw", "description"),
        )
        if getattr(job, field_name) != before[field_name]
    ]
    if job.apply_url != before["apply_url"] and "source/apply URL" not in changed:
        changed.append("source/apply URL")
    if changed:
        create_job_note(
            db,
            job,
            subject="Inbox enriched",
            notes=f"Updated fields before review decision: {', '.join(changed)}.",
        )


@router.get("/inbox/{job_uuid}/review", response_class=HTMLResponse, include_in_schema=False)
def review_inbox_job(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return render_inbox_review(current_user, _get_inbox_job(db, current_user, job_uuid))


@router.post(
    "/inbox/{job_uuid}/review",
    response_model=None,
    response_class=HTMLResponse,
    include_in_schema=False,
)
def update_inbox_review(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    title: Annotated[str, Form()],
    company: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "",
    source_url: Annotated[str, Form()] = "",
    description_raw: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    job = _get_inbox_job(db, current_user, job_uuid)
    try:
        _apply_inbox_review_update(
            db,
            job,
            title=title,
            company=company,
            location=location,
            source=source,
            source_url=source_url,
            description_raw=description_raw,
        )
    except ValueError as exc:
        return render_inbox_review(current_user, job, error=str(exc))

    db.commit()
    return RedirectResponse(
        url=f"/inbox/{escape(job.uuid, quote=True)}/review",
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    {app_shell_styles()}
  </style>
</head>
<body>
  <main>
    {app_header(user, title="Paste email", subtitle="Add an interesting job email to Inbox", active="inbox")}
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
