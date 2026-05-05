from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.app.config import settings


settings.ensure_directories()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def init_db() -> None:
    from backend.app.storage import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_existing_sqlite_schema()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_existing_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "sessions" not in inspector.get_table_names():
        return
    session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    additions = {
        "privacy_strictness": "VARCHAR DEFAULT 'standard'",
        "ocr_provider": "VARCHAR DEFAULT 'mock'",
        "ocr_profile": "VARCHAR DEFAULT 'screen-fast'",
        "model_provider": "VARCHAR DEFAULT 'mock'",
        "app_exclusion_patterns": "TEXT DEFAULT '[]'",
    }
    with engine.begin() as connection:
        for column_name, ddl in additions.items():
            if column_name not in session_columns:
                connection.execute(text(f"ALTER TABLE sessions ADD COLUMN {column_name} {ddl}"))
