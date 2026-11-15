"""Caps how many requests one web process works on at once.

Why: route handlers are synchronous, so each request runs on one of a fixed number of
worker threads and holds a database connection until its response has been sent. Sending
the response needs a worker thread too. If more requests are in flight than there are
connections, every worker thread can end up waiting for a connection while every
connection belongs to a request waiting for a worker thread. Nothing moves until the
pool's timeout fails some of them, and a burst of a few hundred requests stalled the
server for minutes, health check included.

With the cap, at most MAX_CONCURRENT_REQUESTS requests are worked on at once. A request
beyond that waits, without holding a thread or a connection, for up to
REQUEST_QUEUE_TIMEOUT_SECONDS for a place to free up, first come first served. Only if
none does is it answered 503 with Retry-After, which a client can retry. Short bursts are
absorbed; sustained overload turns into quick, honest "busy" answers instead of a stall.
The pool is sized to the cap (see DB_POOL_SIZE in app/config.py).
"""
import asyncio
import collections
import json

from app.config import settings

# Never capped: the platform's health check must keep answering under load, or the host
# would restart a server that is merely busy. CORS preflights do no database work.
_EXEMPT_PATHS = {"/health"}

# Requests allowed to wait for a place, per place. Beyond this, answer 503 at once: a
# queue far longer than the server can clear within the timeout only delays the answer.
_MAX_WAITING_PER_SLOT = 20

BUSY_MESSAGE = "The server is busy right now. Please try again in a moment."


class ConcurrencyLimitMiddleware:
    """Pure ASGI middleware. All requests of a process run on one event loop, so plain
    counters need no locking. A place is released only once the whole response has been
    sent and the request's database session closed, and is handed straight to the
    longest-waiting request."""

    def __init__(self, app, retry_after_seconds: int = 1):
        self.app = app
        self.retry_after_seconds = retry_after_seconds
        self.in_flight = 0
        self._waiters = collections.deque()

    async def __call__(self, scope, receive, send):
        # Read on every request so the limits can be changed in tests without rebuilding the app.
        limit = settings.MAX_CONCURRENT_REQUESTS
        if (
            scope["type"] != "http"
            or limit <= 0
            or scope.get("method") == "OPTIONS"
            or scope.get("path") in _EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        if not await self._acquire(limit, settings.REQUEST_QUEUE_TIMEOUT_SECONDS):
            await self._reject(send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self._release()

    async def _acquire(self, limit: int, wait_seconds: float) -> bool:
        # Join the back of the queue if anyone is already waiting, so nobody jumps it.
        if self.in_flight < limit and not self._waiters:
            self.in_flight += 1
            return True
        if wait_seconds <= 0 or len(self._waiters) >= limit * _MAX_WAITING_PER_SLOT:
            return False

        granted = asyncio.get_running_loop().create_future()
        self._waiters.append(granted)
        try:
            # shield: a timeout cancels the wait, not `granted`, so the check below can
            # still see a place that was handed over at the last moment.
            await asyncio.wait_for(asyncio.shield(granted), wait_seconds)
            return True
        except asyncio.TimeoutError:
            if granted.done() and not granted.cancelled():
                return True
            granted.cancel()
            return False
        except asyncio.CancelledError:
            # The request itself was cancelled while waiting. If it had just been given a
            # place, pass that place on rather than lose it.
            if granted.done() and not granted.cancelled():
                self._release()
            else:
                granted.cancel()
            raise
        finally:
            try:
                self._waiters.remove(granted)
            except ValueError:
                pass

    def _release(self) -> None:
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)  # the place passes to this waiter; in_flight is unchanged
                return
        self.in_flight -= 1

    async def _reject(self, send):
        body = json.dumps({"detail": BUSY_MESSAGE, "error_code": "SERVER_BUSY"}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"retry-after", str(self.retry_after_seconds).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
