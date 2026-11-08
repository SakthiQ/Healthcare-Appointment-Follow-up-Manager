from typing import Optional
from sqlalchemy.orm import Session
from models.user import User, UserRole
from models.doctor import Doctor


class UserRepository:
    def bump_token_version(self, db: Session, user: User) -> None:
        """Invalidate every access token issued to this user so far."""
        user.token_version = (user.token_version or 0) + 1
        db.commit()

    def set_password(self, db: Session, user: User, password_hash: str) -> None:
        """New password hash AND every existing token revoked, in one commit."""
        user.password_hash = password_hash
        user.token_version = (user.token_version or 0) + 1
        db.commit()

    def get_by_id(self, db: Session, user_id: str) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        return db.query(User).filter(User.email == email.lower().strip()).first()

    def create(
        self,
        db: Session,
        email: str,
        password_hash: str,
        full_name: str,
        role: UserRole = UserRole.PATIENT,
        email_verified: bool = False,
    ) -> User:
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            full_name=full_name.strip(),
            role=role,
            email_verified=email_verified,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def create_doctor_profile(
        self,
        db: Session,
        user_id: str,
        specialization: str
    ) -> Doctor:
        doctor = Doctor(
            user_id=user_id,
            specialization=specialization.strip()
        )
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
        return doctor


user_repository = UserRepository()
