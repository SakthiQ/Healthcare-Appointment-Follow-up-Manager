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
        recipient_id: Optional[str],
        notification_type: NotificationType,
        payload: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
        recipient_email: Optional[str] = None,
    ) -> NotificationJob:
        job = NotificationJob(
            appointment_id=appointment_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
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
        recipient_id: Optional[str],
        notification_type: NotificationType,
        payload: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
        recipient_email: Optional[str] = None,
    ) -> NotificationJob:
        """Like create_job but only flushes — caller controls the transaction
        boundary (used by DoctorLeaveService's single atomic transaction)."""
        job = NotificationJob(
            appointment_id=appointment_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
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
        affected = self.supersede_pending_no_commit(db, appointment_id, notification_type, reason)
        db.commit()
        return affected

    def supersede_pending_no_commit(
        self,
        db: Session,
        appointment_id: str,
        notification_type: NotificationType,
        reason: str,
    ) -> int:
        """Like supersede_pending but leaves the commit to the caller, whose
        transaction this update joins."""
        now = datetime.now(timezone.utc)
        return db.query(NotificationJob).filter(
            NotificationJob.appointment_id == appointment_id,
            NotificationJob.notification_type == notification_type,
            NotificationJob.status == NotificationStatus.PENDING,
        ).update(
            {"status": NotificationStatus.FAILED, "last_error": reason, "updated_at": now},
            synchronize_session=False,
        )

    def requeue_stale_processing(self, db: Session, stale_before: datetime, max_attempts: int) -> int:
        """Recover jobs a worker claimed but never finished (it crashed or was
        restarted mid-batch). Each recovery counts as an attempt, so a job that
        keeps killing its worker still ends in FAILED. Delivery is at-least-once:
        a worker that died just after sending causes one duplicate email, which
        is preferable to a reminder that is silently never sent."""
        query = db.query(NotificationJob).filter(
            NotificationJob.status == NotificationStatus.PROCESSING,
            NotificationJob.updated_at <= stale_before,
        )
        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update(skip_locked=True)

        jobs = query.all()
        for job in jobs:
            job.attempts += 1
            job.last_error = "Worker stopped before finishing this job."
            job.status = (
                NotificationStatus.FAILED if job.attempts >= max_attempts else NotificationStatus.PENDING
            )
            job.updated_at = datetime.now(timezone.utc)
        db.commit()
        return len(jobs)

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
