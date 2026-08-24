from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import or_
from sqlalchemy.orm import Session
from models.notification import NotificationJob, NotificationType, NotificationStatus


class NotificationJobRepository:
    def get_by_id(self, db: Session, job_id: str) -> Optional[NotificationJob]:
        return db.query(NotificationJob).filter(NotificationJob.id == job_id).first()

    def create_job(
        self,
        db: Session,
        appointment_id: Optional[str],
        recipient_id: str,
        notification_type: NotificationType,
        payload: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> NotificationJob:
        job = NotificationJob(
            appointment_id=appointment_id,
            recipient_id=recipient_id,
            notification_type=notification_type,
            status=NotificationStatus.PENDING,
            payload=payload,
            next_retry_at=scheduled_for,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def create_job_no_commit(
        self,
        db: Session,
        appointment_id: Optional[str],
        recipient_id: str,
        notification_type: NotificationType,
        payload: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> NotificationJob:
        """Like create_job but only flushes — caller controls the transaction
        boundary (used by DoctorLeaveService's single atomic transaction)."""
        job = NotificationJob(
            appointment_id=appointment_id,
            recipient_id=recipient_id,
            notification_type=notification_type,
            status=NotificationStatus.PENDING,
            payload=payload,
            next_retry_at=scheduled_for,
        )
        db.add(job)
        db.flush()
        return job

    def get_due_jobs(self, db: Session, limit: int = 20) -> List[NotificationJob]:
        """Atomically claims a batch of due PENDING jobs by marking them
        PROCESSING and committing immediately, so two workers can never pick
        up the same job (SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL;
        a no-op on SQLite, which has no concurrent workers to race with)."""
        now = datetime.now(timezone.utc)
        query = db.query(NotificationJob).filter(
            NotificationJob.status == NotificationStatus.PENDING,
            or_(NotificationJob.next_retry_at.is_(None), NotificationJob.next_retry_at <= now)
        ).order_by(NotificationJob.created_at.asc()).limit(limit)

        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update(skip_locked=True)

        jobs = query.all()
        for job in jobs:
            job.status = NotificationStatus.PROCESSING
            job.updated_at = datetime.now(timezone.utc)
        db.commit()
        for job in jobs:
            db.refresh(job)
        return jobs

    def mark_sent(self, db: Session, job: NotificationJob) -> NotificationJob:
        job.status = NotificationStatus.SENT
        job.attempts += 1
        job.last_error = None
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job

    def mark_failed_retryable(
        self, db: Session, job: NotificationJob, error_message: str, next_retry_at: datetime
    ) -> NotificationJob:
        """Bounded retry: status goes back to PENDING so get_due_jobs picks it up again once due."""
        job.status = NotificationStatus.PENDING
        job.attempts += 1
        job.last_error = error_message
        job.next_retry_at = next_retry_at
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job

    def supersede_pending(
        self,
        db: Session,
        appointment_id: str,
        notification_type: NotificationType,
        reason: str,
    ) -> int:
        """Retire still-pending jobs of one type for an appointment.

        Used when a reschedule or cancellation makes already-queued jobs
        obsolete — without this, a reminder scheduled for the OLD time would
        still be delivered after the appointment moved or was cancelled.

        Terminal state is FAILED because NotificationStatus has no dedicated
        'superseded' value; `last_error` records why, so the distinction stays
        observable and the audit trail is preserved rather than deleted.
        """
        now = datetime.now(timezone.utc)
        affected = db.query(NotificationJob).filter(
            NotificationJob.appointment_id == appointment_id,
            NotificationJob.notification_type == notification_type,
            NotificationJob.status == NotificationStatus.PENDING,
        ).update(
            {"status": NotificationStatus.FAILED, "last_error": reason, "updated_at": now},
            synchronize_session=False,
        )
        db.commit()
        return affected

    def mark_failed_permanent(self, db: Session, job: NotificationJob, error_message: str) -> NotificationJob:
        """Terminal failure: max attempts exhausted or a non-retryable error."""
        job.status = NotificationStatus.FAILED
        job.attempts += 1
        job.last_error = error_message
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job


notification_repository = NotificationJobRepository()
