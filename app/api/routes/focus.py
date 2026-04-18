from datetime import UTC, datetime, timedelta
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user
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
    <section>
      <h2>{escape(title)}</h2>
      {body}
    </section>
    """


def _list(items: list[str], empty_message: str) -> str:
    if not items:
        return _empty(empty_message)
    return "<ul>" + "\n".join(items) + "</ul>"


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
    profile_prompt = (
        """
        <section class="prompt">
          <h2>Complete your job-search profile</h2>
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
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Focus - Application Tracker</title>
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
      max-width: 1100px;
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

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
    }}

    h2 {{
      font-size: 1rem;
    }}

    p, span, .empty {{
      color: var(--muted);
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .button, nav a {{
      border: 1px solid var(--line);
      border-radius: 8px;
      display: inline-flex;
      padding: 8px 10px;
      text-decoration: none;
    }}

    .button {{
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
      width: max-content;
    }}

    .summary {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 16px;
    }}

    .stat, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}

    .stat strong {{
      display: block;
      font-size: 1.8rem;
      line-height: 1;
      margin-bottom: 6px;
    }}

    .grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    .prompt {{
      border-color: var(--accent);
      display: grid;
      gap: 10px;
      margin-bottom: 16px;
    }}

    ul {{
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 12px 0 0;
      padding: 0;
    }}

    li {{
      border-top: 1px solid var(--line);
      display: grid;
      gap: 4px;
      padding-top: 10px;
    }}

    li strong {{
      font-size: 1rem;
    }}

    @media (max-width: 760px) {{
      main {{
        padding: 16px;
      }}

      .topbar,
      .summary,
      .grid {{
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
        <h1>Focus</h1>
        <p>{escape(user.email)} · What needs attention now</p>
      </div>
      <nav>
        <a href="/board">Board</a>
        <a href="/inbox">Inbox</a>
        <a href="/artefacts">Artefacts</a>
        <a href="/jobs/new">Add job</a>
        <a href="/api/capture/bookmarklet">Capture</a>
        <a href="/settings#profile">Profile</a>
        <a href="/settings">Settings</a>
        {'<a href="/admin">Admin</a>' if user.is_admin else ""}
      </nav>
    </header>

    {profile_prompt}

    <div class="summary" aria-label="Focus summary">
      <div class="stat"><strong>{len(due_followups)}</strong><span>Due follow-ups</span></div>
      <div class="stat"><strong>{len(stale_jobs)}</strong><span>Stale jobs</span></div>
      <div class="stat"><strong>{len(interviews)}</strong><span>Upcoming interviews</span></div>
      <div class="stat"><strong>{active_count}</strong><span>Active jobs</span></div>
    </div>

    <div class="grid">
      {_section("Due follow-ups", _list(due_items, "No due follow-ups."))}
      {_section("Stale active jobs", _list(stale_items, "No stale active jobs."))}
      {_section("Upcoming interviews", _list(interview_items, "No upcoming interviews."))}
      {_section("Recent prospects", _list(recent_items, "No recent saved or interested jobs."))}
    </div>
  </main>
</body>
</html>"""
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
