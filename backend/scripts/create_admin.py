"""Create the first ADMIN account directly in the database.

There is deliberately no API endpoint that creates an admin. Run this once
against the deployed database, from your own machine:

    cd backend
    DATABASE_URL="postgresql://..." python -m scripts.create_admin --email admin@clinic.com --name "Clinic Admin"

The password is read from the ADMIN_PASSWORD environment variable, or prompted
for (hidden input) when that is unset. Run `alembic upgrade head` against the
same DATABASE_URL first if the backend has never booted against it.
"""
import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database import SessionLocal
from models.user import User, UserRole
from repositories.user_repository import user_repository

MIN_PASSWORD_LENGTH = 8


class CreateAdminError(Exception):
    pass


def create_admin(db: Session, email: str, full_name: str, password: str) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CreateAdminError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if not full_name.strip():
        raise CreateAdminError("Full name is required.")
    if user_repository.get_by_email(db, email):
        raise CreateAdminError(f"A user with email {email} already exists.")
    return user_repository.create(
        db=db,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=UserRole.ADMIN,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create an ADMIN account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Full name")
    args = parser.parse_args(argv)

    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Admin password: ")
        if password != getpass.getpass("Confirm password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1

    db = SessionLocal()
    try:
        user = create_admin(db, args.email, args.name, password)
    except CreateAdminError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"Created admin {user.email} ({user.id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
