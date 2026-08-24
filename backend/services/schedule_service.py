from typing import List
from sqlalchemy.orm import Session
from app.exceptions import NotFoundError, ValidationError
from repositories.doctor_repository import doctor_repository
from schemas.doctor import WorkingHoursConfigRequest, WorkingHoursResponse


class ScheduleService:
    def configure_working_hours(
        self, db: Session, doctor_id: str, req: WorkingHoursConfigRequest
    ) -> List[WorkingHoursResponse]:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        # Business Validation
        days_seen = set()
        for item in req.working_hours:
            if item.day_of_week in days_seen:
                raise ValidationError(f"Duplicate working hours configured for day_of_week={item.day_of_week}")
            days_seen.add(item.day_of_week)

            if item.end_time <= item.start_time:
                raise ValidationError(f"Invalid schedule: end_time ({item.end_time}) must be after start_time ({item.start_time})")

        updated_hours = doctor_repository.upsert_working_hours(db, doctor_id, req.working_hours)
        return [WorkingHoursResponse.model_validate(h) for h in updated_hours]

    def get_working_hours(self, db: Session, doctor_id: str) -> List[WorkingHoursResponse]:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        hours = doctor_repository.get_working_hours(db, doctor_id)
        return [WorkingHoursResponse.model_validate(h) for h in hours]


schedule_service = ScheduleService()
