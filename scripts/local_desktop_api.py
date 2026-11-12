"""Local-only desktop API. Does not import app.main or start trading workers.

Launch: python -m uvicorn scripts.local_desktop_api:app --host 127.0.0.1 --port 8765
"""
import os
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from app.core.config import get_settings
from app.api.routes import auth, users, strategies, desktop, paper_preview

settings = get_settings()
db = make_url(settings.database_url)
if db.database != "cryptobot" or db.host not in {"127.0.0.1", "localhost"}:
    raise RuntimeError("Local desktop API requires local cryptobot PostgreSQL.")
if os.getenv("NEXORA_LOCAL_DESKTOP_API") != "YES":
    raise RuntimeError("Set NEXORA_LOCAL_DESKTOP_API=YES to explicitly allow local desktop API.")
if settings.app_env.lower() in {"production", "prod"}:
    raise RuntimeError("Local desktop API is disabled in production.")

app = FastAPI(
    title="Nexora Local Desktop Paper API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
for router in (auth.router, users.router, strategies.router, desktop.router, paper_preview.router):
    app.include_router(router, prefix="/api/v1")


# Background scanning is opt-in and remains strictly paper-only.
if os.getenv("NEXORA_PREVIEW_WORKER") == "YES":
    import asyncio
    from contextlib import asynccontextmanager
    from scripts.local_preview_worker import observer_loop

    @asynccontextmanager
    async def preview_lifespan(app):
        task = asyncio.create_task(observer_loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app.router.lifespan_context = preview_lifespan
