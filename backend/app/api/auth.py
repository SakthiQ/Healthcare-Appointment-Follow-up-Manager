from fastapi import APIRouter, Depends, Request, Response, status
from app.config import settings
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
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Authenticate user credentials and return JWT token. Repeated failures from
    one client IP for one email are locked out with HTTP 429. In cookie mode the token
    is set as an httpOnly cookie and the body's access_token is left empty."""
    client_ip = request.client.host if request.client else "unknown"
    result = auth_service.login_user(db, req, client_ip=client_ip)
    if settings.AUTH_COOKIE_MODE:
        response.set_cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=result.access_token,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            path="/",
        )
        result.access_token = ""
    return result


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Invalidate every access token issued to the current user (all devices) and
    clear the session cookie."""
    auth_service.logout_user(db, current_user)
    response.delete_cookie(settings.AUTH_COOKIE_NAME, path="/")


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
