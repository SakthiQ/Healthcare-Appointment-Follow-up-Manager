from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.exceptions import NotFoundError, ConflictError, ValidationError, ForbiddenError
from repositories.doctor_repository import doctor_repository
from repositories.hold_repository import hold_repository
from services.slot_service import slot_service
from schemas.slot import HoldCreateRequest, HoldResponse
from models.appointment import AppointmentHold, AppointmentStatus
from models.user import User, UserRole


from app.core.datetime_utils import ensure_utc


class HoldService:
    def create_hold(
        self, db: Session, patient_id: str, req: HoldCreateRequest, hold_duration_minutes: int = 10
    ) -> HoldResponse:
        start_time = ensure_utc(req.start_time)
        end_time = ensure_utc(req.end_time)

        # Free this slot of any expired hold that is still flagged active (it would
        # trip the one-active-hold-per-slot index). Only this slot: nothing else
        # needs a write here, and the expiry worker sweeps the rest.
        hold_repository.expire_stale_holds_for_slot(db, req.doctor_id, start_time)

        now = datetime.now(timezone.utc)
        if start_time <= now:
            raise ValidationError("Cannot hold a slot in the past.")

        # 1. Validate slot boundaries
        is_valid_boundary = slot_service.validate_slot_boundary(db, req.doctor_id, start_time, end_time)
        if not is_valid_boundary:
            raise ValidationError("Invalid slot boundary or slot falls outside doctor working hours/leave.")

        # 2. Check active holds
        existing_hold = hold_repository.get_active_hold_for_slot(db, req.doctor_id, start_time, end_time)
        if existing_hold:
            raise ConflictError("Slot is currently held by another patient.")

        # 3. Check active appointments
        existing_appts = hold_repository.get_active_appointments_for_doctor_date(
            db, req.doctor_id, start_time, end_time
        )
        for appt in existing_appts:
            appt_start = ensure_utc(appt.start_time)
            appt_end = ensure_utc(appt.end_time)
            if max(start_time, appt_start) < min(end_time, appt_end):
                raise ConflictError("Slot is already booked.")

        # 4. Create Hold
        expires_at = now + timedelta(minutes=hold_duration_minutes)
        hold = hold_repository.create(
            db=db,
            doctor_id=req.doctor_id,
            patient_id=patient_id,
            start_time=start_time,
            end_time=end_time,
            expires_at=expires_at
        )
        return HoldResponse.model_validate(hold)

    def get_hold(self, db: Session, hold_id: str, user: User) -> HoldResponse:
        # A read: no writes. An expired hold may still be flagged active until the
        # expiry worker or the next hold on its slot sweeps it, so report what it
        # effectively is.
        hold = hold_repository.get_by_id(db, hold_id)
        if not hold:
            raise NotFoundError("Hold not found.")
        if user.role != UserRole.ADMIN and hold.patient_id != user.id:
            raise ForbiddenError("Not authorized to view this hold.")
        response = HoldResponse.model_validate(hold)
        response.is_active = bool(hold.is_active and ensure_utc(hold.expires_at) > datetime.now(timezone.utc))
        return response

    def confirm_hold(self, db: Session, hold_id: str, patient_id: str) -> AppointmentHold:
        """Validate hold for confirmation. Does not create appointment DB entity (handled in Phase 6)."""
        # Locked until the appointment insert commits, so two concurrent confirms
        # of one hold run one after the other and the second sees it released.
        hold = hold_repository.get_by_id(db, hold_id, with_for_update=True)
        if not hold:
            raise NotFoundError("Hold not found.")

        if hold.patient_id != patient_id:
            raise ForbiddenError("Only the patient who created the hold can confirm it.")

        now = datetime.now(timezone.utc)
        expires_at = ensure_utc(hold.expires_at)
        if not hold.is_active or expires_at <= now:
            raise ValidationError("Hold has expired or is inactive. Please select an available slot again.")

        return hold

    def release_hold(self, db: Session, hold_id: str, patient_id: str):
        hold = hold_repository.get_by_id(db, hold_id)
        if not hold:
            raise NotFoundError("Hold not found.")

        if hold.patient_id != patient_id:
            raise ForbiddenError("Only the patient who created the hold can release it.")

        hold_repository.deactivate(db, hold)

    def expire_holds(self, db: Session) -> int:
        return hold_repository.expire_stale_holds(db)



hold_service = HoldService()
