import logging
from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy.orm import Session
from app.config import settings
from app.core.datetime_utils import ensure_utc
from app.core.security import generate_token, hash_token
from app.exceptions import ConflictError, NotFoundError, ValidationError
from models.invitation import Invitation
from models.notification import NotificationType
from models.user import User
from repositories.invitation_repository import invitation_repository
from repositories.user_repository import user_repository
from schemas.invitation import (
    InvitationCreateRequest,
    InvitationCreatedResponse,
    InvitationLookupResponse,
    InvitationResponse,
)
from services.notification_service import notification_service

logger = logging.getLogger(__name__)

INVALID_INVITATION_MESSAGE = "This invitation is invalid, expired or already used. Ask an administrator for a new one."


class InvitationService:
    """Staff invitations. An admin invites a doctor or another admin by email; the invitee
    opens the link on the normal signup page, and the role comes from the invitation rather
    than from anything the invitee types. Accepting one happens in AuthService.register_user,
    so there is a single signup path for everyone."""

    @staticmethod
    def status_of(invitation: Invitation, now: datetime) -> str:
        if invitation.used_at is not None:
            return "ACCEPTED"
        if invitation.revoked_at is not None:
            return "REVOKED"
        if ensure_utc(invitation.expires_at) <= now:
            return "EXPIRED"
        return "PENDING"

    def to_response(self, invitation: Invitation, now: datetime) -> InvitationResponse:
        fields = {name: getattr(invitation, name) for name in InvitationResponse.model_fields if name != "status"}
        return InvitationResponse(status=self.status_of(invitation, now), **fields)

    def invite(self, db: Session, inviter: User, req: InvitationCreateRequest) -> InvitationCreatedResponse:
        email = req.email.strip().lower()
        if user_repository.get_by_email(db, email):
            raise ConflictError("A user with this email already exists.")

        now = datetime.now(timezone.utc)
        token = generate_token()
        # A fresh invitation replaces any older pending one to the same address (one live link).
        invitation_repository.revoke_pending_for_email(db, email, now)
        is_doctor = req.role == "DOCTOR"
        invitation = invitation_repository.create(
            db,
            email=email,
            role=req.role,
            full_name=req.full_name.strip() if req.full_name else None,
            specialization=req.specialization.strip() if is_doctor and req.specialization else None,
            slot_duration_minutes=(req.slot_duration_minutes or 30) if is_doctor else None,
            timezone=(req.timezone or "UTC") if is_doctor else None,
            token_hash=hash_token(token),
            invited_by=inviter.id,
            expires_at=now + timedelta(days=settings.INVITATION_TTL_DAYS),
        )

        link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/register?invite={token}"
        email_queued = True
        try:
            notification_service.queue_notification(
                db, appointment_id=None, recipient_id=None, recipient_email=email,
                notification_type=NotificationType.INVITATION,
                payload={
                    "link": link, "role": req.role, "invited_by": inviter.full_name,
                    "expires_days": settings.INVITATION_TTL_DAYS,
                },
            )
        except Exception:
            # The invitation exists and the admin has the link, so a mail problem is reported,
            # not fatal. Roll back only if the failure left the session unusable.
            if not db.is_active:
                db.rollback()
            logger.exception("Could not queue the invitation email for %s", email)
            email_queued = False

        return InvitationCreatedResponse(
            invitation=self.to_response(invitation, now), invite_link=link, email_queued=email_queued
        )

    def list_invitations(self, db: Session) -> List[InvitationResponse]:
        now = datetime.now(timezone.utc)
        return [self.to_response(i, now) for i in invitation_repository.list_recent(db)]

    def revoke(self, db: Session, invitation_id: str) -> Invitation:
        now = datetime.now(timezone.utc)
        invitation = invitation_repository.get_by_id(db, invitation_id)
        if invitation is None or self.status_of(invitation, now) != "PENDING":
            raise NotFoundError("No pending invitation with that id.")
        invitation.revoked_at = now
        db.commit()
        return invitation

    def lookup(self, db: Session, token: str) -> InvitationLookupResponse:
        """What the signup page shows for an invitation link. Needs the 256-bit token, so it
        reveals nothing to anyone who does not already hold the link."""
        now = datetime.now(timezone.utc)
        invitation = invitation_repository.get_usable(db, hash_token(token), now)
        if invitation is None:
            raise ValidationError(INVALID_INVITATION_MESSAGE)
        if user_repository.get_by_email(db, invitation.email):
            raise ConflictError("An account for this email already exists. Sign in instead.")
        return InvitationLookupResponse(
            email=invitation.email, role=invitation.role, full_name=invitation.full_name,
            expires_at=invitation.expires_at,
        )


invitation_service = InvitationService()
