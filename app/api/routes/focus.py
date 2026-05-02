from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import compact_content_rhythm_styles, render_shell_page
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


def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


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
    """Active jobs that have no pending follow-up communication."""
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


def _job_link(job: Job) -> str:
    return f'<a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a>'


def _empty(message: str) -> str:
    return f'<p class="empty">{escape(message)}</p>'


def _followup_item(event: Communication) -> str:
    return f"""
    <li>
      <strong>{_job_link(event.job)}</strong>
      <span>{escape(_value(event.follow_up_at))}</span>
      <p>{escape(event.subject or event.notes or "Follow up")}</p>
    </li>
    """


def _job_item(job: Job, *, detail: str) -> str:
    return f"""
    <li>
      <strong>{_job_link(job)}</strong>
      <span>{escape(detail)}</span>
      <p>{escape(job.company or "Company not set")} · {escape(job.status)}</p>
    </li>
    """


def _interview_item(interview: InterviewEvent) -> str:
    return f"""
    <li>
      <strong>{_job_link(interview.job)}</strong>
      <span>{escape(_value(interview.scheduled_at))}</span>
      <p>{escape(interview.stage)} · {escape(interview.location or "Location not set")}</p>
    </li>
    """


def _artefact_followup_item(artefact: Artefact) -> str:
    linked_jobs = {link.job.id: link.job for link in artefact.job_links}
    if artefact.job:
        linked_jobs[artefact.job.id] = artefact.job
    linked_context = ", ".join(
        job.title for job in sorted(linked_jobs.values(), key=lambda item: item.title.lower())
    )
    if not linked_context:
        linked_context = "No linked jobs"
    return f"""
    <li>
      <strong><a href="/artefacts">{escape(artefact.filename)}</a></strong>
      <span>{escape(_value(artefact.follow_up_at))}</span>
      <p>{escape(artefact.purpose or artefact.kind)} · {escape(linked_context)}</p>
    </li>
    """


def _section(title: str, body: str, *, section_id: str, wide: bool = False) -> str:
    wide_class = " span-wide" if wide else ""
    return f"""
    <article class="focus-card{wide_class}" id="{escape(section_id, quote=True)}">
      <div class="card-header">
        <div>
          <h2>{escape(title)}</h2>
        </div>
        <span class="status-pill accent">Now</span>
      </div>
      {body}
    </article>
    """


def _list(items: list[str], empty_message: str) -> str:
    if not items:
        return _empty(empty_message)
    return '<ul class="focus-list">' + "\n".join(items) + "</ul>"


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
    return f'<section class="page-panel flash flash-{escape(tone, quote=True)}"><p>{escape(message)}</p></section>'


def _focus_redirect(*, ai_status: str | None = None, ai_error: str | None = None) -> str:
    params = []
    if ai_status:
        params.append(f"ai_status={quote(ai_status)}")
    if ai_error:
        params.append(f"ai_error={quote(ai_error)}")
    if not params:
        return "/focus"
    return "/focus?" + "&".join(params)


def _focus_ai_output(output: AiOutput | None, job: Job | None) -> str:
    if output is None or job is None:
        return '<p class="meta">No AI nudge yet. Generate one when you want a quick steer on the next useful move.</p>'
    return f"""
    <article class="focus-ai-card">
      <div class="panel-header">
        <div>
          <h2>AI nudge</h2>
        </div>
        <span class="status-pill accent">Optional</span>
      </div>
      <p class="meta">For <a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></p>
      {render_markdown_blocks(output.body, class_name="ai-markdown")}
    </article>
    """


def _focus_ai_panel(job: Job | None) -> str:
    if job is None:
        return """
        <section class="page-panel soft">
          <div class="panel-header">
            <div>
              <h2>No current target</h2>
            </div>
          </div>
          <p>No due follow-up, stale active job, or recent prospect is available for a Focus suggestion right now.</p>
        </section>
        """
    return f"""
    <section class="page-panel ai">
      <div class="panel-header">
        <div>
          <h2>Suggest the next useful move</h2>
        </div>
        <span class="status-pill accent">Manual</span>
      </div>
      <p class="meta">Targeting <a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a>. Focus uses one explicit recommendation at a time.</p>
      <form method="post" action="/focus/ai-nudge">
        <input type="hidden" name="job_uuid" value="{escape(job.uuid, quote=True)}">
        <button type="submit">Suggest next step</button>
      </form>
    </section>
    """


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
                part
                for part in (
                    _format_salary_goal(profile.salary_min, profile.salary_currency),
                    _format_salary_goal(profile.salary_max, profile.salary_currency),
                )
                if part
            )
            if salary:
                goal_bits.append('<span class="goal-chip-sep tertiary">|</span>')
                goal_bits.append(f'<span class="goal-chip-tertiary">{escape(salary)}</span>')
        goal = "".join(goal_bits)

    profile_prompt = (
        """
        <section class="page-panel ai prompt">
          <div class="panel-header">
            <div>
              <p class="panel-micro">Profile signal</p>
              <h2>Complete your job-search profile</h2>
            </div>
            <span class="status-pill accent">Useful next</span>
          </div>
          <p>Focus will become more useful when it knows your target roles, locations, constraints, and positioning notes.</p>
          <a class="button" href="/settings#profile">Add profile</a>
        </section>
        """
        if _profile_is_empty(profile)
        else ""
    )
    due_items = [_followup_item(event) for event in due_followups]
    artefact_followup_items = [
        _artefact_followup_item(artefact) for artefact in due_artefact_followups
    ]
    stale_items = [_job_item(job, detail=f"Updated {_value(job.updated_at)}") for job in stale_jobs]
    recent_items = [_job_item(job, detail=f"Added {_value(job.created_at)}") for job in recent_jobs]
    interview_items = [_interview_item(interview) for interview in interviews]
    no_next_action_items = [
        _job_item(job, detail=f"Status: {job.status}")
        for job in no_next_action_jobs
    ]
    extra_styles = compact_content_rhythm_styles() + """
    .focus-summary {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      margin-bottom: 18px;
    }
    .focus-summary .metric-card {
      color: inherit;
      min-width: 0;
      text-decoration: none;
      transition: border-color 120ms ease-out, transform 120ms ease-out;
    }
    .focus-summary .metric-card:hover,
    .focus-summary .metric-card:focus-visible {
      border-color: var(--line);
      transform: translateY(-1px);
    }
    .focus-grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .focus-card.span-wide {
      grid-column: 1 / -1;
    }
    .focus-card {
      background: #ffffff;
      border: var(--border-default);
      border-radius: var(--radius-xl);
      display: grid;
      gap: 12px;
      padding: 16px 18px;
    }
    .focus-list {
      display: grid;
      gap: 6px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .focus-list li {
      background: rgba(247,249,252,0.72);
      border: var(--border-default);
      border-radius: var(--radius-md);
      display: grid;
      gap: 3px;
      padding: 10px 12px;
    }
    .focus-list li strong { font-size: 0.93rem; font-weight: 500; }
    .focus-list li span,
    .focus-list li p,
    .empty { color: var(--muted); font-size: 0.84rem; }
    .focus-card.span-wide .focus-list li {
      align-items: center;
      grid-template-columns: minmax(220px, 1.4fr) minmax(160px, 0.8fr) minmax(180px, 1fr);
    }
    .focus-card.span-wide .focus-list li p {
      margin: 0;
    }
    .focus-aside {
      display: grid;
      gap: 18px;
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
    .empty {
      background: transparent;
      border: 0.5px dashed rgba(0,0,0,0.12);
      border-radius: var(--radius-md);
      padding: 10px 12px;
    }
    .flash { padding: 14px 18px; }
    .flash-success {
      background: var(--success-soft);
      border-color: #b6dfc5;
    }
    .flash-error {
      background: var(--danger-soft);
      border-color: #f8c4be;
    }
    .focus-ai-card {
      background: var(--accent-soft);
      border: 0.5px solid #C3CCF0;
      border-radius: var(--radius-xl);
      display: grid;
      gap: 12px;
      padding: 16px 18px;
    }
    .focus-ai-card .ai-markdown {
      max-height: 220px;
      overflow-y: auto;
    }
    .focus-aside form { display: grid; gap: 10px; }
    .ai-markdown { display: grid; gap: 10px; }
    .ai-markdown h2, .ai-markdown h3, .ai-markdown h4 { font-size: 1rem; margin: 0; }
    .ai-markdown p, .ai-markdown ul { margin: 0; }
    .ai-markdown ul { padding-left: 18px; }
    @media (max-width: 1180px) {
      .focus-summary {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .focus-card.span-wide .focus-list li {
        align-items: start;
        grid-template-columns: 1fr;
      }
    }
    @media (max-width: 760px) {
      .focus-summary {
        grid-template-columns: 1fr;
      }
      .focus-grid { grid-template-columns: 1fr; }
    }
    """
    flash_parts = []
    if ai_status:
        flash_parts.append(_flash_message(ai_status, tone="success"))
    if ai_error:
        flash_parts.append(_flash_message(ai_error, tone="error"))
    aside = f"""
    <div class="focus-aside">
      {' '.join(flash_parts)}
      <section class="page-panel soft">
        <div class="panel-header">
          <div>
            <h2>Where to resume</h2>
          </div>
          <a class="secondary" href="/board">Board</a>
        </div>
        <p>Start with the highest-signal queue, then jump into the matching work surface.</p>
        <div class="mobile-stack">
          <a class="status-pill accent" href="#due-follow-ups">{len(due_followups)} due follow-ups</a>
          <a class="status-pill accent" href="#artefact-reviews">{len(due_artefact_followups)} artefact reviews</a>
          <a class="status-pill warn" href="#stale-active-jobs">{len(stale_jobs)} stale jobs</a>
          <a class="status-pill success" href="#upcoming-interviews">{len(interviews)} interviews</a>
          <a class="status-pill warn" href="#no-next-action">{len(no_next_action_jobs)} no next action</a>
        </div>
      </section>
      {_focus_ai_panel(ai_target_job)}
      {_focus_ai_output(ai_output, ai_target_job)}
      <section class="page-panel emphasis">
        <div class="panel-header">
          <div>
            <h2>Keep the loop tight</h2>
          </div>
        </div>
        <p>Start with follow-ups, review what has gone stale, and end by deciding whether new prospects belong in the workflow.</p>
        <ul class="tip-list">
          <li>Review Inbox before adding new manual jobs.</li>
          <li>Use Job Workspace when a role needs execution, not just status movement.</li>
          <li>Record return notes after external actions so Focus stays trustworthy.</li>
        </ul>
      </section>
    </div>
    """
    body = f"""
    {profile_prompt}
    <div class="metric-grid focus-summary" aria-label="Focus summary">
      <a class="metric-card" href="#due-follow-ups"><strong>{len(due_followups)}</strong><span>Due follow-ups</span></a>
      <a class="metric-card" href="#artefact-reviews"><strong>{len(due_artefact_followups)}</strong><span>Artefact reviews</span></a>
      <a class="metric-card" href="#stale-active-jobs"><strong>{len(stale_jobs)}</strong><span>Stale jobs</span></a>
      <a class="metric-card" href="#upcoming-interviews"><strong>{len(interviews)}</strong><span>Upcoming interviews</span></a>
      <a class="metric-card" href="/board?workflow=in_progress"><strong>{active_count}</strong><span>Active jobs</span></a>
    </div>
    <div class="focus-grid">
      {_section("Due follow-ups", _list(due_items, "No due follow-ups."), section_id="due-follow-ups")}
      {_section("Artefact reviews", _list(artefact_followup_items, "No artefact reviews due."), section_id="artefact-reviews")}
      {_section("Stale active jobs", _list(stale_items, "No stale active jobs."), section_id="stale-active-jobs")}
      {_section("Upcoming interviews", _list(interview_items, "No upcoming interviews."), section_id="upcoming-interviews")}
      {_section("No next action", _list(no_next_action_items, "All active jobs have a scheduled follow-up."), section_id="no-next-action")}
      {_section("Recent prospects", _list(recent_items, "No recent saved or interested jobs."), section_id="recent-prospects", wide=True)}
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
            extra_styles=extra_styles,
        )
    )


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
            profile=get_user_profile(db, current_user),
            surface="focus",
        )
    except AiExecutionError as exc:
        db.rollback()
        return RedirectResponse(
            url=_focus_redirect(ai_error=str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    db.commit()
    return RedirectResponse(
        url=_focus_redirect(ai_status="AI nudge generated"),
        status_code=status.HTTP_303_SEE_OTHER,
    )
