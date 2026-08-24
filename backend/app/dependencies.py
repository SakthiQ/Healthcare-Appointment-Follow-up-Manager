from typing import List, Callable
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings, Settings
from app.database import get_db
from app.core.security import decode_access_token
from app.exceptions import UnauthorizedError, ForbiddenError
from repositories.user_repository import user_repository
from models.user import User, UserRole

security_scheme = HTTPBearer(auto_error=False)


def get_settings() -> Settings:
    """Dependency injection helper for app settings."""
    return settings


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Dependency to extract and validate current authenticated user from JWT token."""
    if not credentials or not credentials.credentials:
        raise UnauthorizedError("Authentication token is required")

    token = credentials.credentials
    payload = decode_access_token(token)
    
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    user = user_repository.get_by_id(db, user_id)
    if not user:
        raise UnauthorizedError("User no longer exists")

    if not user.is_active:
        raise UnauthorizedError("User account is inactive")

    return user


def require_role(*allowed_roles: UserRole):
    """Dependency factory returning a function that enforces server-side role checks."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenError(f"Access denied for role '{current_user.role.value}'. Allowed roles: {[r.value for r in allowed_roles]}")
        return current_user
    return role_checker


def check_resource_ownership(current_user: User, resource_owner_id: str):
    """Helper to verify that patients/doctors can only access their own data unless they are ADMIN."""
    if current_user.role == UserRole.ADMIN:
        return
    if current_user.id != resource_owner_id:
        raise ForbiddenError("You do not have permission to access this resource")
