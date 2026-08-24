"""
Google Calendar provider abstraction (Phase 10).

Used exclusively by CalendarService — never called from route handlers or
from the appointment transaction, so a Google outage can never block or
invalidate a booking (see docs/failure-handling.md).
"""
import abc
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CalendarProviderError(Exception):
    """Base class for calendar provider failures."""


class CalendarProviderTransientError(CalendarProviderError):
    """Retryable: timeout, 5xx, rate limit, connection refused."""


class CalendarProviderPermanentError(CalendarProviderError):
    """Not retryable: bad credentials, malformed request, forbidden."""


class CalendarEventNotFoundError(CalendarProviderError):
    """The external event no longer exists (already deleted, or never created).
    Treated as success for delete, and as "recreate" for update."""


class CalendarProvider(abc.ABC):
    @abc.abstractmethod
    def create_event(
        self, event_id: str, summary: str, description: str,
        start_time: datetime, end_time: datetime, attendee_email: Optional[str] = None
    ) -> str:
        """Create an event and return its external event id.

        `event_id` is a caller-supplied stable id used for idempotency: creating
        twice with the same id must NOT produce two events — the second call
        should return the same id rather than duplicating.
        """

    @abc.abstractmethod
    def update_event(
        self, external_event_id: str, summary: str, description: str,
        start_time: datetime, end_time: datetime
    ) -> None:
        ...

    @abc.abstractmethod
    def delete_event(self, external_event_id: str) -> None:
        ...


class MockCalendarProvider(CalendarProvider):
    """DEMO_MODE provider — never touches the network. Keeps events in memory
    so tests/demos can assert on calendar state without Google credentials."""

    def __init__(self):
        self.events = {}

    def create_event(
        self, event_id: str, summary: str, description: str,
        start_time: datetime, end_time: datetime, attendee_email: Optional[str] = None
    ) -> str:
        # Idempotent by construction: same event_id overwrites rather than duplicating.
        self.events[event_id] = {
            "summary": summary,
            "description": description,
            "start_time": start_time,
            "end_time": end_time,
            "attendee_email": attendee_email,
        }
        logger.info("MockCalendarProvider: created event %s (%r)", event_id, summary)
        return event_id

    def update_event(
        self, external_event_id: str, summary: str, description: str,
        start_time: datetime, end_time: datetime
    ) -> None:
        if external_event_id not in self.events:
            raise CalendarEventNotFoundError(f"Event {external_event_id} not found.")
        self.events[external_event_id].update({
            "summary": summary,
            "description": description,
            "start_time": start_time,
            "end_time": end_time,
        })

    def delete_event(self, external_event_id: str) -> None:
        if external_event_id not in self.events:
            raise CalendarEventNotFoundError(f"Event {external_event_id} not found.")
        del self.events[external_event_id]


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar API v3 via OAuth 2.0 refresh-token flow.

    Credentials come exclusively from environment variables (see app/config.py
    and .env.example) — never hardcoded. The refresh token is obtained once
    out-of-band through the OAuth consent flow; this class exchanges it for a
    short-lived access token and caches that until shortly before expiry.
    """

    def __init__(self):
        self._client_id = settings.GOOGLE_CLIENT_ID
        self._client_secret = settings.GOOGLE_CLIENT_SECRET
        self._refresh_token = settings.GOOGLE_REFRESH_TOKEN
        self._token_uri = settings.GOOGLE_TOKEN_URI
        self._base_url = settings.GOOGLE_CALENDAR_API_BASE_URL
        self._calendar_id = settings.GOOGLE_CALENDAR_ID
        self._timeout = settings.GOOGLE_CALENDAR_TIMEOUT_SECONDS

        self._access_token: Optional[str] = None
        self._access_token_expires_at: Optional[datetime] = None
        self._token_lock = threading.Lock()

    # --- OAuth 2.0 ---
    def _get_access_token(self) -> str:
        if not (self._client_id and self._client_secret and self._refresh_token):
            raise CalendarProviderPermanentError(
                "Google OAuth credentials are not configured "
                "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN)."
            )

        with self._token_lock:
            now = datetime.now(timezone.utc)
            if self._access_token and self._access_token_expires_at and now < self._access_token_expires_at:
                return self._access_token

            try:
                response = httpx.post(
                    self._token_uri,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": self._refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                raise CalendarProviderTransientError(f"OAuth token request timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise CalendarProviderTransientError(f"OAuth token request failed: {exc}") from exc

            if response.status_code >= 500:
                raise CalendarProviderTransientError(f"OAuth token endpoint error {response.status_code}")
            if response.status_code >= 400:
                raise CalendarProviderPermanentError(
                    f"OAuth token refresh rejected ({response.status_code}): {response.text}"
                )

            body = response.json()
            self._access_token = body["access_token"]
            expires_in = int(body.get("expires_in", 3600))
            # Refresh a minute early to avoid using a token that expires mid-request.
            self._access_token_expires_at = now + timedelta(seconds=max(expires_in - 60, 30))
            return self._access_token

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = self._get_access_token()
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise CalendarProviderTransientError(f"Calendar API request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise CalendarProviderTransientError(f"Calendar API request failed: {exc}") from exc

        if response.status_code == 404:
            raise CalendarEventNotFoundError(f"Calendar event not found: {response.text}")
        if response.status_code == 429 or response.status_code >= 500:
            raise CalendarProviderTransientError(
                f"Calendar API transient error {response.status_code}: {response.text}"
            )
        if response.status_code >= 400 and response.status_code != 409:
            raise CalendarProviderPermanentError(
                f"Calendar API error {response.status_code}: {response.text}"
            )
        return response

    @staticmethod
    def _event_body(summary: str, description: str, start_time: datetime, end_time: datetime) -> dict:
        return {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
        }

    def create_event(
        self, event_id: str, summary: str, description: str,
        start_time: datetime, end_time: datetime, attendee_email: Optional[str] = None
    ) -> str:
        body = self._event_body(summary, description, start_time, end_time)
        # Supplying our own id makes create idempotent: a retried create hits
        # 409 "duplicate" instead of inserting a second event.
        body["id"] = event_id
        if attendee_email:
            body["attendees"] = [{"email": attendee_email}]

        response = self._request("POST", f"/calendars/{self._calendar_id}/events", json=body)

        if response.status_code == 409:
            # Already created by a previous attempt — same event, not a duplicate.
            logger.info("GoogleCalendarProvider: event %s already exists, treating as created", event_id)
            return event_id

        return response.json().get("id", event_id)

    def update_event(
        self, external_event_id: str, summary: str, description: str,
        start_time: datetime, end_time: datetime
    ) -> None:
        self._request(
            "PATCH",
            f"/calendars/{self._calendar_id}/events/{external_event_id}",
            json=self._event_body(summary, description, start_time, end_time),
        )

    def delete_event(self, external_event_id: str) -> None:
        self._request("DELETE", f"/calendars/{self._calendar_id}/events/{external_event_id}")


def get_calendar_provider() -> CalendarProvider:
    """Resolve the active provider from current settings (read live, not
    cached, so DEMO_MODE toggles and test overrides take effect immediately)."""
    if settings.DEMO_MODE:
        return MockCalendarProvider()
    return GoogleCalendarProvider()
