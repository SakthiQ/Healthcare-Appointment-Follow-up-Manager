from sqlalchemy import text
from app.database import check_db_connection
from app.exceptions import NotFoundError, ConflictError


def test_database_connection():
    """Test utility check_db_connection."""
    assert check_db_connection() is True


def test_db_session_query(db_session):
    """Test active DB session query execution."""
    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_custom_exceptions():
    """Test custom exception status codes and error codes."""
    nf = NotFoundError("Item missing")
    assert nf.status_code == 404
    assert nf.error_code == "NOT_FOUND"
    assert nf.message == "Item missing"

    cf = ConflictError("Slot booked")
    assert cf.status_code == 409
    assert cf.error_code == "CONFLICT"
