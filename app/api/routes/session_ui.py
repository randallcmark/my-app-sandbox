from html import escape
from typing import Annotated

from fastapi import APIRouter, Cookie, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import DbSession
from app.api.routes.auth import authenticate_local_user, create_login_session
from app.auth.csrf import clear_csrf_cookie
from app.auth.sessions import revoke_session
from app.core.config import settings

router = APIRouter(tags=["session-ui"])


def login_page(*, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
      --error: #a43d2b;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      align-items: center;
      background: var(--page);
      color: var(--ink);
      display: grid;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      min-height: 100vh;
      padding: 24px;
    }}

    main {{
      margin: 0 auto;
      max-width: 420px;
      width: 100%;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
      margin: 0 0 8px;
    }}

    p {{
      color: var(--muted);
      line-height: 1.45;
      margin: 0 0 20px;
    }}

    form {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 20px;
    }}

    label {{
      display: grid;
      font-weight: 700;
      gap: 6px;
    }}

    input {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      min-height: 42px;
      padding: 8px 10px;
      width: 100%;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      min-height: 44px;
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    .error {{
      color: var(--error);
      font-weight: 700;
      margin: 0;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Application Tracker</h1>
    <p>Sign in to manage your job search.</p>
    <form method="post" action="/login">
      {error_block}
      <label>
        Email
        <input name="email" type="email" autocomplete="email" required>
      </label>
      <label>
        Password
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>"""
    )


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_form() -> HTMLResponse:
    return login_page()


@router.post(
    "/login",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def login_form_submit(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    try:
        user = authenticate_local_user(db, email, password)
    except HTTPException:
        return login_page(error="Invalid email or password")

    response = RedirectResponse(url="/board", status_code=status.HTTP_303_SEE_OTHER)
    create_login_session(db, user, request=request, response=response)
    return response


@router.post("/logout", include_in_schema=False)
def logout_form(
    db: DbSession,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if session_token:
        revoke_session(db, session_token)
        db.commit()

    response.delete_cookie(settings.session_cookie_name, path="/")
    clear_csrf_cookie(response)
    return response
