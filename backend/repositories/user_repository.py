from typing import Optional
from sqlalchemy.orm import Session
from models.user import User, UserRole
from models.doctor import Doctor


class UserRepository:
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
        role: UserRole = UserRole.PATIENT
    ) -> User:
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            full_name=full_name.strip(),
            role=role
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
