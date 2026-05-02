from datetime import datetime
from html import escape
from typing import Annotated
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import compact_content_rhythm_styles, render_shell_page
from app.db.models.ai_output import AiOutput
from app.db.models.email_intake import EmailIntake
from app.db.models.job import Job
from app.db.models.user import User
from app.services.ai import AiExecutionError, generate_job_ai_output
from app.services.email_intake import create_email_inbox_candidate, create_email_inbox_candidates
from app.services.jobs import BOARD_STATUSES, create_job_note, update_job_board_state
from app.services.markdown import render_markdown_blocks
from app.services.profiles import get_user_profile

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
    job_uuids: list[str] = Field(default_factory=list)
    candidate_count: int = 1
    created_count: int = 0


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


def _review_attention_items(job: Job) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    if not job.company:
        items.append(("Company missing", "Add the employer before accepting.", "warn"))
    if not job.location:
        items.append(("Location missing", "Add location or mark remote when known.", "warn"))
    if not (job.source_url or job.apply_url):
        items.append(("Source link missing", "Add a recoverable source or apply link if one exists.", "warn"))
    if not job.description_raw:
        items.append(("Description missing", "Add enough context to judge fit later.", "warn"))
    if job.intake_confidence in {"low", "unknown"}:
        items.append(
            (
                f"{job.intake_confidence.replace('_', ' ').title()} confidence",
                "Review extracted fields before moving this into active work.",
                "accent",
            )
        )
    return items


def _review_readiness_panel(job: Job) -> str:
    items = _review_attention_items(job)
    if not items:
        return """
        <section class="page-panel soft review-readiness" data-ui-component="review-readiness">
          <div class="panel-header">
            <div>
              <p class="panel-micro">Review readiness</p>
              <h2>Ready for decision</h2>
            </div>
            <span class="status-pill success">Complete fields</span>
          </div>
          <p class="hint">Core fields are present. Accept or dismiss when the opportunity quality is clear.</p>
        </section>
        """
    rendered = "".join(
        "<li>"
        f'<span class="status-pill {escape(tone, quote=True)}">{escape(title)}</span>'
        f"<p>{escape(detail)}</p>"
        "</li>"
        for title, detail, tone in items
    )
    return f"""
    <section class="page-panel soft review-readiness" data-ui-component="review-readiness">
      <div class="panel-header">
        <div>
          <p class="panel-micro">Review readiness</p>
          <h2>Needs cleanup before accept</h2>
        </div>
        <span class="status-pill warn">{len(items)} checks</span>
      </div>
      <ul class="review-readiness-list">
        {rendered}
      </ul>
    </section>
    """


def _job_card(job: Job) -> str:
    source = _source_label(job)
    confidence = job.intake_confidence.replace("_", " ")
    captured = _value(job.captured_at or job.created_at)
    attention_count = len(_review_attention_items(job))
    attention = (
        f'<span class="status-pill warn">{attention_count} cleanup checks</span>'
        if attention_count
        else '<span class="status-pill success">Ready to decide</span>'
    )
    return f"""
    <article class="inbox-card">
      <div class="inbox-card-body">
        <div class="inbox-card-title">
          <h2><a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></h2>
          {attention}
        </div>
        <div class="inbox-card-meta">
          <span>{escape(job.company or "Company not set")}</span>
          <span>{escape(job.location or "Location not set")}</span>
          <span>{escape(source)}</span>
          <span>{escape(confidence)} confidence</span>
          <span>Captured {escape(captured)}</span>
        </div>
      </div>
      <div class="inbox-card-foot">
        <div class="inbox-card-actions">
          <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/accept">
            <button class="inbox-act accept" type="submit">Accept</button>
          </form>
          <a class="inbox-act review" href="/inbox/{escape(job.uuid, quote=True)}/review">Review</a>
          <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/dismiss">
            <button class="inbox-act dismiss" type="submit">Dismiss</button>
          </form>
        </div>
        {_source_action(job)}
      </div>
    </article>
    """


def render_inbox(user: User, jobs: list[Job]) -> HTMLResponse:
    cards = "\n".join(_job_card(job) for job in jobs)
    if not cards:
        cards = """
        <section class="page-panel soft empty-state">
          <div class="panel-header">
            <div>
              <p class="panel-micro">Clear queue</p>
              <h2>Inbox is clear</h2>
            </div>
            <span class="status-pill success">Up to date</span>
          </div>
          <p>Captured and recommended jobs that need review will appear here before they move into active work.</p>
          <div class="empty-actions">
            <a class="button" href="/inbox/email/new">Paste email</a>
            <a class="secondary" href="/api/capture/bookmarklet">Set up capture</a>
          </div>
        </section>
        """
    extra_styles = compact_content_rhythm_styles() + """
    :root { --warn: #a43d2b; }
    .inbox-list { display: grid; gap: 12px; }
    .inbox-card {
      align-items: start;
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 18px;
    }
    .inbox-card-main {
      display: grid;
      gap: 10px;
      min-width: 0;
    }
    .inbox-card-title {
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
      min-width: 0;
    }
    .inbox-card-title h2 {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .inbox-card-meta,
    .inbox-card-summary {
      align-items: center;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
    }
    .inbox-card-meta span:not(:last-child)::after {
      color: var(--soft-text);
      content: "·";
      margin-left: 12px;
    }
    .inbox-card-summary .external-link {
      white-space: nowrap;
    }
    .meta { color: var(--muted); }
    .inbox-card-actions {
      align-items: stretch;
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 120px;
    }
    .inbox-card-actions form,
    .inbox-card-actions button,
    .inbox-card-actions a {
      width: 100%;
    }
    .inbox-aside { display: grid; gap: 18px; }
    .queue-count {
      align-items: baseline;
      display: flex;
      gap: 8px;
    }
    .queue-count strong {
      font-size: 2rem;
      letter-spacing: -0.02em;
      line-height: 1;
    }
    .queue-count span {
      color: var(--muted);
    }
    .tip-list {
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .tip-list li {
      border-left: 3px solid rgba(255,255,255,0.28);
      padding-left: 10px;
    }
    .inbox-aside .mobile-stack {
      margin-top: 4px;
    }
    @media (max-width: 760px) {
      .inbox-card {
        grid-template-columns: 1fr;
      }
      .inbox-card-title,
      .inbox-card-meta,
      .inbox-card-summary {
        align-items: start;
        flex-direction: column;
      }
      .inbox-card-meta span::after {
        display: none;
      }
      .inbox-card-actions {
        width: 100%;
      }
    }
    """
    aside = f"""
    <div class="inbox-aside">
      <section class="page-panel soft">
        <div class="panel-header">
          <div>
            <h2>Queue</h2>
          </div>
          <span class="status-pill accent">Inbox</span>
        </div>
        <div class="queue-count"><strong>{len(jobs)}</strong><span>queued</span></div>
        <p>Review only what looks worth effort, then accept, clean up, or dismiss.</p>
        <div class="mobile-stack">
          <a class="secondary" href="/api/capture/bookmarklet">Capture setup</a>
        </div>
      </section>
      <section class="page-panel emphasis">
        <div class="panel-header">
          <div>
            <h2>Review habit</h2>
          </div>
        </div>
        <ul class="tip-list">
          <li>Prefer Review when the capture needs cleanup before acceptance.</li>
          <li>Keep the source/apply URL accurate so external follow-up stays recoverable.</li>
          <li>Dismiss weak opportunities so Board and Focus stay calm.</li>
        </ul>
      </section>
    </div>
    """
    body = f"""
    <div class="inbox-list">
      {cards}
    </div>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Inbox",
            title="Inbox",
            subtitle="",
            active="inbox",
            actions=(("Paste email", "/inbox/email/new", "paste-email"), ("Add job", "/jobs/new", "add-job")),
            body=body,
            aside=aside,
            container="split",
            extra_styles=extra_styles,
        )
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


def _ai_outputs_panel(outputs: list[AiOutput]) -> str:
    if not outputs:
        return '<p class="empty">No AI output yet. Generate a fit summary or recommendation when you want help deciding whether this role is worth effort.</p>'
    cards = []
    for output in outputs:
        provider = output.model_name or output.provider or "AI"
        cards.append(
            f"""
            <article class="ai-output-card">
              <div class="card-header">
                <div>
                  <p class="panel-micro">AI output</p>
                  <h3>{escape(output.title or output.output_type.replace('_', ' ').title())}</h3>
                </div>
                {_ai_badge(output.output_type)}
              </div>
              <p class="meta">From {escape(provider)}</p>
              {render_markdown_blocks(output.body, class_name="ai-markdown")}
            </article>
            """
        )
    return '<div class="ai-output-list">' + "".join(cards) + "</div>"


def _ai_actions(job: Job) -> str:
    return f"""
    <div class="ai-action-stack">
      <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/ai-outputs">
        <input type="hidden" name="output_type" value="fit_summary">
        <button type="submit">Generate fit summary</button>
      </form>
      <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/ai-outputs">
        <input type="hidden" name="output_type" value="recommendation">
        <button class="secondary" type="submit">Suggest next step</button>
      </form>
      <p class="meta">AI only creates visible review notes. It does not accept, dismiss, or edit the candidate automatically.</p>
    </div>
    """


def _flash_message(message: str, *, tone: str) -> str:
    return f'<section class="page-panel flash flash-{escape(tone, quote=True)}"><p>{escape(message)}</p></section>'


def _inbox_review_redirect(job_uuid: str, *, ai_status: str | None = None, ai_error: str | None = None) -> str:
    params = []
    if ai_status:
        params.append(f"ai_status={quote(ai_status)}")
    if ai_error:
        params.append(f"ai_error={quote(ai_error)}")
    if not params:
        return f"/inbox/{quote(job_uuid)}/review"
    return f"/inbox/{quote(job_uuid)}/review?" + "&".join(params)


def render_inbox_review(
    user: User,
    job: Job,
    *,
    error: str | None = None,
    ai_status: str | None = None,
    ai_error: str | None = None,
) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    source_url = _selected_source_url(job)
    ai_outputs = [
        output
        for output in sorted(job.ai_outputs, key=lambda item: item.updated_at, reverse=True)
        if output.status == "active"
    ]
    flash_parts = []
    if ai_status:
        flash_parts.append(_flash_message(ai_status, tone="success"))
    if ai_error:
        flash_parts.append(_flash_message(ai_error, tone="error"))
    extra_styles = compact_content_rhythm_styles() + """
    :root { --warn: #a43d2b; }
    .hint, .meta { color: var(--muted); line-height: 1.45; }
    form { display: grid; gap: 14px; }
    label { gap: 6px; }
    textarea { min-height: 320px; resize: vertical; }
    .field-grid, .actions {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .provenance ul, .provenance ol {
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .provenance li { display: grid; gap: 3px; min-width: 0; }
    .provenance strong { font-weight: 500; }
    .provenance span, .provenance a { overflow-wrap: anywhere; }
    .error { color: var(--warn); }
    .flash { padding: 14px 18px; }
    .flash-success {
      background: rgba(59, 167, 134, 0.10);
      border-color: rgba(59, 167, 134, 0.28);
    }
    .flash-error {
      background: rgba(226, 91, 76, 0.10);
      border-color: rgba(226, 91, 76, 0.28);
    }
    .ai-output-list { display: grid; gap: 12px; }
    .ai-output-card {
      background: linear-gradient(180deg, rgba(232,239,255,0.96), rgba(244,247,255,0.98));
      border: 1px solid var(--ai-line);
      border-radius: var(--radius-lg);
      display: grid;
      gap: 10px;
      padding: 16px;
    }
    .ai-markdown { display: grid; gap: 10px; }
    .ai-markdown h2, .ai-markdown h3, .ai-markdown h4,
    .ai-markdown p { margin: 0; }
    .ai-markdown ul {
      display: grid;
      gap: 8px;
      list-style: disc;
      margin: 0;
      padding-left: 22px;
    }
    .ai-markdown li { border-left: 0; padding-left: 0; }
    .ai-action-stack { display: grid; gap: 10px; }
    .review-readiness-list {
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .review-readiness-list li {
      border-left: 3px solid var(--line);
      display: grid;
      gap: 6px;
      padding-left: 10px;
    }
    .review-readiness-list p { margin: 0; }
    @media (max-width: 800px) {
      .field-grid, .actions { grid-template-columns: 1fr; }
    }
    """
    body = f"""
    {"".join(flash_parts)}
    {_review_readiness_panel(job)}
    <section class="page-panel">
      <div class="panel-header">
        <div>
          <p class="panel-micro">Candidate fields</p>
          <h2>Opportunity fields</h2>
        </div>
        <span class="status-pill accent">Editable before accept</span>
      </div>
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
    <section class="page-panel ai">
      <div class="panel-header">
        <div>
          <p class="panel-micro">Visible AI output</p>
          <h2>Review guidance</h2>
        </div>
      </div>
      {_ai_outputs_panel(ai_outputs)}
    </section>
    """
    aside = f"""
    <aside class="provenance">
      <section class="page-panel soft">
        <div class="panel-header">
          <div>
            <p class="panel-micro">Generate guidance</p>
            <h2>AI review support</h2>
          </div>
        </div>
        {_ai_actions(job)}
      </section>
      <section class="page-panel soft">
        <div class="panel-header">
          <div>
            <p class="panel-micro">Captured context</p>
            <h2>Provenance</h2>
          </div>
        </div>
        {_provenance_summary(job)}
      </section>
      <section class="page-panel emphasis">
        <div class="panel-header">
          <div>
            <p class="panel-micro">Decision</p>
            <h2>Promote or dismiss</h2>
          </div>
        </div>
        <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/accept">
          <button type="submit">Accept to Interested</button>
        </form>
        <form method="post" action="/inbox/{escape(job.uuid, quote=True)}/dismiss">
          <button class="ghost" type="submit">Dismiss and archive</button>
        </form>
        <a class="secondary" href="/inbox">Back to Inbox</a>
      </section>
    </aside>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Review Inbox Item",
            title="Review Inbox Item",
            subtitle="Clean up extracted fields before accepting or dismissing",
            active="inbox",
            body=body,
            aside=aside,
            kicker="Review surface",
            container="workspace",
            extra_styles=extra_styles,
        )
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
    ai_status: Annotated[str | None, Query()] = None,
    ai_error: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    return render_inbox_review(
        current_user,
        _get_inbox_job(db, current_user, job_uuid),
        ai_status=ai_status,
        ai_error=ai_error,
    )


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


@router.post("/inbox/{job_uuid}/ai-outputs", include_in_schema=False)
def create_inbox_ai_output(
    job_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    output_type: Annotated[str, Form()] = "fit_summary",
) -> RedirectResponse:
    job = _get_inbox_job(db, current_user, job_uuid)
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
            url=_inbox_review_redirect(job.uuid, ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    db.commit()
    return RedirectResponse(
        url=_inbox_review_redirect(job.uuid, ai_status="AI output generated"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def render_email_capture_form(user: User, *, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    extra_styles = compact_content_rhythm_styles() + """
    :root { --warn: #a43d2b; }
    .hint { color: var(--muted); }
    form[action="/inbox/email"] {
      background: var(--panel);
      border: 0.5px solid var(--line);
      border-radius: 10px;
      display: grid;
      gap: 14px;
      padding: 18px;
    }
    label { gap: 6px; }
    input, textarea {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }
    textarea { min-height: 160px; resize: vertical; }
    form[action="/inbox/email"] button[type="submit"] {
      background: var(--accent);
      border: 0.5px solid var(--accent);
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      display: inline-flex;
      font: inherit;
      font-weight: 500;
      justify-self: start;
      padding: 8px 10px;
    }
    .error { color: var(--warn); }
    """
    body = f"""
    <section class="page-panel">
      <div class="panel-header">
        <div>
          <p class="panel-micro">Manual intake</p>
          <h2>Paste a recruiter or job-board email</h2>
        </div>
        <span class="status-pill accent">Inbox first</span>
      </div>
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
    </section>
    """
    aside = """
    <section class="page-panel emphasis">
      <div class="panel-header">
        <div>
          <p class="panel-micro">Why start here</p>
          <h2>Email belongs in Inbox first</h2>
        </div>
      </div>
      <p>Paste the interesting signal, then review the extracted candidate before it becomes active work. This keeps provenance visible and the board clean.</p>
    </section>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Paste email",
            title="Paste email",
            subtitle="",
            active="inbox",
            body=body,
            aside=aside,
            container="workspace",
            extra_styles=extra_styles,
        )
    )


def _parse_form_datetime(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    return datetime.fromisoformat(stripped)


def _email_response(
    email_intake: EmailIntake,
    jobs: list[Job],
    *,
    created_count: int,
) -> EmailCaptureResponse:
    first_job = jobs[0]
    return EmailCaptureResponse(
        email_intake_uuid=email_intake.uuid,
        job_uuid=first_job.uuid,
        created=created_count > 0,
        intake_state=first_job.intake_state,
        job_uuids=[job.uuid for job in jobs],
        candidate_count=len(jobs),
        created_count=created_count,
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

    email_intake, jobs, created_count = create_email_inbox_candidates(
        db,
        current_user,
        subject=payload.subject,
        sender=payload.sender,
        received_at=payload.received_at,
        body_text=payload.body_text,
        body_html=payload.body_html,
    )
    db.commit()
    return _email_response(email_intake, jobs, created_count=created_count)


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
