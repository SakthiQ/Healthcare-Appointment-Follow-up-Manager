import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.main import app
from app.config import settings
from app.database import Base, get_db

# Test-only: fixtures across the suite bootstrap ADMIN/DOCTOR users directly
# via POST /auth/register (no separate seeding mechanism exists). This must
# stay False in any real deployment — see AuthService.register_user.
settings.ALLOW_PRIVILEGED_SELF_REGISTRATION = True

# Test-only: many tests register dozens of users from one address ("testclient"). The limiter has
# its own tests, which switch it back on with monkeypatch.
settings.RATE_LIMITING_ENABLED = False

# Test-only: the concurrency tests fire 100 requests at once on purpose. The request cap has
# its own tests, which switch it back on with monkeypatch.
settings.MAX_CONCURRENT_REQUESTS = 0


# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)


TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all tables in the test database for the session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def _empty_tables_after_each_test():
    """Start every test from an empty database.

    Services commit for real, and the threaded tests need those commits visible to other
    sessions, so the rollback in db_session cannot undo them. Instead, every row is deleted
    once the test (and its fixtures) are done. Child tables go first, so the order also
    works with foreign keys switched on.
    """
    yield
    with test_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def db_session():
    """Provide a transactional database session for testing."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()



@pytest.fixture
def client(db_session):
    """FastAPI TestClient with overridden database dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
