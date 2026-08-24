from typing import List
from sqlalchemy.orm import Session
from app.exceptions import NotFoundError
from repositories.doctor_repository import doctor_repository
from schemas.doctor import DoctorLeaveResponse


class LeaveService:
    """Read/delete operations on doctor leave dates. Leave *creation* lives in
    DoctorLeaveService (services/doctor_leave_service.py) since Phase 8 —
    creating a leave must also detect and resolve appointment conflicts in
    the same transaction, which belongs with that dedicated service rather
    than here."""

    def get_leaves(self, db: Session, doctor_id: str) -> List[DoctorLeaveResponse]:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        leaves = doctor_repository.get_leaves(db, doctor_id)
        return [DoctorLeaveResponse.model_validate(l) for l in leaves]

    def delete_leave(self, db: Session, doctor_id: str, leave_id: str):
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        success = doctor_repository.delete_leave(db, doctor_id, leave_id)
        if not success:
            raise NotFoundError("Leave record not found.")


leave_service = LeaveService()
