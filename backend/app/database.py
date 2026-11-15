import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logger = logging.getLogger(__name__)


def _engine_kwargs(url: str) -> dict:
    kwargs = {"pool_pre_ping": True, "echo": False}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    # An in-memory SQLite database lives in a single connection, so its pool is not a
    # QueuePool and takes no sizing. Every other URL gets the configured pool (see
    # DB_POOL_SIZE in app/config.py for how to size it).
    if not (url.startswith("sqlite") and (":memory:" in url or url.rstrip("/").endswith("sqlite:"))):
        kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        )
    return kwargs


engine = create_engine(settings.DATABASE_URL, **_engine_kwargs(settings.DATABASE_URL))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency that yields a database session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Utility to test database connectivity."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
