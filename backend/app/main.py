from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router
from backend.app.config import settings
from backend.app.storage.database import SessionLocal, init_db
from backend.app.storage.models import Session, UserActionLog, utcnow


def close_open_sessions_on_start() -> dict[str, int]:
    db = SessionLocal()
    try:
        open_sessions = db.query(Session).filter(Session.status.in_(["active", "paused"])).all()
        now = utcnow()
        for session in open_sessions:
            session.status = "stopped"
            session.ended_at = session.ended_at or now
            db.add(
                UserActionLog(
                    session_id=session.id,
                    action="session_closed_on_backend_start",
                    details='{"reason": "backend_started_without_local_capture_stream"}',
                )
            )
        db.commit()
        return {"closed_sessions": len(open_sessions)}
    finally:
        db.close()


def create_app() -> FastAPI:
    settings.ensure_directories()
    init_db()
    close_open_sessions_on_start()
    app = FastAPI(
        title="Watcher Backend",
        description="Local-only context memory and note generation backend.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "app://watcher",
            "file://",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port, reload=False)
