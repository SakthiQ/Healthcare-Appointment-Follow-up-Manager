from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from models.invitation import Invitation


class InvitationRepository:
    def create(self, db: Session, **fields) -> Invitation:
        invitation = Invitation(**fields)
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        return invitation

    def get_by_id(self, db: Session, invitation_id: str) -> Optional[Invitation]:
        return db.query(Invitation).filter(Invitation.id == invitation_id).first()

    def get_usable(
        self, db: Session, token_hash: str, now: datetime, for_update: bool = False
    ) -> Optional[Invitation]:
        """The invitation if it exists and is still pending: unused, unrevoked, unexpired."""
        query = db.query(Invitation).filter(
            Invitation.token_hash == token_hash,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
        )
        if for_update and db.bind and db.bind.dialect.name != "sqlite":
            # Locked, so two people presenting the same link cannot both create an account.
            query = query.with_for_update()
        return query.first()

    def list_recent(self, db: Session, limit: int = 200) -> List[Invitation]:
        return db.query(Invitation).order_by(Invitation.created_at.desc()).limit(limit).all()

    def revoke_pending_for_email(self, db: Session, email: str, now: datetime) -> int:
        """Retire every still-pending invitation to this address (a fresh one replaces them).
        Leaves the commit to the caller so it lands together with the new invitation."""
        return db.query(Invitation).filter(
            Invitation.email == email,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
        ).update({"revoked_at": now}, synchronize_session=False)

    def purge_stale(self, db: Session, cutoff: datetime) -> int:
        """Delete invitations nobody accepted that expired before `cutoff`. Accepted and revoked
        ones are kept as a record of who was invited."""
        deleted = db.query(Invitation).filter(
            Invitation.used_at.is_(None), Invitation.expires_at < cutoff
        ).delete(synchronize_session=False)
        db.commit()
        return deleted


invitation_repository = InvitationRepository()
