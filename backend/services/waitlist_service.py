"""Waitlist for fully booked days (#71).

A patient joins for one doctor and one date when that day has no free slot. When a slot on
that day frees up (a cancellation, a reschedule away from it, or a hold expiring), everyone
still waiting is emailed, and the first to book wins: the waitlist reserves nothing. The
email is queued after the change has committed, like every other side effect, so a failure
here never undoes a cancellation.
"""
import logging
from datetime import date, datetime, timezone
from typing import List

from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.core.datetime_utils import ensure_utc, get_zone
from app.exceptions import ConflictError, NotFoundError, ValidationError
from models.doctor import Doctor
from models.notification import NotificationType
from models.waitlist import WaitlistEntry
from repositories.doctor_repository import doctor_repository
from schemas.waitlist import WaitlistEntryResponse
from services.notification_service import notification_service
from services.slot_service import slot_service

logger = logging.getLogger(__name__)


def local_date(doctor: Doctor, moment: datetime) -> date:
    """The date of `moment` in the doctor's own timezone, which is how slots are grouped."""
    return ensure_utc(moment).astimezone(get_zone(doctor.timezone)).date()


def _response(entry: WaitlistEntry) -> WaitlistEntryResponse:
    doctor = entry.doctor
    return WaitlistEntryResponse(
        id=entry.id, doctor_id=entry.doctor_id, date=entry.date, created_at=entry.created_at,
        notified_at=entry.notified_at,
        doctor_name=doctor.user.full_name if doctor and doctor.user else None,
        doctor_specialization=doctor.specialization if doctor else None,
    )


class WaitlistService:
    def _free_slots(self, db: Session, doctor_id: str, day: date) -> int:
        return slot_service.generate_slots(db, doctor_id, day).available_slots

    def join(self, db: Session, patient_id: str, doctor_id: str, day: date) -> WaitlistEntryResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor or not doctor.is_active:
            raise NotFoundError("Doctor not found.")
        if day <= local_date(doctor, datetime.now(timezone.utc)):
            raise ValidationError("You can only join the waitlist for a future date.")
        if self._free_slots(db, doctor_id, day) > 0:
            raise ConflictError("There are still free slots on that day. Book one instead.")

        existing = db.query(WaitlistEntry).filter(
            WaitlistEntry.patient_id == patient_id, WaitlistEntry.doctor_id == doctor_id, WaitlistEntry.date == day
        ).first()
        if existing is not None and existing.notified_at is None:
            raise ConflictError("You are already on the waitlist for that day.")
        active = db.query(WaitlistEntry).filter(
            WaitlistEntry.patient_id == patient_id, WaitlistEntry.notified_at.is_(None), WaitlistEntry.date >= date.today()
        ).count()
        if active >= settings.MAX_ACTIVE_WAITLIST_PER_PATIENT:
            raise ConflictError(
                f"You can be on at most {settings.MAX_ACTIVE_WAITLIST_PER_PATIENT} waitlists at once. Leave one first."
            )
        if existing is not None:  # notified before; joining again re-arms it
            existing.notified_at = None
            existing.created_at = datetime.now(timezone.utc)
            entry = existing
        else:
            entry = WaitlistEntry(patient_id=patient_id, doctor_id=doctor_id, date=day)
            db.add(entry)
        db.commit()
        db.refresh(entry)
        return _response(entry)

    def leave(self, db: Session, patient_id: str, doctor_id: str, day: date) -> None:
        deleted = db.query(WaitlistEntry).filter(
            WaitlistEntry.patient_id == patient_id, WaitlistEntry.doctor_id == doctor_id, WaitlistEntry.date == day
        ).delete(synchronize_session=False)
        db.commit()
        if not deleted:
            raise NotFoundError("You are not on the waitlist for that day.")

    def list_mine(self, db: Session, patient_id: str) -> List[WaitlistEntryResponse]:
        entries = (
            db.query(WaitlistEntry)
            .options(selectinload(WaitlistEntry.doctor).selectinload(Doctor.user))
            .filter(WaitlistEntry.patient_id == patient_id, WaitlistEntry.date >= date.today())
            .order_by(WaitlistEntry.date, WaitlistEntry.created_at)
            .all()
        )
        return [_response(e) for e in entries]

    def notify_if_slot_open(self, db: Session, doctor_id: str, day: date) -> int:
        """Email everyone still waiting for this doctor and day, if the day now has a free
        slot. Returns how many were told. Call after the freeing change has committed."""
        waiting = db.query(WaitlistEntry).filter(
            WaitlistEntry.doctor_id == doctor_id, WaitlistEntry.date == day, WaitlistEntry.notified_at.is_(None)
        ).all()
        if not waiting or self._free_slots(db, doctor_id, day) == 0:
            return 0
        doctor = doctor_repository.get_by_id(db, doctor_id)
        payload = {
            "doctor_id": doctor_id, "date": day.isoformat(),
            "doctor_name": doctor.user.full_name if doctor and doctor.user else None,
        }
        now = datetime.now(timezone.utc)
        for entry in waiting:
            notification_service.queue_notification_no_commit(
                db, appointment_id=None, recipient_id=entry.patient_id,
                notification_type=NotificationType.WAITLIST_SLOT_OPEN, payload=payload,
            )
            entry.notified_at = now
        db.commit()
        return len(waiting)

    def safe_notify(self, db: Session, doctor_id: str, day: date) -> None:
        """Best effort: a failure is logged and rolled back, never raised to the caller."""
        try:
            self.notify_if_slot_open(db, doctor_id, day)
        except Exception:
            db.rollback()
            logger.exception("Could not notify the waitlist for doctor %s on %s", doctor_id, day)

    def purge_past(self, db: Session) -> int:
        deleted = db.query(WaitlistEntry).filter(WaitlistEntry.date < date.today()).delete(synchronize_session=False)
        db.commit()
        return deleted


waitlist_service = WaitlistService()
