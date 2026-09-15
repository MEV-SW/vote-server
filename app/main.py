from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import admin, events, polls
from app.services.poll_events import close_event_bus, init_event_bus
from app.migrations import ensure_schema, migrate_figma_urls
from app.seed import seed_database

settings = get_settings()


class StripApiPrefixMiddleware:
    """브라우저/프론트는 /api/* 로 호출. Vite는 프록시에서 떼고, EC2(FRONTEND_DIST)는 여기서 뗀다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = dict(scope)
                new_path = path[4:] or "/"
                scope["path"] = new_path
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)) and raw.startswith(b"/api"):
                    scope["raw_path"] = raw[4:] or b"/"
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    settings.media_path.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        migrate_figma_urls(db)
        seed_database(db)
    finally:
        db.close()
    await init_event_bus(settings.redis_url)
    yield
    await close_event_bus()


app = FastAPI(title="Vote Platform API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 가장 바깥에서 /api 접두 제거 (EC2에서 Vite 프록시 없을 때)
app.add_middleware(StripApiPrefixMiddleware)

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(events.router)
app.include_router(polls.router)
app.include_router(admin.router)

if settings.media_path.exists():
    app.mount("/media", StaticFiles(directory=str(settings.media_path)), name="media")

frontend_dist = settings.frontend_dist_path
if frontend_dist and frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
