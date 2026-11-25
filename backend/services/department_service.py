from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, ValidationError
from models.department import Department
from models.doctor import Doctor
from models.user import User
from schemas.department import DepartmentCreateRequest, DepartmentResponse, DepartmentUpdateRequest


class DepartmentService:
    def _name_taken(self, db: Session, name: str, except_id: Optional[str] = None) -> bool:
        query = db.query(Department).filter(func.lower(Department.name) == name.lower())
        if except_id:
            query = query.filter(Department.id != except_id)
        return db.query(query.exists()).scalar()

    def _counts(self, db: Session) -> dict:
        """Active, bookable doctors per department, in one GROUP BY query."""
        rows = (
            db.query(Doctor.department_id, func.count(Doctor.id))
            .join(User, Doctor.user_id == User.id)
            .filter(Doctor.department_id.isnot(None), Doctor.is_active.is_(True), User.is_active.is_(True))
            .group_by(Doctor.department_id)
            .all()
        )
        return dict(rows)

    def _response(self, dept: Department, counts: dict) -> DepartmentResponse:
        return DepartmentResponse(id=dept.id, name=dept.name, description=dept.description,
                                  is_active=dept.is_active, active_doctor_count=counts.get(dept.id, 0))

    def list(self, db: Session, active_only: bool) -> List[DepartmentResponse]:
        query = db.query(Department)
        if active_only:
            query = query.filter(Department.is_active.is_(True))
        counts = self._counts(db)
        return [self._response(d, counts) for d in query.order_by(Department.name).all()]

    def create(self, db: Session, req: DepartmentCreateRequest) -> DepartmentResponse:
        if self._name_taken(db, req.name):
            raise ConflictError(f"A department called {req.name!r} already exists.")
        dept = Department(name=req.name, description=req.description, is_active=True)
        db.add(dept)
        db.commit()
        db.refresh(dept)
        return self._response(dept, {})

    def update(self, db: Session, department_id: str, req: DepartmentUpdateRequest) -> DepartmentResponse:
        dept = db.get(Department, department_id)
        if not dept:
            raise NotFoundError("Department not found.")
        if req.name is not None:
            if self._name_taken(db, req.name, except_id=dept.id):
                raise ConflictError(f"A department called {req.name!r} already exists.")
            dept.name = req.name
        if "description" in req.model_fields_set:
            dept.description = req.description
        if req.is_active is not None:
            dept.is_active = req.is_active
        db.commit()
        db.refresh(dept)
        return self._response(dept, self._counts(db))

    def check_assignable(self, db: Session, department_id: Optional[str]) -> None:
        """A doctor can join an existing, active department, or none (None)."""
        if department_id is None:
            return
        dept = db.get(Department, department_id)
        if dept is None:
            raise NotFoundError("Department not found.")
        if not dept.is_active:
            raise ValidationError("That department is deactivated. Reactivate it first.")


department_service = DepartmentService()
