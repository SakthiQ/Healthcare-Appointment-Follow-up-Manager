"""Optional audit log retention (#37): off by default, deletes only old entries, refuses typos."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.config import AUDIT_LOG_RETENTION_MIN_DAYS, Settings, settings
from models.audit import AuditLog
from repositories.audit_repository import audit_repository
from services.maintenance_service import maintenance_service


def _entry(days_ago: float) -> AuditLog:
    return AuditLog(occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
                    action="appointment.view", actor_role="ADMIN")


def _seed(db, ages):
    db.add_all([_entry(age) for age in ages])
    db.commit()


def test_unset_retention_deletes_nothing(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUDIT_LOG_RETENTION_DAYS", None)
    _seed(db_session, [1, 400, 4000])

    counts = maintenance_service.purge_expired(db_session)

    assert counts["audit_logs"] == 0
    assert db_session.query(AuditLog).count() == 3


def test_retention_deletes_only_entries_older_than_the_cutoff(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUDIT_LOG_RETENTION_DAYS", 365)
    _seed(db_session, [1, 100, 364, 366, 1000])

    counts = maintenance_service.purge_expired(db_session)

    assert counts["audit_logs"] == 2
    remaining = sorted((datetime.now(timezone.utc) - row.occurred_at.replace(tzinfo=timezone.utc)).days
                       for row in db_session.query(AuditLog).all())
    assert remaining == [1, 100, 364]


def test_purge_works_in_batches(db_session):
    _seed(db_session, [500] * 25 + [1] * 3)

    deleted = audit_repository.purge_older_than(
        db_session, datetime.now(timezone.utc) - timedelta(days=30), batch_size=10)

    assert deleted == 25
    assert db_session.query(AuditLog).count() == 3


@pytest.mark.parametrize("value", [0, 3, AUDIT_LOG_RETENTION_MIN_DAYS - 1])
def test_retention_below_the_minimum_is_refused(value):
    with pytest.raises(ValidationError, match="AUDIT_LOG_RETENTION_DAYS must be at least"):
        Settings(AUDIT_LOG_RETENTION_DAYS=value)


@pytest.mark.parametrize("value, expected", [(None, None), ("", None), (AUDIT_LOG_RETENTION_MIN_DAYS, 30), (2555, 2555)])
def test_valid_retention_values_are_accepted(value, expected):
    assert Settings(AUDIT_LOG_RETENTION_DAYS=value).AUDIT_LOG_RETENTION_DAYS == expected
