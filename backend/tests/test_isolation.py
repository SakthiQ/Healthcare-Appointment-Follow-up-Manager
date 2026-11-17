"""Rows committed by one test must not be visible to the next (see conftest.py).

The two tests run in file order: the first commits a user, the second checks it is gone.
"""
from models.user import User, UserRole

EMAIL = "isolation-check@example.com"


def test_1_commit_a_row(db_session):
    db_session.add(User(email=EMAIL, password_hash="x", full_name="Isolation Check", role=UserRole.PATIENT))
    db_session.commit()
    assert db_session.query(User).filter_by(email=EMAIL).count() == 1


def test_2_the_row_is_gone(db_session):
    assert db_session.query(User).filter_by(email=EMAIL).count() == 0
    assert db_session.query(User).count() == 0
