from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models.appointment import AppointmentHold, Appointment, AppointmentStatus


class HoldRepository:
    def get_by_id(self, db: Session, hold_id: str) -> Optional[AppointmentHold]:
        return db.query(AppointmentHold).filter(AppointmentHold.id == hold_id).first()

    def get_active_hold_for_slot(
        self, db: Session, doctor_id: str, start_time: datetime, end_time: datetime
    ) -> Optional[AppointmentHold]:
        now = datetime.now(timezone.utc)
        return db.query(AppointmentHold).filter(
            AppointmentHold.doctor_id == doctor_id,
            AppointmentHold.start_time == start_time,
            AppointmentHold.is_active.is_(True),
            AppointmentHold.expires_at > now
        ).first()

    def get_active_holds_for_doctor_date(
        self, db: Session, doctor_id: str, day_start: datetime, day_end: datetime
    ) -> List[AppointmentHold]:
        now = datetime.now(timezone.utc)
        return db.query(AppointmentHold).filter(
            AppointmentHold.doctor_id == doctor_id,
            AppointmentHold.start_time >= day_start,
            AppointmentHold.start_time < day_end,
            AppointmentHold.is_active.is_(True),
            AppointmentHold.expires_at > now
        ).all()

    def get_active_appointments_for_doctor_date(
        self, db: Session, doctor_id: str, day_start: datetime, day_end: datetime
    ) -> List[Appointment]:
        return db.query(Appointment).filter(
            Appointment.doctor_profile_id == doctor_id,
            Appointment.start_time >= day_start,
            Appointment.start_time < day_end,
            Appointment.status.in_([AppointmentStatus.HELD, AppointmentStatus.CONFIRMED])
        ).all()

    def create(
        self,
        db: Session,
        doctor_id: str,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
        expires_at: datetime
    ) -> AppointmentHold:
        hold = AppointmentHold(
            doctor_id=doctor_id,
            patient_id=patient_id,
            start_time=start_time,
            end_time=end_time,
            expires_at=expires_at,
            is_active=True
        )
        db.add(hold)
        db.commit()
        db.refresh(hold)
        return hold

    def deactivate(self, db: Session, hold: AppointmentHold):
        hold.is_active = False
        db.commit()
        db.refresh(hold)

    def expire_stale_holds(self, db: Session) -> int:
        now = datetime.now(timezone.utc)
        stale_count = db.query(AppointmentHold).filter(
            AppointmentHold.is_active.is_(True),
            AppointmentHold.expires_at <= now
        ).update({"is_active": False}, synchronize_session=False)
        db.commit()
        return stale_count



hold_repository = HoldRepository()
