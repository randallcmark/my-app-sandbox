from collections.abc import Iterable
from datetime import UTC, datetime
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import render_shell_page
from app.db.models.job import Job
from app.db.models.user import User
from app.services.jobs import BOARD_STATUSES, list_user_jobs

router = APIRouter(tags=["board"])


def _icon(path: str, *, w: int = 14, h: int = 14) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 20 20" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{path}</svg>'
    )


_ICON_KEEP     = _icon('<polygon points="10 2 12.5 7.5 18.5 8.2 14 12.5 15.4 18.5 10 15.3 4.6 18.5 6 12.5 1.5 8.2 7.5 7.5"/>')
_ICON_PENCIL   = _icon('<path d="M13.5 2.5l4 4L6.5 18H2.5v-4L13.5 2.5z"/>')
_ICON_SEND     = _icon('<path d="M17.5 2.5L2 9l6 2 2 7 7.5-15.5z"/><line x1="8" y1="11" x2="17.5" y2="2.5"/>')
_ICON_CHAT     = _icon('<path d="M3 3h14a1 1 0 011 1v9a1 1 0 01-1 1H8l-5 3V4a1 1 0 011-1z"/>')
_ICON_CLOCK    = _icon('<circle cx="10" cy="10" r="8"/><polyline points="10 5.5 10 10 13 12.5"/>')
_ICON_ARCHIVE  = _icon('<rect x="3" y="7" width="14" height="9.5" rx="1"/><rect x="2" y="4" width="16" height="3" rx="0.75"/><line x1="8" y1="12" x2="12" y2="12"/>')
_ICON_OFFER    = _icon('<rect x="2" y="8.5" width="16" height="9" rx="1"/><path d="M7 8.5V6a3 3 0 016 0v2.5"/><line x1="2" y1="12.5" x2="18" y2="12.5"/>')
_ICON_REJECT   = _icon('<circle cx="10" cy="10" r="8"/><line x1="6" y1="10" x2="14" y2="10"/>')
_ICON_UNDO     = _icon('<polyline points="3 8 3 3 8 3"/><path d="M3 3a9 9 0 100 14"/>')
_ICON_CHECK    = _icon('<polyline points="3 10 8 15 17 5"/>')

_BOARD_ACTION_ICONS: dict[str, str] = {
    "interested":   _ICON_KEEP,
    "archived":     _ICON_ARCHIVE,
    "preparing":    _ICON_PENCIL,
    "applied":      _ICON_SEND,
    "interviewing": _ICON_CHAT,
    "offer":        _ICON_OFFER,
    "rejected":     _ICON_REJECT,
    "saved":        _ICON_CLOCK,
    "restored":     _ICON_UNDO,
}

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


def _refined_workflow_nav(current_workflow: str) -> str:
    links = []
    for workflow, label in WORKFLOW_LABELS.items():
        active = " active" if workflow == current_workflow else ""
        links.append(
            f'<a class="workflow-tab{active}" href="/board?workflow={escape(workflow, quote=True)}">'
            f"{escape(label)}</a>"
        )
    return "\n".join(links)


def _refined_action_buttons(job: Job) -> str:
    buttons = []
    for target_status, label in REFINED_STATUS_ACTIONS.get(job.status, ()):
        intent = "positive" if target_status in {"interested", "preparing", "applied", "interviewing", "offer", "saved"} else "quiet"
        if target_status in {"archived", "rejected"}:
            intent = "negative"
        icon = _BOARD_ACTION_ICONS.get(target_status, "")
        buttons.append(
            '<button class="refined-action '
            f'{escape(intent, quote=True)}" type="button" '
            f'data-status-target="{escape(target_status, quote=True)}">'
            f'{icon}<span>{escape(label)}</span></button>'
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
    job_list = list(jobs)
    cards = "\n".join(_refined_item(job, draggable=True, show_status=False) for job in job_list)
    empty = '<p class="empty refined-empty">Nothing here.</p>' if not cards else ""
    return f"""
    <section class="refined-lane" data-status="{escape(status_name, quote=True)}">
      <header>
        <h2>{escape(BOARD_LABELS[status_name])} <span class="lane-count">{len(job_list)}</span></h2>
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
    extra_styles = f"""
    :root {{
      --soft: #f1f0ed;
      --danger: #d64535;
      --danger-soft: #fdefed;
      --success: #2a8a58;
      --success-soft: #eaf4ee;
      --amber: #b87800;
      --amber-soft: #fdf3e6;
      --slate-soft: #e8ebf8;
    }}

    h1, h2, h3, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 1.5rem;
      letter-spacing: 0;
      line-height: 1.08;
      font-weight: 500;
    }}

    .item-meta,
    .item-signals,
    .refined-lane header span {{
      color: var(--muted);
    }}

    .workflow-tabs,
    .item-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .workflow-tab,
    .refined-action,
    button {{
      border-radius: 10px;
      font: inherit;
      min-height: 36px;
    }}

    .workflow-tab {{
      align-items: center;
      background: rgba(255,255,255,0.82);
      border: 1px solid var(--line-soft);
      box-shadow: var(--shadow-sm);
      color: var(--ink);
      display: inline-flex;
      font-size: 0.88rem;
      padding: 0 12px;
      text-decoration: none;
    }}

    .workflow-tab.active {{
      background: var(--slate-soft);
      border-color: #c3ccf0;
      color: var(--accent-strong);
    }}

    .workflow-tabs {{
      margin-bottom: 14px;
    }}

    .refined-list,
    .refined-lane-body {{
      display: grid;
      gap: 10px;
    }}

    .refined-lanes {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat({len(statuses)}, minmax(250px, 1fr));
      overflow-x: auto;
      padding-bottom: 14px;
    }}

    .refined-lane {{
      background: rgba(255,255,255,0.60);
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.48);
      min-height: 58vh;
      min-width: 250px;
      padding: 12px;
    }}

    .refined-lane header {{
      align-items: center;
      display: flex;
      justify-content: space-between;
      padding: 4px 2px 10px;
    }}

    h2 {{
      font-size: 0.98rem;
      line-height: 1.25;
    }}

    .lane-count {{
      border: 0.5px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      display: inline-flex;
      font-size: 0.76rem;
      font-weight: 500;
      line-height: 1;
      margin-left: 8px;
      padding: 4px 7px;
      vertical-align: middle;
    }}

    .refined-item {{
      background: linear-gradient(180deg, #ffffff, rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-left: 3px solid var(--accent);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-sm);
      display: block;
      min-height: 112px;
      padding: 14px;
      transition: box-shadow 140ms ease-out, transform 140ms ease-out;
    }}

    .refined-item:hover {{
      box-shadow: 0 4px 18px rgba(16, 34, 52, 0.13);
      transform: translateY(-1px);
    }}

    .refined-item[draggable="true"] {{
      cursor: grab;
    }}

    .refined-item.dragging {{
      opacity: 0.55;
      transform: none;
    }}

    .refined-lane.drag-over {{
      border-color: var(--accent);
      background: #ffffff;
    }}

    .refined-item.status-saved,
    .refined-item.status-preparing,
    .refined-item.status-applied {{
      border-left-color: var(--accent);
    }}

    .refined-item.status-interested {{
      border-left-color: var(--amber);
    }}

    .refined-item.status-interviewing,
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
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(0, 1fr) auto;
      justify-content: space-between;
    }}

    .item-title h3 {{
      font-size: 1rem;
      font-weight: 500;
      line-height: 1.3;
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
      border: 0.5px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      flex: 0 0 auto;
      font-size: 0.73rem;
      font-weight: 500;
      letter-spacing: 0.02em;
      line-height: 1;
      padding: 5px 7px;
    }}

    .refined-item.status-interested .item-title span {{
      background: var(--amber-soft);
      border-color: #f9d9a0;
      color: var(--amber);
    }}

    .refined-item.status-preparing .item-title span,
    .refined-item.status-applied .item-title span {{
      background: var(--slate-soft);
      border-color: #c3ccf0;
      color: var(--accent-strong);
    }}

    .refined-item.status-interviewing .item-title span,
    .refined-item.status-offer .item-title span {{
      background: var(--success-soft);
      border-color: #b6dfc5;
      color: var(--success);
    }}

    .refined-item.status-rejected .item-title span {{
      background: var(--danger-soft);
      border-color: #f8c4be;
      color: var(--danger);
    }}

    .item-meta,
    .item-signals {{
      display: flex;
      flex-wrap: wrap;
      font-size: 0.86rem;
      gap: 5px 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}

    .item-meta {{
      color: var(--ink);
      font-weight: 500;
    }}

    .stage-age.stale,
    .follow-up.overdue,
    .follow-up.due-today {{
      color: var(--danger);
      font-weight: 500;
    }}

    .follow-up {{
      color: var(--accent-strong);
      font-weight: 500;
    }}

    .item-actions {{
      border-top: 1px solid var(--line-soft);
      justify-content: start;
      margin-top: 2px;
      padding-top: 10px;
    }}

    .refined-action {{
      align-items: center;
      background: transparent;
      border: 0.5px solid transparent;
      border-radius: 10px;
      color: var(--muted);
      cursor: pointer;
      display: inline-flex;
      font-size: 0.82rem;
      font-weight: 500;
      gap: 5px;
      min-height: 32px;
      padding: 0 10px;
      transition: background 120ms ease-out, color 120ms ease-out, border-color 120ms ease-out;
      width: auto;
    }}

    .refined-action svg {{ flex-shrink: 0; }}

    .refined-action.positive {{
      background: var(--slate-soft);
      border-color: #c3ccf0;
      color: var(--accent-strong);
    }}

    .refined-action.negative {{
      background: var(--danger-soft);
      border-color: #f8c4be;
      color: var(--danger);
    }}

    .refined-action:hover:not(:disabled) {{
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }}

    .refined-action:disabled {{
      cursor: not-allowed;
      opacity: 0.6;
    }}

    .empty {{
      border: 0.5px dashed var(--line);
      border-radius: 10px;
      color: var(--muted);
      padding: 12px;
    }}

    .notice {{
      color: var(--danger);
      font-weight: 500;
      min-height: 24px;
    }}

    @media (max-width: 860px) {{
      .item-actions {{
        justify-content: start;
      }}

      .refined-lanes {{
        grid-template-columns: repeat({len(statuses)}, minmax(260px, 86vw));
      }}

      .workflow-tabs {{
        flex-wrap: nowrap;
        overflow-x: auto;
        padding-bottom: 5px;
        -webkit-overflow-scrolling: touch;
      }}

      .workflow-tab {{
        flex: 0 0 auto;
      }}

      .item-title {{
        grid-template-columns: 1fr;
      }}

      .item-title span {{
        justify-self: start;
      }}

      .item-actions {{
        gap: 6px;
      }}

      .refined-action {{
        min-height: 34px;
      }}
    }}
    """
    body = f"""
    <nav class="workflow-tabs" aria-label="Workflow views">
      {_refined_workflow_nav(workflow)}
    </nav>

    <p class="notice" role="status" aria-live="polite"></p>
    <div class="refined-board" data-statuses="{escape(status_list, quote=True)}">
      {content}
    </div>
    """
    scripts = f"""
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
"""
    return render_shell_page(
        user,
        page_title=workflow_label,
        title="",
        subtitle="",
        active="board",
        show_hero=False,
        actions=(("Add job", "/jobs/new", "add-job"),),
        body=body,
        goal=f"<span>Workflow:</span> <strong>{escape(workflow_label)}</strong>",
        container="kanban",
        extra_styles=extra_styles,
        scripts=scripts,
    )


@router.get("/board", response_class=HTMLResponse)
def board(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    workflow: Annotated[str, Query()] = "in_progress",
    ui: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    if workflow not in WORKFLOW_VIEWS:
        workflow = "in_progress"
    _ = ui  # Backward-compatible query parameter; refined board is always rendered.
    jobs = list_user_jobs(db, current_user, include_archived=workflow == "archived")
    return HTMLResponse(render_refined_board(current_user, jobs, workflow=workflow))
