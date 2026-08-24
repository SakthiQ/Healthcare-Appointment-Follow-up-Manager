from typing import Optional, List
from datetime import date
from sqlalchemy.orm import Session
from models.user import User, UserRole
from models.doctor import Doctor, DoctorWorkingHours, DoctorLeave


class DoctorRepository:
    def get_by_id(self, db: Session, doctor_id: str) -> Optional[Doctor]:
        return db.query(Doctor).filter(Doctor.id == doctor_id).first()

    def get_by_user_id(self, db: Session, user_id: str) -> Optional[Doctor]:
        return db.query(Doctor).filter(Doctor.user_id == user_id).first()

    def search(self, db: Session, specialization: Optional[str] = None, active_only: bool = True) -> List[Doctor]:
        query = db.query(Doctor).join(User, Doctor.user_id == User.id)
        if active_only:
            query = query.filter(Doctor.is_active.is_(True), User.is_active.is_(True))
        if specialization:
            query = query.filter(Doctor.specialization.ilike(f"%{specialization.strip()}%"))
        return query.all()

    def create_doctor(self, db: Session, user_id: str, specialization: str, slot_duration: int = 30) -> Doctor:
        doctor = Doctor(
            user_id=user_id,
            specialization=specialization.strip(),
            slot_duration_minutes=slot_duration
        )
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
        return doctor

    def update_doctor(self, db: Session, doctor: Doctor, specialization: Optional[str] = None, slot_duration: Optional[int] = None, is_active: Optional[bool] = None) -> Doctor:
        if specialization is not None:
            doctor.specialization = specialization.strip()
        if slot_duration is not None:
            doctor.slot_duration_minutes = slot_duration
        if is_active is not None:
            doctor.is_active = is_active
        db.commit()
        db.refresh(doctor)
        return doctor

    # Working Hours
    def get_working_hours(self, db: Session, doctor_id: str) -> List[DoctorWorkingHours]:
        return db.query(DoctorWorkingHours).filter(DoctorWorkingHours.doctor_id == doctor_id).order_by(DoctorWorkingHours.day_of_week).all()

    def upsert_working_hours(self, db: Session, doctor_id: str, hours_items: list) -> List[DoctorWorkingHours]:
        # Delete existing schedule for doctor and insert fresh working hours
        db.query(DoctorWorkingHours).filter(DoctorWorkingHours.doctor_id == doctor_id).delete()
        new_hours = []
        for item in hours_items:
            wh = DoctorWorkingHours(
                doctor_id=doctor_id,
                day_of_week=item.day_of_week,
                start_time=item.start_time,
                end_time=item.end_time,
                is_active=item.is_active
            )
            db.add(wh)
            new_hours.append(wh)
        db.commit()
        for wh in new_hours:
            db.refresh(wh)
        return new_hours

    # Leave Management
    def get_leaves(self, db: Session, doctor_id: str) -> List[DoctorLeave]:
        return db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id).order_by(DoctorLeave.leave_date).all()

    def get_leave_by_date(self, db: Session, doctor_id: str, leave_date: date) -> Optional[DoctorLeave]:
        return db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id, DoctorLeave.leave_date == leave_date).first()

    def create_leave(self, db: Session, doctor_id: str, leave_date: date, reason: Optional[str] = None) -> DoctorLeave:
        leave = DoctorLeave(
            doctor_id=doctor_id,
            leave_date=leave_date,
            reason=reason
        )
        db.add(leave)
        db.commit()
        db.refresh(leave)
        return leave

    def add_leave_no_commit(self, db: Session, doctor_id: str, leave_date: date, reason: Optional[str] = None) -> DoctorLeave:
        """Like create_leave but only flushes — caller controls the transaction
        boundary (used by DoctorLeaveService to keep leave creation and
        conflict handling in a single atomic transaction)."""
        leave = DoctorLeave(
            doctor_id=doctor_id,
            leave_date=leave_date,
            reason=reason
        )
        db.add(leave)
        db.flush()
        return leave

    def delete_leave(self, db: Session, doctor_id: str, leave_id: str) -> bool:
        leave = db.query(DoctorLeave).filter(DoctorLeave.id == leave_id, DoctorLeave.doctor_id == doctor_id).first()
        if leave:
            db.delete(leave)
            db.commit()
            return True
        return False


doctor_repository = DoctorRepository()
