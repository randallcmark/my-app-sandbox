from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    app.include_router(auth_router)
    app.include_router(health_router)
    return app


app = create_app()
