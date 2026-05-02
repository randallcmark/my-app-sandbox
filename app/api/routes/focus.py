from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import render_shell_page
from app.db.models.ai_output import AiOutput
from app.db.models.artefact import Artefact
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User
from app.db.models.user_profile import UserProfile
from app.services.ai import AiExecutionError, generate_job_ai_output
from app.services.artefacts import list_due_artefact_followups
from app.services.markdown import render_markdown_blocks
from app.services.profiles import get_user_profile

router = APIRouter(tags=["focus"])

ACTIVE_STATUSES = ("interested", "preparing", "applied", "interviewing", "offer")


# ── Tiny icon helper (same convention as board/inbox) ────────────────────────

def _icon(path: str, *, w: int = 14, h: int = 14) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 20 20" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{path}</svg>'
    )


_ICO_FOLLOWUP   = _icon('<circle cx="10" cy="10" r="8"/><polyline points="10 5.5 10 10 13 12.5"/>')
_ICO_ARTEFACT   = _icon('<path d="M4 2h8l4 4v13a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z"/><polyline points="12 2 12 6 16 6"/>')
_ICO_STALE      = _icon('<path d="M10 2a8 8 0 100 16A8 8 0 0010 2z"/><line x1="10" y1="6" x2="10" y2="10"/><line x1="10" y1="13.5" x2="10" y2="14"/>')
_ICO_INTERVIEW  = _icon('<rect x="3" y="4" width="14" height="13" rx="1.5"/><line x1="3" y1="8" x2="17" y2="8"/><line x1="7" y1="2" x2="7" y2="5"/><line x1="13" y1="2" x2="13" y2="5"/>')
_ICO_NACTION    = _icon('<circle cx="10" cy="10" r="8"/><line x1="10" y1="6" x2="10" y2="10"/><line x1="13" y1="13" x2="10" y2="10"/>')
_ICO_PROSPECT   = _icon('<polygon points="10 2 12.5 7.5 18.5 8.2 14 12.5 15.4 18.5 10 15.3 4.6 18.5 6 12.5 1.5 8.2 7.5 7.5"/>')
_ICO_ACTIVE     = _icon('<rect x="2" y="2" width="6" height="16" rx="1.5"/><rect x="12" y="2" width="6" height="10" rx="1.5"/>')
_ICO_NUDGE      = _icon('<path d="M10 2l2 6h6l-5 3.5 2 6L10 14l-5 3.5 2-6L2 8h6z"/>')
_ICO_EXTERNAL   = _icon('<path d="M9 3H4a1 1 0 00-1 1v12a1 1 0 001 1h12a1 1 0 001-1v-5"/><polyline points="14 3 17 3 17 6"/><line x1="10" y1="10" x2="17" y2="3"/>')
_ICO_SETTINGS   = _icon('<circle cx="10" cy="10" r="2.5"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.9 4.9l1.4 1.4M13.7 13.7l1.4 1.4M4.9 15.1l1.4-1.4M13.7 6.3l1.4-1.4"/>')
_ICO_CHEVRON    = _icon('<polyline points="5 8 10 13 15 8"/>', w=12, h=12)
_ICO_CHECK      = _icon('<polyline points="3 10 8 15 17 5"/>')


# ── Data helpers ─────────────────────────────────────────────────────────────

def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%b %-d, %Y")
    return str(value)


def _value_time(value: datetime | None) -> str:
    if value is None:
        return "Not set"
    return value.strftime("%b %-d · %H:%M")


def _profile_is_empty(profile: UserProfile | None) -> bool:
    if profile is None:
        return True
    return not any(
        (
            profile.target_roles,
            profile.target_locations,
            profile.remote_preference,
            profile.salary_min,
            profile.salary_max,
            profile.preferred_industries,
            profile.excluded_industries,
            profile.constraints,
            profile.urgency,
            profile.positioning_notes,
        )
    )


def _format_salary_goal(value: Decimal | None, currency: str | None) -> str:
    if value is None:
        return ""
    rounded_thousands = int((value / Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    amount = f"{rounded_thousands}K"
    if currency:
        return f"{currency} {amount}"
    return amount


def _list_due_followups(db: DbSession, user: User, *, now: datetime) -> list[Communication]:
    return list(
        db.scalars(
            select(Communication)
            .join(Job)
            .where(
                Communication.owner_user_id == user.id,
                Communication.follow_up_at.is_not(None),
                Communication.follow_up_at <= now,
                Job.status != "archived",
            )
            .order_by(Communication.follow_up_at, Communication.created_at)
            .limit(6)
        )
    )


def _list_stale_jobs(db: DbSession, user: User, *, now: datetime) -> list[Job]:
    stale_before = now - timedelta(days=7)
    return list(
        db.scalars(
            select(Job)
            .where(
                Job.owner_user_id == user.id,
                Job.status.in_(ACTIVE_STATUSES),
                Job.updated_at <= stale_before,
            )
            .order_by(Job.updated_at, Job.created_at)
            .limit(6)
        )
    )


def _list_recent_jobs(db: DbSession, user: User) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(
                Job.owner_user_id == user.id,
                Job.intake_state != "needs_review",
                Job.status.in_(("saved", "interested")),
            )
            .order_by(Job.created_at.desc())
            .limit(6)
        )
    )


def _list_upcoming_interviews(db: DbSession, user: User, *, now: datetime) -> list[InterviewEvent]:
    return list(
        db.scalars(
            select(InterviewEvent)
            .join(Job)
            .where(
                InterviewEvent.owner_user_id == user.id,
                InterviewEvent.scheduled_at.is_not(None),
                InterviewEvent.scheduled_at >= now,
                Job.status != "archived",
            )
            .order_by(InterviewEvent.scheduled_at, InterviewEvent.created_at)
            .limit(6)
        )
    )


def _count_active_jobs(db: DbSession, user: User) -> int:
    return (
        db.scalar(
            select(func.count(Job.id)).where(
                Job.owner_user_id == user.id,
                Job.status.in_(ACTIVE_STATUSES),
            )
        )
        or 0
    )


def _list_jobs_with_no_next_action(db: DbSession, user: User) -> list[Job]:
    subq = (
        select(Communication.job_id)
        .where(
            Communication.owner_user_id == user.id,
            Communication.follow_up_at.is_not(None),
        )
        .scalar_subquery()
    )
    return list(
        db.scalars(
            select(Job)
            .where(
                Job.owner_user_id == user.id,
                Job.status.in_(ACTIVE_STATUSES),
                Job.id.not_in(subq),
            )
            .order_by(Job.updated_at, Job.created_at)
            .limit(8)
        )
    )


# ── Item renderers ────────────────────────────────────────────────────────────

def _job_link(job: Job) -> str:
    return f'<a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a>'


def _status_dot(status_val: str) -> str:
    cls = {
        "interested": "dot-amber",
        "preparing": "dot-accent",
        "applied": "dot-accent",
        "interviewing": "dot-success",
        "offer": "dot-success",
        "saved": "dot-muted",
        "rejected": "dot-danger",
        "archived": "dot-muted",
    }.get(status_val, "dot-muted")
    return f'<span class="status-dot {cls}" title="{escape(status_val)}"></span>'


def _followup_item(event: Communication) -> str:
    when = _value(event.follow_up_at)
    subject = event.subject or event.notes or "Follow up"
    job = event.job
    return f"""
    <li class="focus-row">
      <span class="row-when urgent">{_ICO_FOLLOWUP}{escape(when)}</span>
      <span class="row-title">{_status_dot(job.status)}{_job_link(job)}</span>
      <span class="row-meta">{escape(job.company or "—")}</span>
      <span class="row-subject">{escape(subject)}</span>
    </li>
    """


def _stale_item(job: Job) -> str:
    when = _value(job.updated_at)
    return f"""
    <li class="focus-row">
      <span class="row-when warn">{_ICO_STALE}{escape(when)}</span>
      <span class="row-title">{_status_dot(job.status)}{_job_link(job)}</span>
      <span class="row-meta">{escape(job.company or "—")}</span>
      <span class="row-subject">{escape(job.status)}</span>
    </li>
    """


def _interview_item(interview: InterviewEvent) -> str:
    when = _value_time(interview.scheduled_at)
    return f"""
    <li class="focus-row">
      <span class="row-when ok">{_ICO_INTERVIEW}{escape(when)}</span>
      <span class="row-title">{_status_dot("interviewing")}{_job_link(interview.job)}</span>
      <span class="row-meta">{escape(interview.job.company or "—")}</span>
      <span class="row-subject">{escape(interview.stage)}{(" · " + escape(interview.location)) if interview.location else ""}</span>
    </li>
    """


def _artefact_item(artefact: Artefact) -> str:
    linked_jobs = {link.job.id: link.job for link in artefact.job_links}
    if artefact.job:
        linked_jobs[artefact.job.id] = artefact.job
    context = ", ".join(
        job.title for job in sorted(linked_jobs.values(), key=lambda x: x.title.lower())
    ) or "—"
    when = _value(artefact.follow_up_at)
    return f"""
    <li class="focus-row">
      <span class="row-when warn">{_ICO_ARTEFACT}{escape(when)}</span>
      <span class="row-title"><a href="/artefacts">{escape(artefact.filename)}</a></span>
      <span class="row-meta">{escape(artefact.purpose or artefact.kind)}</span>
      <span class="row-subject">{escape(context)}</span>
    </li>
    """


def _no_action_item(job: Job) -> str:
    return f"""
    <li class="focus-row">
      <span class="row-when muted">{_ICO_NACTION}No follow-up</span>
      <span class="row-title">{_status_dot(job.status)}{_job_link(job)}</span>
      <span class="row-meta">{escape(job.company or "—")}</span>
      <span class="row-subject">{escape(job.status)}</span>
    </li>
    """


def _recent_item(job: Job) -> str:
    when = _value(job.created_at)
    return f"""
    <li class="focus-row">
      <span class="row-when muted">{_ICO_PROSPECT}{escape(when)}</span>
      <span class="row-title">{_status_dot(job.status)}{_job_link(job)}</span>
      <span class="row-meta">{escape(job.company or "—")}</span>
      <span class="row-subject">{escape(job.status)}</span>
    </li>
    """


def _row_list(items: list[str], empty: str) -> str:
    if not items:
        return f'<p class="focus-empty">{escape(empty)}</p>'
    return '<ul class="focus-rows">' + "\n".join(items) + "</ul>"


# ── Section builders ──────────────────────────────────────────────────────────

def _section(
    icon: str,
    title: str,
    body: str,
    *,
    section_id: str,
    count: int,
    badge_tone: str = "neutral",
    span_wide: bool = False,
) -> str:
    tone_class = {
        "urgent": "badge-urgent",
        "warn": "badge-warn",
        "ok": "badge-ok",
        "neutral": "badge-neutral",
    }.get(badge_tone, "badge-neutral")
    badge = f'<span class="section-badge {tone_class}">{count}</span>' if count else ""
    wide_class = " span-wide" if span_wide else ""
    return f"""
    <section class="focus-section{wide_class}" id="{escape(section_id, quote=True)}">
      <header class="section-head">
        <span class="section-icon">{icon}</span>
        <h2>{escape(title)}</h2>
        {badge}
      </header>
      {body}
    </section>
    """


def _focus_ai_target(
    due_followups: list[Communication],
    stale_jobs: list[Job],
    recent_jobs: list[Job],
) -> Job | None:
    if due_followups:
        return due_followups[0].job
    if stale_jobs:
        return stale_jobs[0]
    if recent_jobs:
        return recent_jobs[0]
    return None


def _flash_message(message: str, *, tone: str) -> str:
    return f'<p class="focus-flash flash-{escape(tone, quote=True)}">{escape(message)}</p>'


def _focus_redirect(*, ai_status: str | None = None, ai_error: str | None = None) -> str:
    params = []
    if ai_status:
        params.append(f"ai_status={quote(ai_status)}")
    if ai_error:
        params.append(f"ai_error={quote(ai_error)}")
    if not params:
        return "/focus"
    return "/focus?" + "&".join(params)


def _focus_ai_panel(job: Job | None, ai_output: "AiOutput | None") -> str:
    if job is None:
        return ""
    output_html = ""
    if ai_output is not None:
        output_html = f"""
        <div class="ai-output">
          <p class="ai-output-label">{_ICO_NUDGE} For <a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></p>
          {render_markdown_blocks(ai_output.body, class_name="ai-markdown")}
        </div>
        """
    return f"""
    <section class="aside-panel aside-ai">
      <header class="section-head">
        <span class="section-icon">{_ICO_NUDGE}</span>
        <h2>AI nudge</h2>
        <span class="section-badge badge-neutral">Optional</span>
      </header>
      <p class="aside-meta">Target: <a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></p>
      <form method="post" action="/focus/ai-nudge">
        <input type="hidden" name="job_uuid" value="{escape(job.uuid, quote=True)}">
        <button type="submit" class="secondary ai-btn">{_ICO_NUDGE}<span>Suggest next step</span></button>
      </form>
      {output_html}
    </section>
    """


# ── Styles ────────────────────────────────────────────────────────────────────

_FOCUS_STYLES = """
  /* ── Summary stat strip ───────────────────────────────── */
  .focus-stat-strip {
    display: grid;
    gap: 10px;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    margin-bottom: 20px;
  }
  .stat-card {
    align-items: center;
    background: #ffffff;
    border: var(--border-default);
    border-radius: var(--radius-lg);
    color: inherit;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 10px 10px;
    text-align: center;
    text-decoration: none;
    transition: box-shadow 120ms ease-out, transform 120ms ease-out, border-color 120ms ease-out;
  }
  .stat-card:hover {
    border-color: var(--line);
    box-shadow: 0 4px 14px rgba(16,34,52,0.10);
    transform: translateY(-1px);
  }
  .stat-card .stat-icon {
    color: var(--soft-text);
    display: flex;
    margin-bottom: 2px;
  }
  .stat-card .stat-num {
    font-size: 1.6rem;
    font-weight: 500;
    letter-spacing: -0.02em;
    line-height: 1;
  }
  .stat-card .stat-label {
    color: var(--muted);
    font-size: 0.76rem;
    line-height: 1.3;
  }
  .stat-card.urgent .stat-num  { color: var(--danger); }
  .stat-card.warn   .stat-num  { color: #8c5000; }
  .stat-card.ok     .stat-num  { color: var(--success); }
  .stat-card.accent .stat-num  { color: var(--accent-strong); }

  /* ── Focus grid ────────────────────────────────────────── */
  .focus-grid {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .focus-section {
    background: #ffffff;
    border: var(--border-default);
    border-radius: var(--radius-xl);
    display: grid;
    gap: 0;
    overflow: hidden;
  }
  .focus-section.span-wide {
    grid-column: 1 / -1;
  }

  /* ── Section header ────────────────────────────────────── */
  .section-head {
    align-items: center;
    border-bottom: var(--border-default);
    display: flex;
    gap: 8px;
    padding: 11px 16px;
  }
  .section-head h2 {
    flex: 1 1 auto;
    font-size: 0.88rem;
    font-weight: 600;
    letter-spacing: 0;
    margin: 0;
    min-width: 0;
    text-transform: none;
  }
  .section-icon {
    color: var(--soft-text);
    display: flex;
    flex-shrink: 0;
  }
  .section-badge {
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    min-width: 20px;
    padding: 2px 7px;
    text-align: center;
  }
  .badge-urgent { background: var(--danger-soft);   border: 0.5px solid #f8c4be; color: var(--danger); }
  .badge-warn   { background: var(--amber-soft);    border: 0.5px solid #f9d9a0; color: #8c5000; }
  .badge-ok     { background: var(--success-soft);  border: 0.5px solid #b6dfc5; color: var(--success); }
  .badge-neutral { background: var(--accent-soft);  border: 0.5px solid #c3ccf0; color: var(--accent-strong); }

  /* ── Row list ──────────────────────────────────────────── */
  .focus-rows {
    display: grid;
    gap: 0;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .focus-row {
    align-items: center;
    border-bottom: var(--border-default);
    display: grid;
    gap: 0 12px;
    grid-template-columns: 130px minmax(0,1fr) minmax(100px,0.7fr) minmax(120px,1fr);
    min-height: 44px;
    padding: 8px 16px;
    transition: background 100ms ease-out;
  }
  .focus-row:last-child { border-bottom: none; }
  .focus-row:hover { background: var(--surface-soft); }
  .focus-section.span-wide .focus-row {
    grid-template-columns: 130px minmax(0,1.4fr) minmax(100px,0.7fr) minmax(140px,1fr);
  }
  .focus-empty {
    color: var(--soft-text);
    font-size: 0.84rem;
    padding: 14px 16px;
    margin: 0;
  }

  /* ── Row cells ─────────────────────────────────────────── */
  .row-when {
    align-items: center;
    display: flex;
    font-size: 0.78rem;
    font-weight: 500;
    gap: 5px;
    white-space: nowrap;
  }
  .row-when svg { flex-shrink: 0; }
  .row-when.urgent { color: var(--danger); }
  .row-when.warn   { color: #8c5000; }
  .row-when.ok     { color: var(--success); }
  .row-when.muted  { color: var(--soft-text); }

  .row-title {
    align-items: center;
    display: flex;
    font-size: 0.88rem;
    font-weight: 500;
    gap: 7px;
    min-width: 0;
    overflow: hidden;
  }
  .row-title a {
    color: var(--ink);
    overflow: hidden;
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row-title a:hover { color: var(--accent-strong); text-decoration: underline; }

  .row-meta {
    color: var(--muted);
    font-size: 0.81rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row-subject {
    color: var(--soft-text);
    font-size: 0.81rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── Status dot ─────────────────────────────────────────── */
  .status-dot {
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
    height: 7px;
    width: 7px;
  }
  .dot-accent  { background: var(--accent); }
  .dot-amber   { background: var(--amber); }
  .dot-success { background: var(--success); }
  .dot-danger  { background: var(--danger); }
  .dot-muted   { background: var(--soft-text); }

  /* ── Aside ──────────────────────────────────────────────── */
  .focus-aside {
    display: grid;
    gap: 14px;
  }
  .aside-panel {
    background: #ffffff;
    border: var(--border-default);
    border-radius: var(--radius-xl);
    display: grid;
    gap: 0;
    overflow: hidden;
  }
  .aside-nav-list {
    display: grid;
    gap: 0;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .aside-nav-list li {
    border-bottom: var(--border-default);
  }
  .aside-nav-list li:last-child { border-bottom: none; }
  .aside-nav-item {
    align-items: center;
    color: var(--ink);
    display: flex;
    font-size: 0.86rem;
    font-weight: 500;
    gap: 10px;
    min-height: 44px;
    padding: 0 16px;
    text-decoration: none;
    transition: background 100ms ease-out;
  }
  .aside-nav-item:hover { background: var(--surface-soft); }
  .aside-nav-item .nav-icon { color: var(--soft-text); display: flex; flex-shrink: 0; }
  .aside-nav-item .nav-label { flex: 1 1 auto; min-width: 0; }
  .aside-nav-item .nav-count {
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 2px 7px;
  }
  .nav-count.urgent  { background: var(--danger-soft);  border: 0.5px solid #f8c4be; color: var(--danger); }
  .nav-count.warn    { background: var(--amber-soft);   border: 0.5px solid #f9d9a0; color: #8c5000; }
  .nav-count.ok      { background: var(--success-soft); border: 0.5px solid #b6dfc5; color: var(--success); }
  .nav-count.neutral { background: var(--accent-soft);  border: 0.5px solid #c3ccf0; color: var(--accent-strong); }
  .nav-count.zero    { background: var(--surface-muted); border: var(--border-default); color: var(--soft-text); }

  .aside-panel-body {
    padding: 14px 16px;
    display: grid;
    gap: 10px;
  }
  .aside-meta {
    color: var(--muted);
    font-size: 0.84rem;
    margin: 0;
    padding: 10px 16px 0;
  }
  .aside-meta a { color: var(--accent-strong); font-weight: 500; }
  .ai-btn { justify-content: center; width: 100%; }
  .ai-btn span { flex: 0; }

  .ai-output {
    border-top: var(--border-default);
    display: grid;
    gap: 10px;
    padding: 12px 16px;
  }
  .ai-output-label {
    align-items: center;
    color: var(--muted);
    display: flex;
    font-size: 0.82rem;
    gap: 5px;
    margin: 0;
  }
  .ai-output-label a { color: var(--accent-strong); font-weight: 500; }
  .ai-markdown { display: grid; gap: 8px; max-height: 200px; overflow-y: auto; }
  .ai-markdown h2, .ai-markdown h3, .ai-markdown h4 { font-size: 0.93rem; margin: 0; }
  .ai-markdown p, .ai-markdown ul { font-size: 0.88rem; margin: 0; }
  .ai-markdown ul { padding-left: 16px; }

  .aside-ai form { padding: 10px 16px 0; }
  .aside-ai .ai-btn { margin-bottom: 0; }

  /* ── Profile prompt ─────────────────────────────────────── */
  .profile-prompt {
    align-items: center;
    background: linear-gradient(135deg, rgba(79,103,228,0.06), rgba(79,103,228,0.02));
    border: 0.5px solid #c3ccf0;
    border-radius: var(--radius-xl);
    display: flex;
    gap: 14px;
    margin-bottom: 16px;
    padding: 14px 18px;
  }
  .profile-prompt-icon { color: var(--accent); display: flex; flex-shrink: 0; }
  .profile-prompt-text { flex: 1 1 auto; min-width: 0; }
  .profile-prompt-text strong { color: var(--ink); display: block; font-size: 0.9rem; font-weight: 600; }
  .profile-prompt-text span   { color: var(--muted); font-size: 0.82rem; }
  .profile-prompt a.btn-prompt {
    align-items: center;
    background: var(--accent);
    border: 0.5px solid var(--accent-strong);
    border-radius: var(--radius-md);
    color: #fff;
    display: inline-flex;
    flex-shrink: 0;
    font-size: 0.84rem;
    font-weight: 500;
    gap: 5px;
    padding: 6px 14px;
    text-decoration: none;
    transition: background 120ms ease-out;
    white-space: nowrap;
  }
  .profile-prompt a.btn-prompt:hover { background: var(--accent-strong); }

  /* ── Flash messages ─────────────────────────────────────── */
  .focus-flash {
    border-radius: var(--radius-md);
    font-size: 0.86rem;
    font-weight: 500;
    margin: 0;
    padding: 10px 14px;
  }
  .flash-success { background: var(--success-soft); border: 0.5px solid #b6dfc5; color: var(--success); }
  .flash-error   { background: var(--danger-soft);  border: 0.5px solid #f8c4be; color: var(--danger); }

  /* ── Responsive ─────────────────────────────────────────── */
  @media (max-width: 1180px) {
    .focus-stat-strip { grid-template-columns: repeat(3, minmax(0,1fr)); }
    .focus-row {
      grid-template-columns: 110px minmax(0,1fr) minmax(80px,0.6fr);
    }
    .focus-row .row-subject { display: none; }
    .focus-section.span-wide .focus-row {
      grid-template-columns: 110px minmax(0,1fr) minmax(80px,0.6fr);
    }
  }
  @media (max-width: 860px) {
    .focus-stat-strip { grid-template-columns: repeat(2, minmax(0,1fr)); }
    .focus-grid { grid-template-columns: 1fr; }
    .focus-row { grid-template-columns: 100px minmax(0,1fr); }
    .focus-row .row-meta,
    .focus-row .row-subject { display: none; }
  }
"""


# ── Main render ───────────────────────────────────────────────────────────────

def render_focus(
    user: User,
    *,
    profile: UserProfile | None,
    due_followups: list[Communication],
    due_artefact_followups: list[Artefact],
    stale_jobs: list[Job],
    recent_jobs: list[Job],
    interviews: list[InterviewEvent],
    no_next_action_jobs: list[Job],
    active_count: int,
    ai_output: AiOutput | None = None,
    ai_target_job: Job | None = None,
    ai_status: str | None = None,
    ai_error: str | None = None,
) -> HTMLResponse:
    # ── Goal chip ──────────────────────────────────────────────────────────
    goal = None
    if profile and (profile.target_roles or profile.target_locations or profile.salary_min or profile.salary_max):
        goal_bits = ['<span class="goal-chip-label">Target:</span>']
        if profile.target_roles:
            goal_bits.append(f'<strong class="goal-chip-primary">{escape(profile.target_roles)}</strong>')
        if profile.target_locations:
            goal_bits.append('<span class="goal-chip-sep secondary">|</span>')
            goal_bits.append(f'<span class="goal-chip-secondary">{escape(profile.target_locations)}</span>')
        if profile.salary_min or profile.salary_max:
            salary = " / ".join(
                part for part in (
                    _format_salary_goal(profile.salary_min, profile.salary_currency),
                    _format_salary_goal(profile.salary_max, profile.salary_currency),
                ) if part
            )
            if salary:
                goal_bits.append('<span class="goal-chip-sep tertiary">|</span>')
                goal_bits.append(f'<span class="goal-chip-tertiary">{escape(salary)}</span>')
        goal = "".join(goal_bits)

    # ── Profile prompt ─────────────────────────────────────────────────────
    profile_prompt = ""
    if _profile_is_empty(profile):
        profile_prompt = f"""
        <div class="profile-prompt">
          <span class="profile-prompt-icon">{_ICO_SETTINGS}</span>
          <div class="profile-prompt-text">
            <strong>Complete your search profile</strong>
            <span>Add target roles, locations and salary to unlock smarter focus signals.</span>
          </div>
          <a class="btn-prompt" href="/settings#profile">{_ICO_SETTINGS}<span>Set up profile</span></a>
        </div>
        """

    # ── Flash messages ─────────────────────────────────────────────────────
    flashes = ""
    if ai_status:
        flashes += _flash_message(ai_status, tone="success")
    if ai_error:
        flashes += _flash_message(ai_error, tone="error")

    # ── Section rows ────────────────────────────────────────────────────────
    followup_rows    = [_followup_item(e) for e in due_followups]
    artefact_rows    = [_artefact_item(a) for a in due_artefact_followups]
    stale_rows       = [_stale_item(j) for j in stale_jobs]
    interview_rows   = [_interview_item(i) for i in interviews]
    no_action_rows   = [_no_action_item(j) for j in no_next_action_jobs]
    recent_rows      = [_recent_item(j) for j in recent_jobs]

    all_fu_rows      = followup_rows + artefact_rows
    all_fu_count     = len(due_followups) + len(due_artefact_followups)

    grid = f"""
    <div class="focus-grid">
      {_section(_ICO_FOLLOWUP, "Due follow-ups", _row_list(all_fu_rows, "No follow-ups due — all clear."),
                section_id="due-follow-ups", count=all_fu_count,
                badge_tone="urgent" if all_fu_count else "neutral")}
      {_section(_ICO_INTERVIEW, "Upcoming interviews", _row_list(interview_rows, "No interviews scheduled."),
                section_id="upcoming-interviews", count=len(interviews),
                badge_tone="ok" if interviews else "neutral")}
      {_section(_ICO_STALE, "Stale active jobs", _row_list(stale_rows, "No stale jobs — everything is moving."),
                section_id="stale-active-jobs", count=len(stale_jobs),
                badge_tone="warn" if stale_jobs else "neutral")}
      {_section(_ICO_NACTION, "Need next action", _row_list(no_action_rows, "All active jobs have a scheduled follow-up."),
                section_id="no-next-action", count=len(no_next_action_jobs),
                badge_tone="warn" if no_next_action_jobs else "neutral")}
      {_section(_ICO_PROSPECT, "Recent prospects", _row_list(recent_rows, "No new saved or interested jobs."),
                section_id="recent-prospects", count=len(recent_jobs),
                badge_tone="neutral", span_wide=True)}
    </div>
    """

    body = profile_prompt + grid

    # ── Aside ───────────────────────────────────────────────────────────────
    def _nav_count(n: int, tone: str) -> str:
        t = tone if n else "zero"
        return f'<span class="nav-count {t}">{n}</span>'

    aside = f"""
    <div class="focus-aside">
      {flashes}
      <section class="aside-panel">
        <header class="section-head">
          <span class="section-icon">{_ICO_ACTIVE}</span>
          <h2>Queue</h2>
          {_nav_count(active_count, "neutral")}
        </header>
        <ul class="aside-nav-list">
          <li><a class="aside-nav-item" href="#due-follow-ups">
            <span class="nav-icon">{_ICO_FOLLOWUP}</span>
            <span class="nav-label">Due follow-ups</span>
            {_nav_count(len(due_followups) + len(due_artefact_followups), "urgent")}
          </a></li>
          <li><a class="aside-nav-item" href="#upcoming-interviews">
            <span class="nav-icon">{_ICO_INTERVIEW}</span>
            <span class="nav-label">Interviews</span>
            {_nav_count(len(interviews), "ok")}
          </a></li>
          <li><a class="aside-nav-item" href="#stale-active-jobs">
            <span class="nav-icon">{_ICO_STALE}</span>
            <span class="nav-label">Stale jobs</span>
            {_nav_count(len(stale_jobs), "warn")}
          </a></li>
          <li><a class="aside-nav-item" href="#no-next-action">
            <span class="nav-icon">{_ICO_NACTION}</span>
            <span class="nav-label">Need next action</span>
            {_nav_count(len(no_next_action_jobs), "warn")}
          </a></li>
        </ul>
      </section>
      {_focus_ai_panel(ai_target_job, ai_output)}
    </div>
    """

    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Focus",
            title="Focus",
            subtitle="",
            active="focus",
            actions=(("Add job", "/jobs/new", "add-job"),),
            body=body,
            aside=aside,
            goal=goal,
            container="split",
            extra_styles=_FOCUS_STYLES,
            show_hero=False,
        )
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/focus", response_class=HTMLResponse, include_in_schema=False)
def focus(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    ai_status: Annotated[str | None, Query()] = None,
    ai_error: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    now = datetime.now(UTC)
    profile = get_user_profile(db, current_user)
    due_followups = _list_due_followups(db, current_user, now=now)
    due_artefact_followups = list_due_artefact_followups(db, current_user, now=now)
    stale_jobs = _list_stale_jobs(db, current_user, now=now)
    recent_jobs = _list_recent_jobs(db, current_user)
    ai_target_job = _focus_ai_target(due_followups, stale_jobs, recent_jobs)
    ai_output = None
    if ai_target_job is not None:
        ai_output = db.scalar(
            select(AiOutput)
            .where(
                AiOutput.owner_user_id == current_user.id,
                AiOutput.job_id == ai_target_job.id,
                AiOutput.output_type == "recommendation",
                AiOutput.status == "active",
            )
            .order_by(AiOutput.updated_at.desc(), AiOutput.created_at.desc())
        )
    return render_focus(
        current_user,
        profile=profile,
        due_followups=due_followups,
        due_artefact_followups=due_artefact_followups,
        stale_jobs=stale_jobs,
        recent_jobs=recent_jobs,
        interviews=_list_upcoming_interviews(db, current_user, now=now),
        no_next_action_jobs=_list_jobs_with_no_next_action(db, current_user),
        active_count=_count_active_jobs(db, current_user),
        ai_output=ai_output,
        ai_target_job=ai_target_job,
        ai_status=ai_status,
        ai_error=ai_error,
    )


@router.post("/focus/ai-nudge", include_in_schema=False)
def create_focus_ai_nudge(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    job_uuid: Annotated[str, Form()] = "",
) -> RedirectResponse:
    job = db.scalar(
        select(Job).where(
            Job.uuid == job_uuid,
            Job.owner_user_id == current_user.id,
        )
    )
    if job is None:
        return RedirectResponse(
            url=_focus_redirect(ai_error="Focus target was not found"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        generate_job_ai_output(
            db,
            current_user,
            job,
            output_type="recommendation",
        )
        return RedirectResponse(
            url=_focus_redirect(ai_status=f"Next step suggestion generated for {job.title}"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except AiExecutionError as e:
        return RedirectResponse(
            url=_focus_redirect(ai_error=str(e)),
            status_code=status.HTTP_303_SEE_OTHER,
        )
