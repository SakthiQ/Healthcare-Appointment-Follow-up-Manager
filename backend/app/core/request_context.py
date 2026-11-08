"""Per-request context that services need but should not have to be passed.

The client IP is bound for the duration of each HTTP request so the audit log can record
it without every service method taking a `request` argument. A context variable (not a
global) keeps concurrent requests apart; the threadpool that runs synchronous route
handlers copies the context, so it is visible there too.
"""
from contextvars import ContextVar
from typing import Optional

client_ip_var: ContextVar[Optional[str]] = ContextVar("client_ip", default=None)


def current_client_ip() -> Optional[str]:
    return client_ip_var.get()


class RequestContextMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware) so it adds no buffering and cannot
    interfere with exception handling or streaming."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        token = client_ip_var.set(client[0] if client else None)
        try:
            await self.app(scope, receive, send)
        finally:
            client_ip_var.reset(token)
