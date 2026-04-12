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

WORKFLOW_LABELS = {
    "prospects": "Prospects",
    "in_progress": "In Progress",
    "outcomes": "Outcomes",
    "all": "All Active",
    "archived": "Archived",
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


def render_board(user: User, jobs: list[Job], *, workflow: str = "in_progress") -> str:
    statuses = WORKFLOW_VIEWS[workflow]
    jobs_by_status = {status: [] for status in statuses}
    for job in jobs:
        if job.status in jobs_by_status:
            jobs_by_status[job.status].append(job)

    columns = "\n".join(_column(status, jobs_by_status[status], statuses) for status in statuses)
    status_list = ",".join(statuses)
    column_count = len(statuses)
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
      --page: #f6f7f9;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --panel: #ffffff;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
      --warn: #a43d2b;
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
      font-weight: 700;
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

    .job-card.dragging {{
      opacity: 0.55;
    }}

    .board-column.drag-over {{
      border-color: var(--accent);
      box-shadow: inset 0 0 0 2px var(--accent);
    }}

    .job-card h3 {{
      font-size: 1rem;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}

    .job-card p,
    .card-meta,
    .stage-age {{
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}

    .stage-age.stale {{
      color: var(--warn);
      font-weight: 700;
    }}

    .follow-up {{
      color: var(--accent-strong);
      font-size: 0.88rem;
      font-weight: 700;
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

    .card-meta a {{
      color: var(--accent-strong);
      font-weight: 700;
    }}

    .job-card h3 a {{
      color: var(--ink);
      text-decoration-color: var(--accent);
      text-decoration-thickness: 2px;
      text-underline-offset: 3px;
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
      font-weight: 700;
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
      font-weight: 700;
    }}

    button:hover {{
      background: var(--accent-strong);
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
      font-weight: 700;
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
        <a class="docs-link" href="/api/capture/bookmarklet">Capture setup</a>
        <a class="docs-link" href="/settings">Settings</a>
        <a class="docs-link" href="/docs">API docs</a>
        <form method="post" action="/logout">
          <button type="submit">Sign out</button>
        </form>
      </nav>
    </header>
    <nav class="workflow-nav" aria-label="Workflow views">
      {_workflow_nav(workflow)}
    </nav>
    <p class="notice" role="status" aria-live="polite"></p>
    <div class="board" data-statuses="{escape(status_list)}">
      {columns}
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
        window.location.href = `/board?workflow=${{event.target.value}}`;
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


@router.get("/board", response_class=HTMLResponse)
def board(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    workflow: Annotated[str, Query()] = "in_progress",
) -> HTMLResponse:
    if workflow not in WORKFLOW_VIEWS:
        workflow = "in_progress"
    jobs = list_user_jobs(db, current_user, include_archived=workflow == "archived")
    return HTMLResponse(render_board(current_user, jobs, workflow=workflow))
