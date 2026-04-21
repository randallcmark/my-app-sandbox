from datetime import datetime
from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.deps import DbSession, get_current_user
from app.api.routes.ui import compact_content_rhythm_styles, render_shell_page
from app.db.models.artefact import Artefact
from app.db.models.user import User
from app.services.artefacts import (
    get_user_artefact_by_uuid,
    list_user_artefacts,
    update_artefact_metadata,
)
from app.storage.provider import get_storage_provider

router = APIRouter(tags=["artefacts"])


def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _size(value: int | None) -> str:
    if value is None:
        return "Size not set"
    if value < 1024:
        return f"{value} bytes"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def _artefact_card(artefact: Artefact) -> str:
    linked_jobs = {link.job.id: link.job for link in artefact.job_links}
    if artefact.job:
        linked_jobs[artefact.job.id] = artefact.job
    job_links = "\n".join(
        f'<li><a href="/jobs/{escape(job.uuid, quote=True)}">{escape(job.title)}</a>'
        f'<span>{escape(job.company or "Company not set")}</span></li>'
        for job in sorted(linked_jobs.values(), key=lambda item: item.title.lower())
    )
    if not job_links:
        job_links = '<li><span class="muted">No linked jobs</span></li>'
    purpose = artefact.purpose or "Purpose not set"
    version = artefact.version_label or "Version not set"
    notes = f"<p>{escape(artefact.notes)}</p>" if artefact.notes else ""
    return f"""
    <article class="artefact-card">
      <div>
        <p class="eyebrow">{escape(artefact.kind)}</p>
        <h2>{escape(artefact.filename)}</h2>
        <p class="meta">{escape(_size(artefact.size_bytes))} · Updated {escape(_value(artefact.updated_at))}</p>
      </div>
      <dl>
        <div>
          <dt>Purpose</dt>
          <dd>{escape(purpose)}</dd>
        </div>
        <div>
          <dt>Version</dt>
          <dd>{escape(version)}</dd>
        </div>
      </dl>
      {notes}
      <div>
        <p class="eyebrow">Linked jobs</p>
        <ol class="linked-jobs">{job_links}</ol>
      </div>
      <details>
        <summary>Edit metadata</summary>
        <form class="metadata-form" method="post" action="/artefacts/{escape(artefact.uuid, quote=True)}/metadata">
          <label>
            Kind
            <input name="kind" value="{escape(artefact.kind, quote=True)}" maxlength="100">
          </label>
          <label>
            Purpose
            <input name="purpose" value="{escape(artefact.purpose or "", quote=True)}" maxlength="300" placeholder="Tailored resume, cover letter, interview prep">
          </label>
          <label>
            Version label
            <input name="version_label" value="{escape(artefact.version_label or "", quote=True)}" maxlength="100" placeholder="Product roles v2">
          </label>
          <label>
            Outcome context
            <input name="outcome_context" value="{escape(artefact.outcome_context or "", quote=True)}" maxlength="300" placeholder="Used for interview invite, rejected, offer">
          </label>
          <label>
            Notes
            <textarea name="notes" rows="3">{escape(artefact.notes or "")}</textarea>
          </label>
          <button type="submit">Save metadata</button>
        </form>
      </details>
      <div class="actions">
        <a class="button" href="/artefacts/{escape(artefact.uuid, quote=True)}/download">Download</a>
      </div>
    </article>
    """


def render_artefact_library(user: User, artefacts: list[Artefact]) -> HTMLResponse:
    cards = "\n".join(_artefact_card(artefact) for artefact in artefacts)
    if not cards:
        cards = """
        <section class="empty-state">
          <h2>No artefacts yet</h2>
          <p>Upload resumes, cover letters, notes, or prep files from a job workspace.</p>
          <a class="button" href="/board">Find a job workspace</a>
        </section>
        """
    extra_styles = compact_content_rhythm_styles() + """
    h2 { overflow-wrap: anywhere; }
    .muted, .meta, .empty-state p { color: var(--muted); }
    .eyebrow, dt {
      color: var(--muted);
      font-size: 0.76rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .library-grid {
      align-items: start;
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .artefact-card, .empty-state {
      background: var(--panel);
      border: 0.5px solid var(--line);
      border-radius: 14px;
      display: grid;
      gap: 16px;
      padding: 18px;
    }
    dl {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 0;
    }
    dd { margin: 3px 0 0; overflow-wrap: anywhere; }
    details { border-top: 0.5px solid var(--line); padding-top: 12px; }
    summary { color: var(--accent-strong); cursor: pointer; font-weight: 500; }
    .metadata-form { gap: 8px; }
    label { color: var(--muted); font-size: 0.86rem; }
    input, textarea {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      color: var(--ink);
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }
    .linked-jobs {
      display: grid;
      gap: 8px;
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
    }
    .linked-jobs li { display: grid; gap: 2px; }
    .linked-jobs span { color: var(--muted); }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .button, button {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      display: inline-flex;
      font: inherit;
      font-weight: 500;
      min-height: 36px;
      padding: 8px 10px;
      text-decoration: none;
    }
    .button, button { align-items: center; cursor: pointer; justify-content: center; }
    .button:not(.secondary), button {
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }
    @media (max-width: 760px) {
      .library-grid, dl { grid-template-columns: 1fr; }
      .actions, .actions .button { width: 100%; }
    }
    """
    body = f"""
    <div class="library-grid">
      {cards}
    </div>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Artefacts",
            title="Artefacts",
            subtitle="Resumes, cover letters, notes, and prep files",
            active="artefacts",
            actions=(("Add job", "/jobs/new", "add-job"),),
            body=body,
            kicker="Library",
            container="wide",
            extra_styles=extra_styles,
        )
    )


@router.get("/artefacts", response_class=HTMLResponse, include_in_schema=False)
def artefact_library(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return render_artefact_library(current_user, list_user_artefacts(db, current_user))


@router.post("/artefacts/{artefact_uuid}/metadata", include_in_schema=False)
def update_artefact_metadata_form(
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    kind: Annotated[str, Form()] = "other",
    purpose: Annotated[str, Form()] = "",
    version_label: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    outcome_context: Annotated[str, Form()] = "",
) -> RedirectResponse:
    artefact = get_user_artefact_by_uuid(db, current_user, artefact_uuid)
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    update_artefact_metadata(
        artefact,
        kind=kind,
        purpose=purpose,
        version_label=version_label,
        notes=notes,
        outcome_context=outcome_context,
    )
    db.commit()
    return RedirectResponse(url="/artefacts", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/artefacts/{artefact_uuid}/download", include_in_schema=False)
def download_artefact(
    artefact_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    artefact = get_user_artefact_by_uuid(db, current_user, artefact_uuid)
    if artefact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    content = get_storage_provider().load(artefact.storage_key)
    filename = quote(artefact.filename)
    return Response(
        content=content,
        media_type=artefact.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
