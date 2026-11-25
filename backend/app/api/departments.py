from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from models.user import User, UserRole
from schemas.department import DepartmentCreateRequest, DepartmentResponse, DepartmentUpdateRequest
from services.audit_service import audit_service
from services.department_service import department_service

router = APIRouter(tags=["Departments"])


@router.get("/departments", response_model=List[DepartmentResponse], status_code=status.HTTP_200_OK)
def list_departments(db: Session = Depends(get_db)):
    """Public: active departments, with how many active doctors each has."""
    return department_service.list(db, active_only=True)


@router.get("/admin/departments", response_model=List[DepartmentResponse], status_code=status.HTTP_200_OK)
def admin_list_departments(
    current_user: User = Depends(require_role(UserRole.ADMIN)), db: Session = Depends(get_db)
):
    """Every department, deactivated ones included."""
    return department_service.list(db, active_only=False)


@router.post("/admin/departments", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(
    req: DepartmentCreateRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Create a department. Names are unique regardless of case (409 on a clash)."""
    result = department_service.create(db, req)
    audit_service.record(db, "department.create", actor=current_user, resource_type="department",
                         resource_id=result.id, detail={"name": result.name})
    return result


@router.patch("/admin/departments/{department_id}", response_model=DepartmentResponse, status_code=status.HTTP_200_OK)
def update_department(
    department_id: str,
    req: DepartmentUpdateRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Rename, re-describe, deactivate or reactivate a department."""
    result = department_service.update(db, department_id, req)
    audit_service.record(db, "department.update", actor=current_user, resource_type="department",
                         resource_id=department_id,
                         detail={k: v for k, v in req.model_dump(exclude_unset=True).items() if k != "description"})
    return result
