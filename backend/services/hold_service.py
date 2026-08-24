from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.exceptions import NotFoundError, ConflictError, ValidationError, ForbiddenError
from repositories.doctor_repository import doctor_repository
from repositories.hold_repository import hold_repository
from services.slot_service import slot_service
from schemas.slot import HoldCreateRequest, HoldResponse
from models.appointment import AppointmentHold, AppointmentStatus


from app.core.datetime_utils import ensure_utc


class HoldService:
    def create_hold(
        self, db: Session, patient_id: str, req: HoldCreateRequest, hold_duration_minutes: int = 10
    ) -> HoldResponse:
        # Ensure stale holds are expired first
        hold_repository.expire_stale_holds(db)

        start_time = ensure_utc(req.start_time)
        end_time = ensure_utc(req.end_time)

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

    def get_hold(self, db: Session, hold_id: str) -> HoldResponse:
        hold_repository.expire_stale_holds(db)
        hold = hold_repository.get_by_id(db, hold_id)
        if not hold:
            raise NotFoundError("Hold not found.")
        return HoldResponse.model_validate(hold)

    def confirm_hold(self, db: Session, hold_id: str, patient_id: str) -> AppointmentHold:
        """Validate hold for confirmation. Does not create appointment DB entity (handled in Phase 6)."""
        hold_repository.expire_stale_holds(db)
        hold = hold_repository.get_by_id(db, hold_id)
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
