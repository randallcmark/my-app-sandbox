from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import DbSession, get_current_user, require_capture_jobs_api_token
from app.api.routes.ui import compact_content_rhythm_styles, render_shell_page
from app.db.models.job import Job
from app.db.models.user import User
from app.services.capture import capture_job
from app.services.extraction import extract_job_capture

router = APIRouter(prefix="/api/capture", tags=["capture"])


class CaptureJobRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=2048)
    apply_url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    description: str | None = None
    selected_text: str | None = None
    source_platform: str | None = Field(default=None, max_length=100)
    raw_extraction_metadata: dict | None = None
    raw_html: str | None = None

    @model_validator(mode="after")
    def require_capture_content(self) -> "CaptureJobRequest":
        if not self.title and not self.source_url and not self.raw_html and not self.selected_text:
            raise ValueError("Capture requires at least a title, source_url, raw_html, or selected_text")
        return self


class CaptureJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    title: str
    company: str | None
    status: str
    source_url: str | None
    apply_url: str | None
    created: bool


def _response(job: Job, *, created: bool) -> CaptureJobResponse:
    return CaptureJobResponse(
        uuid=job.uuid,
        title=job.title,
        company=job.company,
        status=job.status,
        source_url=job.source_url,
        apply_url=job.apply_url,
        created=created,
    )


def _bookmarklet_javascript(base_url: str, token: str) -> str:
    base_url_literal = repr(base_url.rstrip("/"))
    token_literal = repr(token)
    return f"""javascript:(async()=>{{const base={base_url_literal};const token={token_literal};function text(x){{return(x||'').replace(/\\s+/g,' ').trim();}}function findJobPosting(){{for(const s of document.querySelectorAll('script[type="application/ld+json"]')){{try{{const raw=JSON.parse(s.textContent||'null');const items=Array.isArray(raw)?raw:[raw];for(const item of items){{const graph=item&&item['@graph'];const candidates=Array.isArray(graph)?graph.concat(items):items;for(const c of candidates){{const type=c&&c['@type'];const types=Array.isArray(type)?type:[type];if(types.includes('JobPosting'))return c;}}}}catch(e){{}}}}return null;}}const job=findJobPosting()||{{}};const selected=String(window.getSelection?window.getSelection():'').trim();const body=text(document.body?document.body.innerText:'').slice(0,20000);const rawHtml=document.documentElement?document.documentElement.outerHTML.slice(0,200000):null;const title=text(job.title)||text(document.querySelector('h1')&&document.querySelector('h1').innerText)||text(document.title)||location.href;const payload={{source_url:location.href,apply_url:location.href,title,description:selected||body,selected_text:selected||null,source_platform:location.hostname,raw_html:rawHtml,raw_extraction_metadata:{{extractor:'bookmarklet',page_title:document.title,body_text:body,json_ld_job_posting:Boolean(job.title),captured_at:new Date().toISOString()}}}};try{{const r=await fetch(base+'/api/capture/jobs',{{method:'POST',headers:{{'Authorization':'Bearer '+token,'Content-Type':'application/json'}},body:JSON.stringify(payload)}});const data=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(data.detail||'Capture failed');alert((data.created?'Captured: ':'Updated existing job: ')+data.title);}}catch(e){{alert('Application Tracker capture failed: '+e.message);}}}})();"""


def render_bookmarklet_setup(request: Request, user: User) -> str:
    base_url = str(request.base_url).rstrip("/")
    bookmarklet_preview = escape(_bookmarklet_javascript(base_url, "PASTE_TOKEN_HERE"), quote=True)
    extra_styles = compact_content_rhythm_styles() + """
    input, textarea {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }
    textarea { min-height: 120px; }
    .bookmarklet {
      background: var(--accent);
      border-radius: 10px;
      color: #ffffff;
      display: inline-block;
      justify-self: start;
      padding: 9px 12px;
      text-decoration: none;
    }
    .hint { font-size: 0.92rem; }
    """
    body = f"""
    <section>
      <h2>1. Create a capture token</h2>
      <p>Create a scoped API token named Browser bookmarklet from Settings. Paste the one-time token below. It is only used in your browser to generate the bookmarklet link.</p>
      <p><a href="/settings">Open Settings</a></p>
    </section>
    <section>
      <h2>2. Generate bookmarklet</h2>
      <label>
        Tracker URL
        <input id="base-url" value="{base_url}">
      </label>
      <label>
        Capture token
        <input id="capture-token" placeholder="ats_..." autocomplete="off">
      </label>
      <a id="bookmarklet-link" class="bookmarklet" href="{bookmarklet_preview}">Capture job</a>
      <p class="hint">Drag Capture job to your bookmarks bar. On a job page, click it to save the current URL, title, selected text, page text, and any JSON-LD JobPosting data into the tracker.</p>
    </section>
    <section>
      <h2>Generated code</h2>
      <textarea id="bookmarklet-code" readonly></textarea>
    </section>
    """
    scripts = f"""
  <script>
    function bookmarklet(base, token) {{
      return {_bookmarklet_javascript("__BASE__", "__TOKEN__")!r}.replace("'__BASE__'", JSON.stringify(base.replace(/\\/$/, ""))).replace("'__TOKEN__'", JSON.stringify(token));
    }}

    function refresh() {{
      const base = document.getElementById("base-url").value.trim();
      const token = document.getElementById("capture-token").value.trim() || "PASTE_TOKEN_HERE";
      const code = bookmarklet(base, token);
      document.getElementById("bookmarklet-code").value = code;
      document.getElementById("bookmarklet-link").href = code;
    }}

    document.getElementById("base-url").addEventListener("input", refresh);
    document.getElementById("capture-token").addEventListener("input", refresh);
    refresh();
  </script>
"""
    return render_shell_page(
        user,
        page_title="Capture setup",
        title="Capture setup",
        subtitle="Configure bookmarklet and extension capture",
        active="capture",
        body=body,
        kicker="Capture",
        container="standard",
        extra_styles=extra_styles,
        scripts=scripts,
    )


@router.get("/bookmarklet", response_class=HTMLResponse, include_in_schema=False)
def bookmarklet_setup(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return HTMLResponse(render_bookmarklet_setup(request, current_user))


@router.post("/jobs", response_model=CaptureJobResponse, status_code=status.HTTP_201_CREATED)
def capture_job_route(
    payload: CaptureJobRequest,
    response: Response,
    db: DbSession,
    owner: Annotated[User, Depends(require_capture_jobs_api_token)],
) -> CaptureJobResponse:
    extracted = extract_job_capture(
        source_url=payload.source_url,
        apply_url=payload.apply_url,
        title=payload.title,
        company=payload.company,
        location=payload.location,
        description=payload.description,
        selected_text=payload.selected_text,
        source_platform=payload.source_platform,
        raw_extraction_metadata=payload.raw_extraction_metadata,
        raw_html=payload.raw_html,
    )
    title = (extracted.title or payload.source_url or "").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job title is required")

    job, created = capture_job(
        db,
        owner,
        title=title,
        company=extracted.company,
        source_url=payload.source_url,
        apply_url=extracted.apply_url,
        location=extracted.location,
        description=extracted.description,
        selected_text=extracted.selected_text,
        source_platform=extracted.source_platform,
        raw_extraction_metadata=extracted.raw_extraction_metadata,
        raw_html=extracted.raw_html,
        extraction={
            "warnings": extracted.warnings,
            "confidence": extracted.confidence,
        },
    )
    db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return _response(job, created=created)
