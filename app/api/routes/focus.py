from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import compact_content_rhythm_styles, render_shell_page
from app.db.models.communication import Communication
from app.db.models.interview_event import InterviewEvent
from app.db.models.job import Job
from app.db.models.user import User
from app.db.models.user_profile import UserProfile
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


def _section(title: str, body: str) -> str:
    return f"""
    <article class="focus-card">
      <div class="card-header">
        <div>
          <p class="panel-micro">Focus queue</p>
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


def render_focus(
    user: User,
    *,
    profile: UserProfile | None,
    due_followups: list[Communication],
    stale_jobs: list[Job],
    recent_jobs: list[Job],
    interviews: list[InterviewEvent],
    active_count: int,
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
    stale_items = [_job_item(job, detail=f"Updated {_value(job.updated_at)}") for job in stale_jobs]
    recent_items = [_job_item(job, detail=f"Added {_value(job.created_at)}") for job in recent_jobs]
    interview_items = [_interview_item(interview) for interview in interviews]
    extra_styles = compact_content_rhythm_styles() + """
    .focus-summary {
      margin-bottom: 18px;
    }
    .focus-grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .focus-card {
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 14px;
      padding: 18px;
    }
    .focus-list {
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .focus-list li {
      background: rgba(247,249,252,0.92);
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-lg);
      display: grid;
      gap: 4px;
      padding: 14px;
    }
    .focus-list li strong { font-size: 1rem; }
    .focus-list li span,
    .focus-list li p,
    .empty { color: var(--muted); }
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
      background: rgba(247,249,252,0.92);
      border: 1px dashed var(--line);
      border-radius: var(--radius-lg);
      padding: 14px;
    }
    @media (max-width: 760px) {
      .focus-grid { grid-template-columns: 1fr; }
    }
    """
    aside = f"""
    <div class="focus-aside">
      <section class="page-panel soft">
        <div class="panel-header">
          <div>
            <p class="panel-micro">Resume</p>
            <h2>Where to resume</h2>
          </div>
          <a class="secondary" href="/board">Board</a>
        </div>
        <p>Use Focus for the next decision, then jump into Board or Job Workspace to keep the application moving.</p>
        <div class="mobile-stack">
          <span class="status-pill accent">{len(due_followups)} due follow-ups</span>
          <span class="status-pill warn">{len(stale_jobs)} stale jobs</span>
          <span class="status-pill success">{len(interviews)} interviews</span>
        </div>
      </section>
      <section class="page-panel emphasis">
        <div class="panel-header">
          <div>
            <p class="panel-micro">Daily rhythm</p>
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
      <div class="metric-card"><strong>{len(due_followups)}</strong><span>Due follow-ups</span></div>
      <div class="metric-card"><strong>{len(stale_jobs)}</strong><span>Stale jobs</span></div>
      <div class="metric-card"><strong>{len(interviews)}</strong><span>Upcoming interviews</span></div>
      <div class="metric-card"><strong>{active_count}</strong><span>Active jobs</span></div>
    </div>
    <div class="focus-grid">
      {_section("Due follow-ups", _list(due_items, "No due follow-ups."))}
      {_section("Stale active jobs", _list(stale_items, "No stale active jobs."))}
      {_section("Upcoming interviews", _list(interview_items, "No upcoming interviews."))}
      {_section("Recent prospects", _list(recent_items, "No recent saved or interested jobs."))}
    </div>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Focus",
            title="Focus",
            subtitle="What needs attention now",
            active="focus",
            actions=(("Add job", "/jobs/new", "add-job"),),
            body=body,
            aside=aside,
            goal=goal,
            kicker="Daily command surface",
            container="split",
            extra_styles=extra_styles,
        )
    )


@router.get("/focus", response_class=HTMLResponse, include_in_schema=False)
def focus(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    now = datetime.now(UTC)
    return render_focus(
        current_user,
        profile=get_user_profile(db, current_user),
        due_followups=_list_due_followups(db, current_user, now=now),
        stale_jobs=_list_stale_jobs(db, current_user, now=now),
        recent_jobs=_list_recent_jobs(db, current_user),
        interviews=_list_upcoming_interviews(db, current_user, now=now),
        active_count=_count_active_jobs(db, current_user),
    )
