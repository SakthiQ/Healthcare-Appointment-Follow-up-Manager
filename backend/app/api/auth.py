from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_current_user, rate_limited, rate_limited_per_user, require_role
from services.auth_service import auth_service
from schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    MessageResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    VerifyEmailRequest,
)
from models.user import User, UserRole

router = APIRouter(prefix="/auth", tags=["Authentication"])

# The same answer whether or not the address belongs to an account.
_LINK_SENT = MessageResponse(
    message="If that address belongs to an account, we have sent it an email with a link."
)


def _set_session_cookie(response: Response, result: TokenResponse) -> TokenResponse:
    """In cookie mode the token travels only in an httpOnly cookie, never in the body."""
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


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited("register", "REGISTER_RATE_LIMIT_PER_HOUR"))],
)
def register_user(
    req: UserRegisterRequest,
    db: Session = Depends(get_db)
):
    """Register a new user (Patient, Doctor, or Admin). Limited per client IP."""
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
    result = auth_service.login_user(db, req, client_ip=client_ip(request))
    return _set_session_cookie(response, result)


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


@router.post("/change-password", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def change_password(
    req: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(rate_limited_per_user("change-password", "CHANGE_PASSWORD_RATE_LIMIT_PER_HOUR")),
    db: Session = Depends(get_db)
):
    """Change the signed-in user's password. All other sessions are signed out; the
    response carries a fresh token for this one."""
    result = auth_service.change_password(db, current_user, req.current_password, req.new_password)
    return _set_session_cookie(response, result)


@router.post("/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Email a password-reset link. The answer is identical whether or not the address
    is registered. Limited per client IP and per email."""
    auth_service.request_password_reset(db, req.email, client_ip(request))
    return _LINK_SENT


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limited("auth-token", "AUTH_TOKEN_RATE_LIMIT_PER_HOUR"))],
)
def reset_password(
    req: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """Set a new password using the one-time token from the emailed link. Signs the
    account out everywhere."""
    auth_service.reset_password(db, req.token, req.new_password)


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limited("auth-token", "AUTH_TOKEN_RATE_LIMIT_PER_HOUR"))],
)
def verify_email(
    req: VerifyEmailRequest,
    db: Session = Depends(get_db)
):
    """Confirm an email address using the one-time token from the emailed link."""
    auth_service.verify_email(db, req.token)


@router.post("/resend-verification", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    req: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Send a fresh verification link. Same answer for any address; limited per IP and email."""
    auth_service.resend_verification(db, req.email, client_ip(request))
    return _LINK_SENT


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
