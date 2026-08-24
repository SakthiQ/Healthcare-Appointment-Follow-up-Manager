from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.exceptions import NotFoundError, ConflictError, ValidationError
from repositories.user_repository import user_repository
from repositories.doctor_repository import doctor_repository
from schemas.doctor import DoctorCreateRequest, DoctorUpdateRequest, DoctorResponse
from models.user import UserRole, User
from models.doctor import Doctor


class DoctorService:
    def _to_response(self, doctor: Doctor) -> DoctorResponse:
        return DoctorResponse(
            id=doctor.id,
            user_id=doctor.user_id,
            email=doctor.user.email,
            full_name=doctor.user.full_name,
            specialization=doctor.specialization,
            slot_duration_minutes=doctor.slot_duration_minutes,
            is_active=doctor.is_active,
            created_at=doctor.created_at
        )

    def create_doctor(self, db: Session, req: DoctorCreateRequest) -> DoctorResponse:
        existing = user_repository.get_by_email(db, req.email)
        if existing:
            raise ConflictError("A user with this email already exists.")

        hashed_pw = hash_password(req.password)
        user = user_repository.create(
            db=db,
            email=req.email,
            password_hash=hashed_pw,
            full_name=req.full_name,
            role=UserRole.DOCTOR
        )

        doctor = doctor_repository.create_doctor(
            db=db,
            user_id=user.id,
            specialization=req.specialization,
            slot_duration=req.slot_duration_minutes
        )

        return self._to_response(doctor)

    def update_doctor(self, db: Session, doctor_id: str, req: DoctorUpdateRequest) -> DoctorResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        updated_doctor = doctor_repository.update_doctor(
            db=db,
            doctor=doctor,
            specialization=req.specialization,
            slot_duration=req.slot_duration_minutes,
            is_active=req.is_active
        )
        return self._to_response(updated_doctor)

    def set_active_status(self, db: Session, doctor_id: str, is_active: bool) -> DoctorResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        updated_doctor = doctor_repository.update_doctor(db=db, doctor=doctor, is_active=is_active)
        return self._to_response(updated_doctor)

    def get_doctor(self, db: Session, doctor_id: str) -> DoctorResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")
        return self._to_response(doctor)

    def search_doctors(self, db: Session, specialization: Optional[str] = None, active_only: bool = True) -> List[DoctorResponse]:
        doctors = doctor_repository.search(db, specialization=specialization, active_only=active_only)
        return [self._to_response(d) for d in doctors]


doctor_service = DoctorService()
