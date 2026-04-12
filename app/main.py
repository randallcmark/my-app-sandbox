from typing import Annotated

from fastapi import Cookie, Depends, FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.board import router as board_router
from app.api.routes.capture import router as capture_router
from app.api.routes.health import router as health_router
from app.api.routes.job_detail import router as job_detail_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.session_ui import router as session_ui_router
from app.auth.sessions import get_active_session
from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db_session


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/", include_in_schema=False)
    def root(
        db: Annotated[Session, Depends(get_db_session)],
        session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
    ) -> RedirectResponse:
        try:
            has_users = db.scalar(select(User.id).limit(1)) is not None
        except SQLAlchemyError:
            has_users = True
        if not has_users:
            return RedirectResponse(url="/setup")
        if session_token and get_active_session(db, session_token) is not None:
            return RedirectResponse(url="/board")
        return RedirectResponse(url="/login")

    app.include_router(auth_router)
    app.include_router(board_router)
    app.include_router(capture_router)
    app.include_router(health_router)
    app.include_router(job_detail_router)
    app.include_router(jobs_router)
    app.include_router(session_ui_router)
    return app


app = create_app()
