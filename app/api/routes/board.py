from collections.abc import Iterable
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.api.deps import DbSession, get_current_user
from app.db.models.job import Job
from app.db.models.user import User
from app.services.jobs import BOARD_STATUSES, JOB_STATUSES, list_user_jobs

router = APIRouter(tags=["board"])

BOARD_LABELS = {
    "saved": "Saved",
    "interested": "Interested",
    "preparing": "Preparing",
    "applied": "Applied",
    "interviewing": "Interviewing",
    "offer": "Offer",
    "rejected": "Rejected",
}


def _status_options(current_status: str) -> str:
    options = []
    for job_status in JOB_STATUSES:
        label = BOARD_LABELS.get(job_status, job_status.title())
        selected = " selected" if job_status == current_status else ""
        options.append(f'<option value="{escape(job_status)}"{selected}>{escape(label)}</option>')
    return "\n".join(options)


def _job_card(job: Job) -> str:
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
        <h3>{escape(job.title)}</h3>
        {company}
        {location}
      </div>
      <div class="card-meta">
        <span>Position {job.board_position}</span>
        {source_link}
      </div>
      <div class="card-actions">
        <button type="button" data-move="previous">Previous</button>
        <select aria-label="Status for {escape(job.title, quote=True)}">
          {_status_options(job.status)}
        </select>
        <button type="button" data-move="next">Next</button>
      </div>
    </article>
    """


def _column(status: str, jobs: Iterable[Job]) -> str:
    cards = "\n".join(_job_card(job) for job in jobs)
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


def render_board(user: User, jobs: list[Job]) -> str:
    jobs_by_status = {status: [] for status in BOARD_STATUSES}
    for job in jobs:
        if job.status in jobs_by_status:
            jobs_by_status[job.status].append(job)

    columns = "\n".join(_column(status, jobs_by_status[status]) for status in BOARD_STATUSES)
    status_list = ",".join(BOARD_STATUSES)
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

    .board {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(7, minmax(220px, 1fr));
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
    .card-meta {{
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
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

    .card-actions {{
      display: grid;
      gap: 8px;
      grid-template-columns: 1fr;
    }}

    button,
    select {{
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
        grid-template-columns: repeat(7, minmax(240px, 82vw));
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        <h1>Application Board</h1>
        <p>{escape(user.email)}</p>
      </div>
      <nav>
        <a class="docs-link" href="/docs">API docs</a>
        <form method="post" action="/logout">
          <button type="submit">Sign out</button>
        </form>
      </nav>
    </header>
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

    function nextStatus(current, direction) {{
      const index = statuses.indexOf(current);
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= statuses.length) {{
        return current;
      }}
      return statuses[nextIndex];
    }}

    document.addEventListener("click", async (event) => {{
      const button = event.target.closest("button[data-move]");
      if (!button) {{
        return;
      }}

      const card = button.closest(".job-card");
      const column = card.closest(".board-column");
      const direction = button.dataset.move === "next" ? 1 : -1;
      const status = nextStatus(column.dataset.status, direction);
      if (status === column.dataset.status) {{
        return;
      }}

      button.disabled = true;
      notice.textContent = "";
      try {{
        await updateJob(card, status);
        window.location.reload();
      }} catch (error) {{
        notice.textContent = error.message;
        button.disabled = false;
      }}
    }});

    document.addEventListener("change", async (event) => {{
      if (event.target.tagName !== "SELECT") {{
        return;
      }}

      const card = event.target.closest(".job-card");
      notice.textContent = "";
      try {{
        await updateJob(card, event.target.value);
        window.location.reload();
      }} catch (error) {{
        notice.textContent = error.message;
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
) -> HTMLResponse:
    jobs = list_user_jobs(db, current_user)
    return HTMLResponse(render_board(current_user, jobs))
