import hashlib
import logging
import math
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from sqlalchemy.orm import Session
from app.config import settings
from app.core.datetime_utils import ensure_utc
from app.core.security import hash_password, verify_password, create_access_token
from app.exceptions import ConflictError, ForbiddenError, TooManyRequestsError, UnauthorizedError, ValidationError
from models.notification import NotificationType
from models.security import AuthTokenPurpose
from models.user import User, UserRole
from repositories.auth_token_repository import auth_token_repository
from repositories.login_throttle_repository import login_throttle_repository
from repositories.user_repository import user_repository
from schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse
from services.audit_service import audit_service
from services.notification_service import notification_service
from services.rate_limit_service import rate_limit_service

logger = logging.getLogger(__name__)

INVALID_LINK_MESSAGE = "This link is invalid or has expired. Please request a new one."


def _throttle_key(email: str, client_ip: str) -> str:
    return hashlib.sha256(f"{email.strip().lower()}|{client_ip}".encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password("not-a-real-password")


class AuthService:
    # ------------------------------------------------------------------ sessions
    def issue_token(self, user: User) -> TokenResponse:
        token_payload = {
            "sub": user.id,
            "email": user.email,
            "role": user.role.value,
            "tv": user.token_version or 0,
        }
        return TokenResponse(
            access_token=create_access_token(token_payload),
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )

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

        audit_service.record(db, "user.register", actor=user, resource_type="user", resource_id=user.id)
        self._send_verification_email(db, user)
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

        def fail(user_id=None) -> UnauthorizedError:
            row = login_throttle_repository.record_failure(
                db, throttle_key, now,
                max_attempts=settings.LOGIN_MAX_FAILED_ATTEMPTS,
                window=timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES),
            )
            try:
                if row.locked_until and row.failed_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                    audit_service.record(
                        db, "auth.login.lockout", resource_type="user", resource_id=user_id,
                        detail={"email": req.email.strip().lower()[:120]},
                    )
            except Exception:
                logger.exception("could not audit login lockout")
            return UnauthorizedError("Invalid email or password.")

        user = user_repository.get_by_email(db, req.email)
        if not user:
            # Do the same bcrypt work as a real check, so response time doesn't
            # reveal which emails are registered.
            verify_password(req.password, _dummy_password_hash())
            raise fail()

        if not verify_password(req.password, user.password_hash):
            raise fail(user.id)

        if not user.is_active:
            raise UnauthorizedError("User account is inactive.")

        if settings.REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
            # Only reachable with the right password, so it does not reveal which emails exist.
            raise ForbiddenError(
                "Please verify your email address before signing in. "
                "Use the link we emailed you, or request a new one."
            )

        login_throttle_repository.clear(db, throttle_key)
        audit_service.record(db, "auth.login", actor=user, resource_type="user", resource_id=user.id)
        return self.issue_token(user)

    def logout_user(self, db: Session, user: User) -> None:
        """Sign the user out everywhere: every token issued so far stops working."""
        user_repository.bump_token_version(db, user)
        audit_service.record(db, "auth.logout", actor=user, resource_type="user", resource_id=user.id)

    # ------------------------------------------------------------------ passwords
    def change_password(self, db: Session, user: User, current_password: str, new_password: str) -> TokenResponse:
        """Change the signed-in user's password. Every other session is signed out; the
        caller gets a fresh token so this one carries on."""
        if not verify_password(current_password, user.password_hash):
            # 422, not 401: the frontend treats any 401 as "your session expired".
            raise ValidationError("Current password is incorrect.")
        if verify_password(new_password, user.password_hash):
            raise ValidationError("Choose a password different from your current one.")
        user_repository.set_password(db, user, hash_password(new_password))
        audit_service.record(db, "auth.password.change", actor=user, resource_type="user", resource_id=user.id)
        return self.issue_token(user)

    def request_password_reset(self, db: Session, email: str, client_ip: str) -> None:
        """Email a one-time reset link if the address belongs to an active account.

        Always returns normally and the same way, whether or not the account exists, so
        the endpoint cannot be used to find out who is registered. Limited per client IP
        and per target email, so it cannot be used to flood someone's inbox.
        """
        rate_limit_service.check(db, "password-reset-ip", client_ip, settings.PASSWORD_RESET_RATE_LIMIT_PER_HOUR)
        rate_limit_service.check(db, "password-reset-email", email, settings.PASSWORD_RESET_EMAIL_RATE_LIMIT_PER_HOUR)

        user = user_repository.get_by_email(db, email)
        audit_service.record(
            db, "auth.password.reset.request", resource_type="user",
            resource_id=user.id if user else None, detail={"email": email.strip().lower()[:120]},
        )
        if user is None or not user.is_active:
            return
        try:
            self._email_token_link(
                db, user, AuthTokenPurpose.PASSWORD_RESET, NotificationType.PASSWORD_RESET,
                path="reset-password",
                ttl=timedelta(minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES),
                payload_extra={"expires_minutes": settings.PASSWORD_RESET_TOKEN_TTL_MINUTES},
            )
        except Exception:
            # The caller must see the same answer either way; the failure is logged.
            self._reset_if_failed(db)
            logger.exception("Could not queue the password reset email for user %s", user.id)

    def reset_password(self, db: Session, token: str, new_password: str) -> None:
        now = datetime.now(timezone.utc)
        row = auth_token_repository.get_usable(db, AuthTokenPurpose.PASSWORD_RESET, _hash_token(token), now, for_update=True)
        user = user_repository.get_by_id(db, row.user_id) if row else None
        if row is None or user is None or not user.is_active:
            raise ValidationError(INVALID_LINK_MESSAGE)

        row.used_at = now
        # Any other outstanding reset link for this user dies with this one.
        auth_token_repository.invalidate_unused(db, user.id, AuthTokenPurpose.PASSWORD_RESET, now)
        # One commit: the token is spent, the password changes and every session is signed out.
        user_repository.set_password(db, user, hash_password(new_password))
        audit_service.record(db, "auth.password.reset", actor=user, resource_type="user", resource_id=user.id)

    # ------------------------------------------------------------------ email verification
    def verify_email(self, db: Session, token: str) -> None:
        now = datetime.now(timezone.utc)
        row = auth_token_repository.get_usable(db, AuthTokenPurpose.EMAIL_VERIFICATION, _hash_token(token), now, for_update=True)
        user = user_repository.get_by_id(db, row.user_id) if row else None
        if row is None or user is None:
            raise ValidationError(INVALID_LINK_MESSAGE)
        row.used_at = now
        user.email_verified = True
        db.commit()
        audit_service.record(db, "auth.email.verify", actor=user, resource_type="user", resource_id=user.id)

    def resend_verification(self, db: Session, email: str, client_ip: str) -> None:
        """Send a fresh verification link if the account exists and is not yet verified.
        Same answer either way, and limited like the password-reset request."""
        rate_limit_service.check(db, "verify-resend-ip", client_ip, settings.PASSWORD_RESET_RATE_LIMIT_PER_HOUR)
        rate_limit_service.check(db, "verify-resend-email", email, settings.PASSWORD_RESET_EMAIL_RATE_LIMIT_PER_HOUR)
        user = user_repository.get_by_email(db, email)
        if user is None or not user.is_active or user.email_verified:
            return
        self._send_verification_email(db, user)

    def _send_verification_email(self, db: Session, user: User) -> None:
        """Best-effort: a problem sending this email must never fail a registration."""
        try:
            self._email_token_link(
                db, user, AuthTokenPurpose.EMAIL_VERIFICATION, NotificationType.EMAIL_VERIFICATION,
                path="verify-email",
                ttl=timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_TTL_HOURS),
                payload_extra={"expires_hours": settings.EMAIL_VERIFICATION_TOKEN_TTL_HOURS},
            )
        except Exception:
            self._reset_if_failed(db)
            logger.exception("Could not queue the verification email for user %s", user.id)

    @staticmethod
    def _reset_if_failed(db: Session) -> None:
        """Roll back only if the failure left the session unusable (a failed flush). A plain
        exception in the email step leaves nothing half-done to undo, and an unconditional
        rollback here would also discard unrelated work in the caller's transaction."""
        if not db.is_active:
            db.rollback()

    def _email_token_link(
        self, db: Session, user: User, purpose: AuthTokenPurpose, notification_type: NotificationType,
        path: str, ttl: timedelta, payload_extra: dict,
    ) -> None:
        """Create a single-use token (replacing any older one), and queue the email carrying its link."""
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(32)
        auth_token_repository.invalidate_unused(db, user.id, purpose, now)
        auth_token_repository.create(db, user.id, purpose, _hash_token(token), now + ttl)
        link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/{path}?token={token}"
        notification_service.queue_notification(
            db, appointment_id=None, recipient_id=user.id, notification_type=notification_type,
            payload={"link": link, **payload_extra},
        )


auth_service = AuthService()
