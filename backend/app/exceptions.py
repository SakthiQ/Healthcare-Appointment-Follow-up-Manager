from fastapi import Request, status
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Base application exception."""
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST, error_code: str = "BAD_REQUEST"):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND, error_code="NOT_FOUND")


class ConflictError(AppException):
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message, status_code=status.HTTP_409_CONFLICT, error_code="CONFLICT")


class ValidationError(AppException):
    def __init__(self, message: str = "Validation error"):
        super().__init__(message, status_code=422, error_code="VALIDATION_ERROR")




class UnauthorizedError(AppException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, status_code=status.HTTP_401_UNAUTHORIZED, error_code="UNAUTHORIZED")


class ForbiddenError(AppException):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN, error_code="FORBIDDEN")


async def app_exception_handler(request: Request, exc: AppException):
    """Handler for custom AppException hierarchy."""
    logger.warning(f"AppException: [{exc.error_code}] {exc.message} on {request.url.path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "error_code": exc.error_code}
    )


async def global_exception_handler(request: Request, exc: Exception):
    """Fallback handler for unhandled exceptions."""
    logger.error(f"Unhandled Exception: {exc} on {request.url.path}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred.", "error_code": "INTERNAL_ERROR"}
    )
