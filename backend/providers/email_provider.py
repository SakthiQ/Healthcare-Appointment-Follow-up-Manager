"""Email provider abstraction. Used exclusively by NotificationService — never
called directly from appointment/AI/leave services, so email delivery can
never block or invalidate appointment logic (see docs/system-design.md)."""
import abc
import logging
import smtplib
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


class EmailProviderError(Exception):
    """Base class for email delivery failures."""


class EmailProviderTransientError(EmailProviderError):
    """Retryable: connection refused, timeout, temporary server error, etc."""


class EmailProviderPermanentError(EmailProviderError):
    """Not retryable: invalid recipient address, auth rejected, etc."""


class EmailProvider(abc.ABC):
    @abc.abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> None:
        """Raise EmailProviderTransientError / EmailProviderPermanentError on failure."""


class MockEmailProvider(EmailProvider):
    """DEMO_MODE provider — never touches the network. Records every send in
    an in-memory list so tests/demos can assert on what would have been sent."""

    def __init__(self):
        self.sent_emails = []

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.sent_emails.append({"to": to_email, "subject": subject, "body": body})
        logger.info("MockEmailProvider: would send to=%s subject=%r", to_email, subject)


class RealEmailProvider(EmailProvider):
    """Sends via SMTP. Any SMTP-compatible provider (SendGrid, Mailgun, SES,
    Gmail, etc.) works by pointing SMTP_HOST/PORT/USERNAME/PASSWORD at it —
    no vendor-specific SDK required."""

    def __init__(self):
        self._host = settings.SMTP_HOST
        self._port = settings.SMTP_PORT
        self._username = settings.SMTP_USERNAME
        self._password = settings.SMTP_PASSWORD
        self._use_tls = settings.SMTP_USE_TLS
        self._timeout = settings.SMTP_TIMEOUT_SECONDS
        self._from_address = settings.EMAIL_FROM_ADDRESS

    def send(self, to_email: str, subject: str, body: str) -> None:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = self._from_address
        message["To"] = to_email

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                if self._use_tls:
                    smtp.starttls()
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.sendmail(self._from_address, [to_email], message.as_string())
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailProviderPermanentError(f"Recipient refused: {exc}") from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailProviderPermanentError(f"SMTP authentication failed: {exc}") from exc
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError) as exc:
            raise EmailProviderTransientError(f"SMTP connection failed: {exc}") from exc
        except smtplib.SMTPException as exc:
            raise EmailProviderTransientError(f"SMTP error: {exc}") from exc


def get_email_provider() -> EmailProvider:
    """Resolve the active provider based on current settings (read live, not
    cached, so DEMO_MODE toggles and test overrides take effect immediately).
    EMAIL_DEMO_MODE, when set, overrides DEMO_MODE for this integration only."""
    if settings.email_demo_mode:
        return MockEmailProvider()
    return RealEmailProvider()
