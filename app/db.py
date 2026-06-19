"""SQLAlchemy engine / session setup.

Works against both SQLite (local default + tests) and Postgres (Supabase in
production). The driver/connect args are chosen from the configured URL scheme.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _normalize_url(url: str) -> str:
    """Force the psycopg (v3) driver for Postgres URLs (Supabase gives bare ones)."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_url = _normalize_url(settings.database_url)
_is_sqlite = _url.startswith("sqlite")

if _is_sqlite:
    # SQLite + background threads need this.
    _engine_kwargs: dict = {"connect_args": {"check_same_thread": False}}
else:
    # Supabase poolers drop idle connections; pre_ping avoids stale-connection errors.
    _engine_kwargs = {"pool_pre_ping": True}

engine = create_engine(_url, future=True, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables if they do not exist."""
    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for use outside of request handlers / jobs."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
