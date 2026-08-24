from sqlalchemy.orm import Session
from app.config import settings
from app.core.security import hash_password, verify_password, create_access_token
from app.exceptions import ConflictError, ForbiddenError, UnauthorizedError, ValidationError
from repositories.user_repository import user_repository
from schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse
from models.user import User, UserRole


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

    def login_user(self, db: Session, req: UserLoginRequest) -> TokenResponse:
        user = user_repository.get_by_email(db, req.email)
        if not user:
            raise UnauthorizedError("Invalid email or password.")

        if not verify_password(req.password, user.password_hash):
            raise UnauthorizedError("Invalid email or password.")

        if not user.is_active:
            raise UnauthorizedError("User account is inactive.")

        token_payload = {
            "sub": user.id,
            "email": user.email,
            "role": user.role.value
        }
        access_token = create_access_token(token_payload)

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user)
        )


auth_service = AuthService()
