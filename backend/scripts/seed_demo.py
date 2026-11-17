"""Create demo accounts for local development: one admin, one doctor with working hours,
and one patient, so a contributor can sign in as each role straight away.

    cd backend
    python -m scripts.seed_demo

The accounts share a well-known password, so the script refuses to run unless the app is in
DEMO_MODE and ENVIRONMENT is not "production". Running it twice is safe: accounts that
already exist are left as they are.
"""
import sys
from datetime import time
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import hash_password
from app.database import SessionLocal
from models.user import UserRole
from repositories.doctor_repository import doctor_repository
from repositories.user_repository import user_repository
from schemas.doctor import WorkingHoursItem

DEMO_PASSWORD = "demo-password"

ADMIN_EMAIL = "admin@demo.example.com"
DOCTOR_EMAIL = "doctor@demo.example.com"
PATIENT_EMAIL = "patient@demo.example.com"


class SeedRefused(Exception):
    pass


def check_allowed(environment: str, demo_mode: bool) -> None:
    if environment.strip().lower() == "production":
        raise SeedRefused("Refusing to seed demo accounts: ENVIRONMENT is production.")
    if not demo_mode:
        raise SeedRefused("Refusing to seed demo accounts: DEMO_MODE is off.")


def _ensure_user(db: Session, email: str, full_name: str, role: UserRole) -> Tuple[object, bool]:
    existing = user_repository.get_by_email(db, email)
    if existing:
        return existing, False
    user = user_repository.create(
        db=db,
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
        full_name=full_name,
        role=role,
        email_verified=True,
    )
    return user, True


def seed(db: Session) -> List[str]:
    """Create whatever demo accounts are missing; return one line per account."""
    lines = []

    _, created = _ensure_user(db, ADMIN_EMAIL, "Demo Admin", UserRole.ADMIN)
    lines.append(f"{'created' if created else 'exists '}  ADMIN    {ADMIN_EMAIL}")

    doctor_user, created = _ensure_user(db, DOCTOR_EMAIL, "Dr Demo", UserRole.DOCTOR)
    doctor: Optional[object] = doctor_repository.get_by_user_id(db, doctor_user.id)
    if doctor is None:
        doctor = doctor_repository.create_doctor(
            db=db,
            user_id=doctor_user.id,
            specialization="General Practice",
            slot_duration=30,
            timezone="UTC",
        )
        # Monday to Friday, 09:00-17:00 UTC.
        doctor_repository.upsert_working_hours(
            db,
            doctor.id,
            [WorkingHoursItem(day_of_week=d, start_time=time(9), end_time=time(17)) for d in range(5)],
        )
    lines.append(f"{'created' if created else 'exists '}  DOCTOR   {DOCTOR_EMAIL}  (Mon-Fri 09:00-17:00 UTC)")

    _, created = _ensure_user(db, PATIENT_EMAIL, "Pat Demo", UserRole.PATIENT)
    lines.append(f"{'created' if created else 'exists '}  PATIENT  {PATIENT_EMAIL}")
    return lines


def main() -> int:
    try:
        check_allowed(settings.ENVIRONMENT, settings.DEMO_MODE)
    except SeedRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        lines = seed(db)
    finally:
        db.close()

    print("Demo accounts (password for all three: %s)" % DEMO_PASSWORD)
    for line in lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
