from typing import List, Callable, Optional
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings, Settings
from app.database import get_db
from app.core.security import decode_access_token
from app.exceptions import UnauthorizedError, ForbiddenError
from repositories.user_repository import user_repository
from services.rate_limit_service import rate_limit_service
from models.user import User, UserRole

security_scheme = HTTPBearer(auto_error=False)


def get_settings() -> Settings:
    """Dependency injection helper for app settings."""
    return settings


# A cross-site page can make the browser attach the session cookie to a request, but it
# cannot add a custom header without a CORS preflight, which only allow-listed origins
# pass. Requiring this header on state-changing cookie-authenticated requests is the CSRF
# defence (alongside the cookie's SameSite attribute). Bearer-token requests need none:
# the browser never attaches those by itself.
CSRF_HEADER = "X-CSRF-Protection"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Dependency to extract and validate current authenticated user from JWT token."""
    token = credentials.credentials if credentials and credentials.credentials else None
    if not token and settings.AUTH_COOKIE_MODE:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)
        if token and request.method not in _SAFE_METHODS and not request.headers.get(CSRF_HEADER):
            raise ForbiddenError(f"Missing {CSRF_HEADER} header on a cookie-authenticated request.")
    if not token:
        raise UnauthorizedError("Authentication token is required")

    payload = decode_access_token(token)
    
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    user = user_repository.get_by_id(db, user_id)
    if not user:
        raise UnauthorizedError("User no longer exists")

    if not user.is_active:
        raise UnauthorizedError("User account is inactive")

    # Tokens issued before this field existed carry no "tv" and count as version 0.
    if payload.get("tv", 0) != (user.token_version or 0):
        raise UnauthorizedError("This session has been signed out. Please log in again.")

    return user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """For public endpoints whose response differs by caller: the signed-in user,
    or None for anonymous callers and for a missing, expired or invalid token."""
    try:
        return get_current_user(request, credentials, db)
    except (UnauthorizedError, ForbiddenError):
        return None


def client_ip(request: Request) -> str:
    """The caller's IP. Behind a proxy this is the real one only if uvicorn runs with
    --proxy-headers (the Render blueprint does)."""
    return request.client.host if request.client else "unknown"


def rate_limited(bucket: str, limit_setting: str, window_seconds: int = 3600):
    """Dependency factory: at most `settings.<limit_setting>` requests per client IP per
    window to the routes that use it, else HTTP 429 with Retry-After."""
    def dependency(request: Request, db: Session = Depends(get_db)) -> None:
        rate_limit_service.check(db, bucket, client_ip(request), getattr(settings, limit_setting), window_seconds)
    return dependency


def rate_limited_per_user(bucket: str, limit_setting: str, window_seconds: int = 3600, roles: tuple = ()):
    """Like rate_limited, but per signed-in user. Returns the user, so a route can use it
    in place of get_current_user (or of require_role, when `roles` is given)."""
    def dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if roles and current_user.role not in roles:
            raise ForbiddenError(
                f"Access denied for role '{current_user.role.value}'. Allowed roles: {[r.value for r in roles]}"
            )
        rate_limit_service.check(db, bucket, current_user.id, getattr(settings, limit_setting), window_seconds)
        return current_user
    return dependency


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
