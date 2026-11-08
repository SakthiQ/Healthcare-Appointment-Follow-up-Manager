import hashlib
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from sqlalchemy.orm import Session
from app.config import settings
from app.core.security import hash_password, verify_password, create_access_token
from app.core.datetime_utils import ensure_utc
from app.exceptions import ConflictError, ForbiddenError, TooManyRequestsError, UnauthorizedError, ValidationError
from repositories.login_throttle_repository import login_throttle_repository
from repositories.user_repository import user_repository
from schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse
from models.user import User, UserRole


def _throttle_key(email: str, client_ip: str) -> str:
    return hashlib.sha256(f"{email.strip().lower()}|{client_ip}".encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password("not-a-real-password")


class AuthService:
    def register_user(self, db: Session, req: UserRegisterRequest) -> UserResponse:
        # SECURITY: public self-registration must only ever create PATIENT
        # accounts. Doctor accounts are created by an admin (POST
        # /admin/doctors); admin accounts have no self-service path at all.
        # Without this check, anyone could POST {"role": "ADMIN"} here and
        # obtain a full admin account with no authentication whatsoever.
        if req.role != UserRole.PATIENT and not settings.ALLOW_PRIVILEGED_SELF_REGISTRATION:
            raise ForbiddenError(
                "Self-registration is only available for patients. "
                "Doctor accounts are created by an administrator."
            )

        existing = user_repository.get_by_email(db, req.email)
        if existing:
            raise ConflictError("A user with this email already exists.")

        if req.role == UserRole.DOCTOR and not req.specialization:
            raise ConflictError("Specialization is required when registering a doctor.")

        hashed_pw = hash_password(req.password)
        user = user_repository.create(
            db=db,
            email=req.email,
            password_hash=hashed_pw,
            full_name=req.full_name,
            role=req.role
        )

        if req.role == UserRole.DOCTOR and req.specialization:
            user_repository.create_doctor_profile(
                db=db,
                user_id=user.id,
                specialization=req.specialization
            )

        return UserResponse.model_validate(user)

    def login_user(self, db: Session, req: UserLoginRequest, client_ip: str = "unknown") -> TokenResponse:
        now = datetime.now(timezone.utc)
        throttle_key = _throttle_key(req.email, client_ip)
        throttle = login_throttle_repository.get(db, throttle_key)
        if throttle and throttle.locked_until and ensure_utc(throttle.locked_until) > now:
            retry_after = max(1, math.ceil((ensure_utc(throttle.locked_until) - now).total_seconds()))
            raise TooManyRequestsError(
                "Too many failed login attempts. Please try again later.", retry_after_seconds=retry_after
            )

        def fail() -> UnauthorizedError:
            login_throttle_repository.record_failure(
                db, throttle_key, now,
                max_attempts=settings.LOGIN_MAX_FAILED_ATTEMPTS,
                window=timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES),
            )
            return UnauthorizedError("Invalid email or password.")

        user = user_repository.get_by_email(db, req.email)
        if not user:
            # Do the same bcrypt work as a real check, so response time doesn't
            # reveal which emails are registered.
            verify_password(req.password, _dummy_password_hash())
            raise fail()

        if not verify_password(req.password, user.password_hash):
            raise fail()

        if not user.is_active:
            raise UnauthorizedError("User account is inactive.")

        login_throttle_repository.clear(db, throttle_key)

        token_payload = {
            "sub": user.id,
            "email": user.email,
            "role": user.role.value,
            "tv": user.token_version or 0,
        }
        access_token = create_access_token(token_payload)

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user)
        )


    def logout_user(self, db: Session, user: User) -> None:
        """Sign the user out everywhere: every token issued so far stops working."""
        user_repository.bump_token_version(db, user)


auth_service = AuthService()
