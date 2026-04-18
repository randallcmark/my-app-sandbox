from collections.abc import Iterable
from datetime import UTC, datetime
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.api.deps import DbSession, get_current_user
from app.db.models.job import Job
from app.db.models.user import User
from app.services.jobs import BOARD_STATUSES, list_user_jobs

router = APIRouter(tags=["board"])

BOARD_LABELS = {
    "saved": "Saved",
    "interested": "Interested",
    "preparing": "Preparing",
    "applied": "Applied",
    "interviewing": "Interviewing",
    "offer": "Offer",
    "rejected": "Rejected",
    "archived": "Archived",
}

WORKFLOW_VIEWS = {
    "prospects": ("saved", "interested"),
    "in_progress": ("preparing", "applied", "interviewing"),
    "outcomes": ("offer", "rejected"),
    "all": BOARD_STATUSES,
    "archived": ("archived",),
}

LIST_WORKFLOWS = {"prospects", "outcomes", "archived"}

WORKFLOW_LABELS = {
    "prospects": "Prospects",
    "in_progress": "In Progress",
    "outcomes": "Outcomes",
    "all": "All Active",
    "archived": "Archived",
}

WORKFLOW_PROMPTS = {
    "prospects": "Decide what deserves attention.",
    "in_progress": "Keep applications moving.",
    "outcomes": "Review decisions and close the loop.",
    "all": "Scan every active opportunity.",
    "archived": "Review work removed from the board.",
}

STATUS_HINTS = {
    "saved": "Fresh leads waiting for a decision.",
    "interested": "Worth time and preparation.",
    "preparing": "Tailor materials before applying.",
    "applied": "Submitted and waiting for response.",
    "interviewing": "Conversations in motion.",
    "offer": "Decision pending.",
    "rejected": "Closed by the hiring side.",
    "archived": "Removed from active work.",
}

REFINED_STATUS_ACTIONS = {
    "saved": (("archived", "Dismiss"), ("interested", "Keep")),
    "interested": (("archived", "Archive"), ("preparing", "Prepare")),
    "preparing": (("saved", "Later"), ("applied", "Applied")),
    "applied": (("interviewing", "Interview"), ("rejected", "Rejected")),
    "interviewing": (("offer", "Offer"), ("rejected", "Rejected")),
    "offer": (("archived", "Archive"),),
    "rejected": (("archived", "Archive"),),
    "archived": (("saved", "Restore"),),
}

STALE_AFTER_DAYS = {
    "saved": 7,
    "interested": 7,
    "preparing": 3,
    "applied": 10,
    "interviewing": 10,
    "offer": 3,
}


def _status_options(current_status: str, statuses: Iterable[str]) -> str:
    options = []
    for job_status in statuses:
        label = BOARD_LABELS.get(job_status, job_status.title())
        selected = " selected" if job_status == current_status else ""
        options.append(f'<option value="{escape(job_status)}"{selected}>{escape(label)}</option>')
    return "\n".join(options)


def _stage_started_at(job: Job) -> datetime:
    latest_matching_event = None
    for event in job.communications:
        if event.event_type != "stage_change":
            continue
        if not (event.subject or "").endswith(f" to {job.status}"):
            continue
        occurred_at = event.occurred_at or event.created_at
        if latest_matching_event is None or occurred_at > latest_matching_event:
            latest_matching_event = occurred_at
    return latest_matching_event or job.created_at


def _stage_age_days(job: Job) -> int:
    started_at = _stage_started_at(job)
    now = datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return max((now - started_at).days, 0)


def _stage_age(job: Job) -> str:
    age_days = _stage_age_days(job)
    threshold = STALE_AFTER_DAYS.get(job.status)
    stale = threshold is not None and age_days >= threshold
    stale_class = " stale" if stale else ""
    label = "day" if age_days == 1 else "days"
    stale_text = " · stale" if stale else ""
    return f'<p class="stage-age{stale_class}">In stage: {age_days} {label}{stale_text}</p>'


def _next_follow_up(job: Job) -> datetime | None:
    follow_ups = []
    for event in job.communications:
        if event.follow_up_at is None:
            continue
        follow_up_at = event.follow_up_at
        if follow_up_at.tzinfo is None:
            follow_up_at = follow_up_at.replace(tzinfo=UTC)
        follow_ups.append(follow_up_at)
    return min(follow_ups) if follow_ups else None


def _follow_up_indicator(job: Job) -> str:
    follow_up_at = _next_follow_up(job)
    if follow_up_at is None:
        return ""
    if follow_up_at.tzinfo is None:
        follow_up_at = follow_up_at.replace(tzinfo=UTC)

    today = datetime.now(UTC).date()
    follow_up_date = follow_up_at.date()
    if follow_up_date < today:
        return '<p class="follow-up overdue">Follow-up overdue</p>'
    if follow_up_date == today:
        return '<p class="follow-up due-today">Follow-up due today</p>'
    return f'<p class="follow-up">Follow-up {escape(follow_up_date.isoformat())}</p>'


def _workflow_nav(current_workflow: str) -> str:
    options = []
    for workflow, label in WORKFLOW_LABELS.items():
        selected = " selected" if workflow == current_workflow else ""
        options.append(
            f'<option value="{escape(workflow, quote=True)}"{selected}>{escape(label)}</option>'
        )
    return f"""
    <label>
      Workflow
      <select class="workflow-select" aria-label="Workflow view">
        {"".join(options)}
      </select>
    </label>
    """


def _salary_range(job: Job) -> str:
    if job.salary_min is None and job.salary_max is None:
        return ""

    currency = f"{job.salary_currency} " if job.salary_currency else ""
    if job.salary_min is not None and job.salary_max is not None:
        salary = f"{currency}{job.salary_min:g}-{job.salary_max:g}"
    elif job.salary_min is not None:
        salary = f"{currency}{job.salary_min:g}+"
    else:
        salary = f"Up to {currency}{job.salary_max:g}"
    return f"<span>{escape(salary)}</span>"


def _row_actions(job: Job, workflow: str) -> tuple[str, str]:
    if workflow != "prospects":
        return "", ""

    archive = (
        '<button class="row-status-action row-action archive" '
        'type="button" data-status-target="archived" '
        f'aria-label="Archive {escape(job.title, quote=True)}">Archive</button>'
    )
    if job.status == "interested":
        interested = '<span class="row-state-marker reviewed">Interested</span>'
    else:
        interested = (
            '<button class="row-status-action row-action interested" '
            'type="button" data-status-target="interested" '
            f'aria-label="Mark {escape(job.title, quote=True)} as interested">Interested</button>'
        )
    return archive, interested


def _job_row(job: Job, workflow: str) -> str:
    company = f"<span>{escape(job.company)}</span>" if job.company else ""
    location = f"<span>{escape(job.location)}</span>" if job.location else ""
    source = f"<span>{escape(job.source)}</span>" if job.source else ""
    salary = _salary_range(job)
    meta = "".join([company, location, salary, source])
    if not meta:
        meta = "<span>No extra details yet</span>"
    status_label = BOARD_LABELS.get(job.status, job.status.title())
    source_link = ""
    if job.source_url:
        source_link = (
            f'<a href="{escape(job.source_url, quote=True)}" '
            'target="_blank" rel="noreferrer">Source</a>'
        )

    left_action, right_action = _row_actions(job, workflow)
    created_at = job.created_at.date().isoformat() if job.created_at else ""
    added = f"<span>Added {escape(created_at)}</span>" if created_at else ""

    return f"""
    <article class="job-row status-{escape(job.status)}" data-job-uuid="{escape(job.uuid)}">
      <div class="row-edge row-left">{left_action}</div>
      <div class="row-main">
        <div class="row-title-line">
          <h3><a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></h3>
          <span class="status-pill">{escape(status_label)}</span>
        </div>
        <div class="row-meta">
          {meta}
          {added}
          {source_link}
        </div>
        {_stage_age(job)}
        {_follow_up_indicator(job)}
      </div>
      <div class="row-edge row-right">{right_action}</div>
    </article>
    """


def _list_view(jobs: Iterable[Job], workflow: str) -> str:
    rows = "\n".join(_job_row(job, workflow) for job in jobs)
    empty = '<p class="empty">No jobs in this view.</p>' if not rows else ""
    return f"""
    <section class="list-view" aria-label="{escape(WORKFLOW_LABELS[workflow], quote=True)} jobs">
      {rows}
      {empty}
    </section>
    """


def _job_card(job: Job, statuses: Iterable[str]) -> str:
    company = f"<p>{escape(job.company)}</p>" if job.company else ""
    location = f"<p>{escape(job.location)}</p>" if job.location else ""
    source_link = ""
    if job.source_url:
        source_link = (
            f'<a href="{escape(job.source_url, quote=True)}" '
            'target="_blank" rel="noreferrer">Source</a>'
        )

    return f"""
    <article class="job-card" data-job-uuid="{escape(job.uuid)}" draggable="true">
      <div>
        <h3><a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></h3>
        {company}
        {location}
        {_stage_age(job)}
        {_follow_up_indicator(job)}
      </div>
      <div class="card-meta">
        <span>Position {job.board_position}</span>
        {source_link}
      </div>
      <div class="card-actions">
        <label>
          Move to column
          <select class="job-status-select" aria-label="Move {escape(job.title, quote=True)} to column">
            {_status_options(job.status, statuses)}
          </select>
        </label>
      </div>
    </article>
    """


def _column(status: str, jobs: Iterable[Job], statuses: Iterable[str]) -> str:
    cards = "\n".join(_job_card(job, statuses) for job in jobs)
    empty = '<p class="empty">No jobs in this stage.</p>' if not cards else ""
    label = BOARD_LABELS[status]
    return f"""
    <section class="board-column" data-status="{escape(status)}">
      <header>
        <h2>{escape(label)}</h2>
      </header>
      <div class="column-body" data-drop-zone="true">
        {cards}
        {empty}
      </div>
    </section>
    """


def _refined_workflow_nav(current_workflow: str) -> str:
    links = []
    for workflow, label in WORKFLOW_LABELS.items():
        active = " active" if workflow == current_workflow else ""
        links.append(
            f'<a class="workflow-tab{active}" href="/board?workflow={escape(workflow, quote=True)}">'
            f"{escape(label)}</a>"
        )
    return "\n".join(links)


def _refined_status_summary(jobs_by_status: dict[str, list[Job]], statuses: Iterable[str]) -> str:
    items = []
    for job_status in statuses:
        label = BOARD_LABELS[job_status]
        count = len(jobs_by_status[job_status])
        items.append(
            f"""
            <div class="metric">
              <strong>{count}</strong>
              <span>{escape(label)}</span>
            </div>
            """
        )
    return "\n".join(items)


def _refined_action_buttons(job: Job) -> str:
    buttons = []
    for target_status, label in REFINED_STATUS_ACTIONS.get(job.status, ()):
        intent = "positive" if target_status in {"interested", "preparing", "applied", "interviewing", "offer", "saved"} else "quiet"
        if target_status in {"archived", "rejected"}:
            intent = "negative"
        buttons.append(
            '<button class="refined-action '
            f'{escape(intent, quote=True)}" type="button" '
            f'data-status-target="{escape(target_status, quote=True)}">'
            f"{escape(label)}</button>"
        )
    return "".join(buttons)


def _refined_meta(job: Job) -> str:
    meta = [
        f"<span>{escape(job.company)}</span>" if job.company else "",
        f"<span>{escape(job.location)}</span>" if job.location else "",
        _salary_range(job),
        f"<span>{escape(job.source)}</span>" if job.source else "",
    ]
    rendered = "".join(item for item in meta if item)
    return rendered or "<span>No extra details yet</span>"


def _refined_item(job: Job, *, draggable: bool = False, show_status: bool = True) -> str:
    draggable_attr = ' draggable="true"' if draggable else ""
    status_label = BOARD_LABELS.get(job.status, job.status.title())
    status_pill = f"<span>{escape(status_label)}</span>" if show_status else ""
    source_link = ""
    if job.source_url:
        source_link = (
            f'<a href="{escape(job.source_url, quote=True)}" '
            'target="_blank" rel="noreferrer">Source</a>'
        )
    return f"""
    <article class="refined-item status-{escape(job.status, quote=True)}" data-job-uuid="{escape(job.uuid, quote=True)}"{draggable_attr}>
      <div class="item-main">
        <div class="item-title">
          <h3><a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a></h3>
          {status_pill}
        </div>
        <div class="item-meta">
          {_refined_meta(job)}
          {source_link}
        </div>
        <div class="item-signals">
          {_stage_age(job)}
          {_follow_up_indicator(job)}
        </div>
        <div class="item-actions" aria-label="Next actions">
          {_refined_action_buttons(job)}
        </div>
      </div>
    </article>
    """


def _refined_lane(status_name: str, jobs: Iterable[Job]) -> str:
    cards = "\n".join(_refined_item(job, draggable=True, show_status=False) for job in jobs)
    empty = '<p class="empty refined-empty">Nothing here.</p>' if not cards else ""
    return f"""
    <section class="refined-lane" data-status="{escape(status_name, quote=True)}">
      <header>
        <h2>{escape(BOARD_LABELS[status_name])}</h2>
        <span>{escape(STATUS_HINTS[status_name])}</span>
      </header>
      <div class="refined-lane-body">
        {cards}
        {empty}
      </div>
    </section>
    """


def _refined_board_content(
    visible_jobs: list[Job],
    jobs_by_status: dict[str, list[Job]],
    *,
    workflow: str,
    statuses: Iterable[str],
) -> str:
    if workflow in {"in_progress", "all"}:
        lanes = "\n".join(_refined_lane(status, jobs_by_status[status]) for status in statuses)
        return f'<div class="refined-lanes">{lanes}</div>'

    rows = "\n".join(_refined_item(job) for job in visible_jobs)
    empty = '<p class="empty refined-empty">No jobs in this view.</p>' if not rows else ""
    return f"""
    <section class="refined-list">
      {rows}
      {empty}
    </section>
    """


def render_refined_board(user: User, jobs: list[Job], *, workflow: str = "in_progress") -> str:
    statuses = WORKFLOW_VIEWS[workflow]
    jobs_by_status = {status: [] for status in statuses}
    visible_jobs = []
    for job in jobs:
        if job.status in jobs_by_status:
            jobs_by_status[job.status].append(job)
            visible_jobs.append(job)

    status_list = ",".join(statuses)
    workflow_label = WORKFLOW_LABELS[workflow]
    content = _refined_board_content(
        visible_jobs,
        jobs_by_status,
        workflow=workflow,
        statuses=statuses,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(workflow_label)} - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f4f6f5;
      --ink: #17191c;
      --muted: #65707a;
      --line: #d8dedb;
      --panel: #ffffff;
      --soft: #eef2ef;
      --accent: #126b50;
      --accent-strong: #0d513d;
      --danger: #b42318;
      --success: #16703f;
      --amber: #a35c00;
      --shadow: 0 12px 30px rgba(23, 25, 28, 0.08);
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
      min-height: 100vh;
      padding: 22px;
    }}

    .shell {{
      margin: 0 auto;
      max-width: 1320px;
    }}

    .topbar {{
      align-items: start;
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(0, 1fr) auto;
      margin-bottom: 18px;
    }}

    h1, h2, h3, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      letter-spacing: 0;
      line-height: 1.08;
    }}

    .eyebrow,
    .muted,
    .subhead,
    .item-meta,
    .item-signals,
    .refined-lane header span {{
      color: var(--muted);
    }}

    .eyebrow {{
      font-size: 0.82rem;
      font-weight: 800;
      margin-bottom: 7px;
      text-transform: uppercase;
    }}

    .subhead {{
      line-height: 1.45;
      margin-top: 8px;
    }}

    .top-actions,
    .workflow-tabs,
    .item-actions,
    .metrics {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 750;
    }}

    .top-actions {{
      justify-content: end;
    }}

    .nav-link,
    .workflow-tab,
    .refined-action,
    button {{
      border-radius: 8px;
      font: inherit;
      min-height: 36px;
    }}

    .nav-link,
    .workflow-tab {{
      align-items: center;
      background: #ffffff;
      border: 1px solid var(--line);
      color: var(--ink);
      display: inline-flex;
      padding: 0 12px;
      text-decoration: none;
    }}

    .nav-link.primary,
    .workflow-tab.active {{
      background: var(--ink);
      border-color: var(--ink);
      color: #ffffff;
    }}

    .workflow-tabs {{
      margin-bottom: 14px;
    }}

    .metrics {{
      margin-bottom: 18px;
    }}

    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 126px;
      padding: 12px;
    }}

    .metric strong {{
      display: block;
      font-size: 1.6rem;
      line-height: 1;
      margin-bottom: 5px;
    }}

    .metric span {{
      color: var(--muted);
      font-size: 0.86rem;
      font-weight: 750;
    }}

    .refined-list,
    .refined-lane-body {{
      display: grid;
      gap: 10px;
    }}

    .refined-lanes {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat({len(statuses)}, minmax(250px, 1fr));
      overflow-x: auto;
      padding-bottom: 14px;
    }}

    .refined-lane {{
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 58vh;
      min-width: 250px;
      padding: 10px;
    }}

    .refined-lane header {{
      display: grid;
      gap: 3px;
      padding: 4px 2px 10px;
    }}

    h2 {{
      font-size: 0.98rem;
      line-height: 1.25;
    }}

    .refined-item {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      box-shadow: 0 8px 22px rgba(23, 25, 28, 0.06);
      display: block;
      min-height: 112px;
      padding: 14px;
    }}

    .refined-item[draggable="true"] {{
      cursor: grab;
    }}

    .refined-item.dragging {{
      opacity: 0.55;
    }}

    .refined-lane.drag-over {{
      border-color: var(--accent);
      box-shadow: inset 0 0 0 2px var(--accent);
    }}

    .refined-item.status-interested,
    .refined-item.status-preparing,
    .refined-item.status-applied,
    .refined-item.status-interviewing {{
      border-left-color: var(--accent);
    }}

    .refined-item.status-offer {{
      border-left-color: var(--success);
    }}

    .refined-item.status-rejected {{
      border-left-color: var(--danger);
    }}

    .refined-item.status-archived {{
      border-left-color: #7b838c;
      opacity: 0.9;
    }}

    .item-main {{
      display: grid;
      gap: 9px;
      min-width: 0;
    }}

    .item-title {{
      align-items: start;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}

    .item-title h3 {{
      font-size: 1.04rem;
      line-height: 1.28;
      max-width: 100%;
      overflow-wrap: break-word;
    }}

    .item-title h3 a {{
      color: var(--ink);
      text-decoration-color: var(--accent);
      text-decoration-thickness: 2px;
      text-underline-offset: 3px;
    }}

    .item-title span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      flex: 0 0 auto;
      font-size: 0.72rem;
      font-weight: 800;
      line-height: 1;
      padding: 5px 7px;
    }}

    .item-meta,
    .item-signals {{
      display: flex;
      flex-wrap: wrap;
      font-size: 0.88rem;
      gap: 5px 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}

    .item-meta {{
      color: var(--ink);
      font-weight: 650;
    }}

    .stage-age.stale,
    .follow-up.overdue,
    .follow-up.due-today {{
      color: var(--danger);
      font-weight: 800;
    }}

    .follow-up {{
      color: var(--accent-strong);
      font-weight: 800;
    }}

    .item-actions {{
      border-top: 1px solid var(--line);
      justify-content: start;
      margin-top: 2px;
      padding-top: 10px;
    }}

    .refined-action {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--muted);
      cursor: pointer;
      font-size: 0.82rem;
      font-weight: 750;
      min-height: 30px;
      padding: 0 9px;
      width: auto;
    }}

    .refined-action.positive {{
      background: #edf6f2;
      border-color: #c6ded5;
      color: var(--accent-strong);
    }}

    .refined-action.negative {{
      background: #fff5f4;
      border-color: #efd0cb;
      color: var(--danger);
    }}

    .refined-action:hover {{
      background: var(--ink);
      border-color: var(--ink);
      color: #ffffff;
    }}

    .refined-action:disabled {{
      cursor: not-allowed;
      opacity: 0.6;
    }}

    .empty {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      padding: 12px;
    }}

    .notice {{
      color: var(--danger);
      font-weight: 800;
      min-height: 24px;
    }}

    @media (max-width: 860px) {{
      main {{
        padding: 16px;
      }}

      .topbar {{
        grid-template-columns: 1fr;
      }}

      .top-actions,
      .item-actions {{
        justify-content: start;
      }}

      .refined-lanes {{
        grid-template-columns: repeat({len(statuses)}, minmax(260px, 86vw));
      }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">Application Tracker</p>
          <h1>{escape(workflow_label)}</h1>
          <p class="subhead">{escape(WORKFLOW_PROMPTS[workflow])}</p>
        </div>
        <nav class="top-actions">
          <a class="nav-link primary" href="/jobs/new">Add job</a>
          <a class="nav-link" href="/focus">Focus</a>
          <a class="nav-link" href="/inbox">Inbox</a>
          <a class="nav-link" href="/api/capture/bookmarklet">Capture</a>
          <a class="nav-link" href="/settings#profile">Profile</a>
          <a class="nav-link" href="/settings">Settings</a>
          {'<a class="nav-link" href="/admin">Admin</a>' if user.is_admin else ""}
          <a class="nav-link" href="/board?workflow={escape(workflow, quote=True)}&ui=classic">Classic</a>
        </nav>
      </header>

      <nav class="workflow-tabs" aria-label="Workflow views">
        {_refined_workflow_nav(workflow)}
      </nav>

      <section class="metrics" aria-label="Workflow summary">
        {_refined_status_summary(jobs_by_status, statuses)}
      </section>

      <p class="notice" role="status" aria-live="polite"></p>
      <div class="refined-board" data-statuses="{escape(status_list, quote=True)}">
        {content}
      </div>
    </div>
  </main>
  <script>
    const notice = document.querySelector(".notice");

    async function updateJob(item, status) {{
      const response = await fetch(`/api/jobs/${{item.dataset.jobUuid}}/board`, {{
        method: "PATCH",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{status}})
      }});
      if (!response.ok) {{
        const body = await response.json().catch(() => ({{detail: "Update failed"}}));
        throw new Error(body.detail || "Update failed");
      }}
    }}

    async function updateBoardOrder() {{
      const columns = {{}};
      document.querySelectorAll(".refined-lane").forEach((lane) => {{
        columns[lane.dataset.status] = Array.from(lane.querySelectorAll(".refined-item"))
          .map((item) => item.dataset.jobUuid);
      }});
      const response = await fetch("/api/jobs/board", {{
        method: "PATCH",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{columns}})
      }});
      if (!response.ok) {{
        const body = await response.json().catch(() => ({{detail: "Board update failed"}}));
        throw new Error(body.detail || "Board update failed");
      }}
    }}

    document.addEventListener("click", async (event) => {{
      if (!event.target.classList.contains("refined-action")) {{
        return;
      }}
      const item = event.target.closest(".refined-item");
      const status = event.target.dataset.statusTarget;
      if (!item || !status) {{
        return;
      }}
      event.target.disabled = true;
      notice.textContent = "";
      try {{
        await updateJob(item, status);
        window.location.reload();
      }} catch (error) {{
        notice.textContent = error.message;
        event.target.disabled = false;
      }}
    }});

    let draggedItem = null;

    document.addEventListener("dragstart", (event) => {{
      const item = event.target.closest(".refined-item");
      if (!item) {{
        return;
      }}
      draggedItem = item;
      item.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.dataset.jobUuid);
    }});

    document.addEventListener("dragend", (event) => {{
      const item = event.target.closest(".refined-item");
      if (item) {{
        item.classList.remove("dragging");
      }}
      document.querySelectorAll(".refined-lane.drag-over").forEach((lane) => {{
        lane.classList.remove("drag-over");
      }});
      draggedItem = null;
    }});

    document.querySelectorAll(".refined-lane").forEach((lane) => {{
      lane.addEventListener("dragover", (event) => {{
        if (!draggedItem) {{
          return;
        }}
        event.preventDefault();
        lane.classList.add("drag-over");
        const body = lane.querySelector(".refined-lane-body");
        const afterElement = getDragAfterElement(body, event.clientY);
        if (afterElement === null) {{
          body.appendChild(draggedItem);
        }} else {{
          body.insertBefore(draggedItem, afterElement);
        }}
      }});

      lane.addEventListener("dragleave", () => lane.classList.remove("drag-over"));
      lane.addEventListener("drop", async (event) => {{
        event.preventDefault();
        lane.classList.remove("drag-over");
        if (!draggedItem) {{
          return;
        }}
        notice.textContent = "";
        try {{
          await updateBoardOrder();
          window.location.reload();
        }} catch (error) {{
          notice.textContent = error.message;
          window.location.reload();
        }}
      }});
    }});

    function getDragAfterElement(container, y) {{
      const items = [...container.querySelectorAll(".refined-item:not(.dragging)")];
      return items.reduce((closest, child) => {{
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {{
          return {{offset, element: child}};
        }}
        return closest;
      }}, {{offset: Number.NEGATIVE_INFINITY, element: null}}).element;
    }}
  </script>
</body>
</html>"""


def render_classic_board(user: User, jobs: list[Job], *, workflow: str = "in_progress") -> str:
    statuses = WORKFLOW_VIEWS[workflow]
    jobs_by_status = {status: [] for status in statuses}
    visible_jobs = []
    for job in jobs:
        if job.status in jobs_by_status:
            jobs_by_status[job.status].append(job)
            visible_jobs.append(job)

    if workflow in LIST_WORKFLOWS:
        board_content = _list_view(visible_jobs, workflow)
        board_mode_class = " list-board"
        column_count = 1
    else:
        board_content = "\n".join(
            _column(status, jobs_by_status[status], statuses) for status in statuses
        )
        board_mode_class = ""
        column_count = len(statuses)
    status_list = ",".join(statuses)
    workflow_label = WORKFLOW_LABELS[workflow]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Board - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f9f9f7;
      --ink: #111111;
      --muted: #5f5e5a;
      --line: rgba(0, 0, 0, 0.10);
      --panel: #ffffff;
      --accent: #4f67e4;
      --accent-strong: #2d3a9a;
      --warn: #a43d2b;
      --danger: #b42318;
      --success: #16703f;
      --interested: #0f766e;
      --neutral: #6b7280;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    main {{
      min-height: 100vh;
      padding: 24px;
    }}

    .topbar {{
      align-items: end;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin: 0 auto 24px;
      max-width: 1440px;
    }}

    h1, h2, h3, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
    }}

    .topbar p {{
      color: var(--muted);
      margin-top: 6px;
    }}

    .topbar nav {{
      align-items: center;
      display: flex;
      gap: 12px;
    }}

    .topbar form {{
      margin: 0;
    }}

    .docs-link {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .workflow-nav {{
      margin: 0 auto 18px;
      max-width: 1440px;
    }}

    .workflow-nav label {{
      max-width: 260px;
    }}

    .board {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat({column_count}, minmax(220px, 1fr));
      margin: 0 auto;
      max-width: 1440px;
      overflow-x: auto;
      padding-bottom: 16px;
    }}

    .list-board {{
      display: block;
      max-width: 1120px;
      overflow-x: visible;
    }}

    .list-view {{
      display: grid;
      gap: 10px;
    }}

    .board-column {{
      background: #eef2f4;
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 65vh;
      min-width: 220px;
      padding: 10px;
    }}

    .board-column header {{
      border-bottom: 1px solid var(--line);
      padding: 4px 2px 10px;
    }}

    h2 {{
      font-size: 0.95rem;
      line-height: 1.25;
    }}

    .column-body {{
      display: grid;
      gap: 10px;
      padding-top: 10px;
    }}

    .job-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      cursor: grab;
      display: grid;
      gap: 12px;
      padding: 12px;
    }}

    .job-row {{
      align-items: stretch;
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 5px solid var(--neutral);
      border-radius: 8px;
      display: grid;
      gap: 12px;
      grid-template-columns: minmax(82px, auto) 1fr minmax(98px, auto);
      min-height: 88px;
      padding: 12px;
    }}

    .job-row.status-interested {{
      border-left-color: var(--interested);
      box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.22);
    }}

    .job-row.status-offer {{
      border-left-color: var(--success);
      box-shadow: inset 0 0 0 1px rgba(22, 112, 63, 0.22);
    }}

    .job-row.status-rejected {{
      border-left-color: var(--danger);
      box-shadow: inset 0 0 0 1px rgba(180, 35, 24, 0.2);
    }}

    .job-row.status-archived {{
      border-left-color: var(--neutral);
      opacity: 0.9;
    }}

    .row-edge {{
      align-items: center;
      display: flex;
    }}

    .row-left {{
      justify-content: flex-start;
    }}

    .row-right {{
      justify-content: flex-end;
    }}

    .row-main {{
      display: grid;
      gap: 6px;
      min-width: 0;
    }}

    .row-title-line {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}

    .job-card.dragging {{
      opacity: 0.55;
    }}

    .board-column.drag-over {{
      border-color: var(--accent);
      box-shadow: inset 0 0 0 2px var(--accent);
    }}

    .job-card h3,
    .job-row h3 {{
      font-size: 1rem;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}

    .job-card p,
    .job-row p,
    .row-meta,
    .card-meta,
    .stage-age {{
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}

    .row-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
    }}

    .stage-age.stale {{
      color: var(--warn);
      font-weight: 500;
    }}

    .follow-up {{
      color: var(--accent-strong);
      font-size: 0.88rem;
      font-weight: 500;
      line-height: 1.35;
    }}

    .follow-up.overdue,
    .follow-up.due-today {{
      color: var(--warn);
    }}

    .card-meta {{
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}

    .card-meta a,
    .row-meta a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .job-card h3 a,
    .job-row h3 a {{
      color: var(--ink);
      text-decoration-color: var(--accent);
      text-decoration-thickness: 2px;
      text-underline-offset: 3px;
    }}

    .status-pill,
    .row-state-marker {{
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      flex: 0 0 auto;
      font-size: 0.78rem;
      font-weight: 500;
      line-height: 1;
      padding: 6px 8px;
    }}

    .row-state-marker.reviewed {{
      border-color: rgba(15, 118, 110, 0.35);
      color: var(--interested);
    }}

    .card-actions {{
      display: grid;
      gap: 8px;
      grid-template-columns: 1fr;
    }}

    select {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      min-height: 38px;
      width: 100%;
    }}

    label {{
      display: grid;
      font-size: 0.88rem;
      font-weight: 500;
      gap: 6px;
    }}

    button {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      min-height: 38px;
      width: 100%;
    }}

    button {{
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      font-weight: 500;
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    .row-action {{
      min-height: 34px;
      min-width: 82px;
      padding: 0 10px;
      width: auto;
    }}

    .row-action.archive {{
      background: #ffffff;
      color: var(--danger);
    }}

    .row-action.archive:hover {{
      background: #fff1f0;
    }}

    .row-action.interested {{
      background: var(--accent);
      color: #ffffff;
    }}

    button:disabled {{
      background: #9aa3ad;
      cursor: not-allowed;
    }}

    select {{
      background: #ffffff;
      color: var(--ink);
      padding: 0 8px;
    }}

    .empty {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      padding: 12px;
    }}

    .notice {{
      color: var(--warn);
      font-weight: 500;
      min-height: 24px;
    }}

    @media (max-width: 900px) {{
      main {{
        padding: 16px;
      }}

      .topbar {{
        align-items: start;
        display: grid;
      }}

      .board {{
        grid-template-columns: repeat({column_count}, minmax(240px, 82vw));
      }}

      .list-board {{
        display: block;
      }}

      .job-row {{
        grid-template-columns: 1fr;
      }}

      .row-edge,
      .row-left,
      .row-right {{
        justify-content: stretch;
      }}

      .row-action {{
        width: 100%;
      }}

      .row-title-line {{
        align-items: start;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        <h1>Application Board</h1>
        <p>{escape(user.email)} · {escape(workflow_label)}</p>
      </div>
      <nav>
        <a class="docs-link" href="/jobs/new">Add job</a>
        <a class="docs-link" href="/focus">Focus</a>
        <a class="docs-link" href="/inbox">Inbox</a>
        <a class="docs-link" href="/api/capture/bookmarklet">Capture setup</a>
        <a class="docs-link" href="/settings#profile">Profile</a>
        <a class="docs-link" href="/settings">Settings</a>
        {'<a class="docs-link" href="/admin">Admin</a>' if user.is_admin else ""}
        <a class="docs-link" href="/docs">API docs</a>
        <a class="docs-link" href="/board?workflow={escape(workflow, quote=True)}">Refined</a>
        <form method="post" action="/logout">
          <button type="submit">Sign out</button>
        </form>
      </nav>
    </header>
    <nav class="workflow-nav" aria-label="Workflow views">
      {_workflow_nav(workflow)}
    </nav>
    <p class="notice" role="status" aria-live="polite"></p>
    <div class="board{board_mode_class}" data-statuses="{escape(status_list)}">
      {board_content}
    </div>
  </main>
  <script>
    const statuses = document.querySelector(".board").dataset.statuses.split(",");
    const notice = document.querySelector(".notice");

    async function updateJob(card, status) {{
      const response = await fetch(`/api/jobs/${{card.dataset.jobUuid}}/board`, {{
        method: "PATCH",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{status}})
      }});

      if (!response.ok) {{
        const body = await response.json().catch(() => ({{detail: "Update failed"}}));
        throw new Error(body.detail || "Update failed");
      }}
    }}

    async function updateBoardOrder() {{
      const columns = {{}};
      document.querySelectorAll(".board-column").forEach((column) => {{
        columns[column.dataset.status] = Array.from(column.querySelectorAll(".job-card"))
          .map((card) => card.dataset.jobUuid);
      }});

      const response = await fetch("/api/jobs/board", {{
        method: "PATCH",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{columns}})
      }});

      if (!response.ok) {{
        const body = await response.json().catch(() => ({{detail: "Board update failed"}}));
        throw new Error(body.detail || "Board update failed");
      }}
    }}

    document.addEventListener("change", async (event) => {{
      if (event.target.classList.contains("workflow-select")) {{
        window.location.href = `/board?workflow=${{event.target.value}}&ui=classic`;
        return;
      }}

      if (!event.target.classList.contains("job-status-select")) {{
        return;
      }}

      const card = event.target.closest(".job-card");
      const column = card.closest(".board-column");
      if (event.target.value === column.dataset.status) {{
        return;
      }}

      event.target.disabled = true;
      notice.textContent = "";
      try {{
        await updateJob(card, event.target.value);
        window.location.reload();
      }} catch (error) {{
        notice.textContent = error.message;
        event.target.disabled = false;
      }}
    }});

    document.addEventListener("click", async (event) => {{
      if (!event.target.classList.contains("row-status-action")) {{
        return;
      }}

      const row = event.target.closest(".job-row");
      const status = event.target.dataset.statusTarget;
      if (!row || !status) {{
        return;
      }}

      event.target.disabled = true;
      notice.textContent = "";
      try {{
        await updateJob(row, status);
        window.location.reload();
      }} catch (error) {{
        notice.textContent = error.message;
        event.target.disabled = false;
      }}
    }});

    let draggedCard = null;

    document.addEventListener("dragstart", (event) => {{
      const card = event.target.closest(".job-card");
      if (!card) {{
        return;
      }}

      draggedCard = card;
      card.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.jobUuid);
    }});

    document.addEventListener("dragend", (event) => {{
      const card = event.target.closest(".job-card");
      if (card) {{
        card.classList.remove("dragging");
      }}
      document.querySelectorAll(".board-column.drag-over").forEach((column) => {{
        column.classList.remove("drag-over");
      }});
      draggedCard = null;
    }});

    document.querySelectorAll(".board-column").forEach((column) => {{
      column.addEventListener("dragover", (event) => {{
        if (!draggedCard) {{
          return;
        }}

        event.preventDefault();
        column.classList.add("drag-over");
        const body = column.querySelector(".column-body");
        const afterElement = getDragAfterElement(body, event.clientY);
        if (afterElement === null) {{
          body.appendChild(draggedCard);
        }} else {{
          body.insertBefore(draggedCard, afterElement);
        }}
      }});

      column.addEventListener("dragleave", () => {{
        column.classList.remove("drag-over");
      }});

      column.addEventListener("drop", async (event) => {{
        event.preventDefault();
        column.classList.remove("drag-over");
        if (!draggedCard) {{
          return;
        }}

        notice.textContent = "";
        try {{
          await updateBoardOrder();
          window.location.reload();
        }} catch (error) {{
          notice.textContent = error.message;
          window.location.reload();
        }}
      }});
    }});

    function getDragAfterElement(container, y) {{
      const cards = [...container.querySelectorAll(".job-card:not(.dragging)")];
      return cards.reduce((closest, child) => {{
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {{
          return {{offset, element: child}};
        }}
        return closest;
      }}, {{offset: Number.NEGATIVE_INFINITY, element: null}}).element;
    }}
  </script>
</body>
</html>"""


def render_board(
    user: User,
    jobs: list[Job],
    *,
    workflow: str = "in_progress",
    ui: str = "refined",
) -> str:
    if ui == "classic":
        return render_classic_board(user, jobs, workflow=workflow)
    return render_refined_board(user, jobs, workflow=workflow)


@router.get("/board", response_class=HTMLResponse)
def board(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    workflow: Annotated[str, Query()] = "in_progress",
    ui: Annotated[str, Query()] = "refined",
) -> HTMLResponse:
    if workflow not in WORKFLOW_VIEWS:
        workflow = "in_progress"
    if ui not in {"refined", "classic"}:
        ui = "refined"
    jobs = list_user_jobs(db, current_user, include_archived=workflow == "archived")
    return HTMLResponse(render_board(current_user, jobs, workflow=workflow, ui=ui))
