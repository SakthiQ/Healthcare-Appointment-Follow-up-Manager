from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from services.auth_service import auth_service
from schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse
from models.user import User, UserRole

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    req: UserRegisterRequest,
    db: Session = Depends(get_db)
):
    """Register a new user (Patient, Doctor, or Admin)."""
    return auth_service.register_user(db, req)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login_user(
    req: UserLoginRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user credentials and return JWT token."""
    return auth_service.login_user(db, req)


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    """Get current authenticated user profile."""
    return UserResponse.model_validate(current_user)


@router.get("/patient-only", status_code=status.HTTP_200_OK)
def patient_only_endpoint(
    current_user: User = Depends(require_role(UserRole.PATIENT))
):
    """Endpoint accessible only by users with PATIENT role."""
    return {"message": "Access granted to Patient portal", "user_id": current_user.id}


@router.get("/doctor-only", status_code=status.HTTP_200_OK)
def doctor_only_endpoint(
    current_user: User = Depends(require_role(UserRole.DOCTOR))
):
    """Endpoint accessible only by users with DOCTOR role."""
    return {"message": "Access granted to Doctor portal", "user_id": current_user.id}


@router.get("/admin-only", status_code=status.HTTP_200_OK)
def admin_only_endpoint(
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """Endpoint accessible only by users with ADMIN role."""
    return {"message": "Access granted to Admin portal", "user_id": current_user.id}
