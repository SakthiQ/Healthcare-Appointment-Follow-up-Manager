from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import or_
from sqlalchemy.orm import Session
from models.calendar import CalendarEvent, CalendarSyncStatus, CalendarOperation


class CalendarEventRepository:
    def get_by_id(self, db: Session, event_row_id: str) -> Optional[CalendarEvent]:
        return db.query(CalendarEvent).filter(CalendarEvent.id == event_row_id).first()

    def get_for_appointment(self, db: Session, appointment_id: str) -> List[CalendarEvent]:
        return db.query(CalendarEvent).filter(CalendarEvent.appointment_id == appointment_id).all()

    def get_for_appointment_recipient(
        self, db: Session, appointment_id: str, recipient_type: str
    ) -> Optional[CalendarEvent]:
        return db.query(CalendarEvent).filter(
            CalendarEvent.appointment_id == appointment_id,
            CalendarEvent.recipient_type == recipient_type,
        ).first()

    def upsert_pending(
        self, db: Session, appointment_id: str, recipient_type: str, operation: CalendarOperation
    ) -> CalendarEvent:
        """Create the row if absent, otherwise re-arm the existing row with a new
        pending operation. Never inserts a second row for the same
        (appointment, recipient) — that pairing is uniquely constrained, which
        is what prevents duplicate calendar events across repeated syncs."""
        row = self.get_for_appointment_recipient(db, appointment_id, recipient_type)
        if row is None:
            row = CalendarEvent(
                appointment_id=appointment_id,
                recipient_type=recipient_type,
                status=CalendarSyncStatus.PENDING_SYNC,
                pending_operation=operation,
            )
            db.add(row)
        else:
            row.pending_operation = operation
            row.status = CalendarSyncStatus.PENDING_SYNC
            row.attempts = 0
            row.next_retry_at = None
            row.last_error = None
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return row

    def get_due_syncs(self, db: Session, limit: int = 20) -> List[CalendarEvent]:
        now = datetime.now(timezone.utc)
        query = db.query(CalendarEvent).filter(
            CalendarEvent.status == CalendarSyncStatus.PENDING_SYNC,
            CalendarEvent.pending_operation != CalendarOperation.NONE,
            or_(CalendarEvent.next_retry_at.is_(None), CalendarEvent.next_retry_at <= now),
        ).order_by(CalendarEvent.created_at.asc()).limit(limit)

        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update(skip_locked=True)
        return query.all()

    def mark_synced(self, db: Session, row: CalendarEvent, external_event_id: Optional[str]) -> CalendarEvent:
        row.status = CalendarSyncStatus.SYNCED
        row.pending_operation = CalendarOperation.NONE
        row.external_event_id = external_event_id
        row.attempts += 1
        row.last_error = None
        row.next_retry_at = None
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return row

    def mark_retryable(
        self, db: Session, row: CalendarEvent, error_message: str, next_retry_at: datetime
    ) -> CalendarEvent:
        row.status = CalendarSyncStatus.PENDING_SYNC
        row.attempts += 1
        row.last_error = error_message
        row.next_retry_at = next_retry_at
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return row

    def mark_failed(self, db: Session, row: CalendarEvent, error_message: str) -> CalendarEvent:
        row.status = CalendarSyncStatus.FAILED
        row.attempts += 1
        row.last_error = error_message
        row.next_retry_at = None
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return row


calendar_repository = CalendarEventRepository()
