from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from models.security import AuthToken, AuthTokenPurpose


class AuthTokenRepository:
    def create(
        self, db: Session, user_id: str, purpose: AuthTokenPurpose, token_hash: str, expires_at: datetime
    ) -> AuthToken:
        token = AuthToken(user_id=user_id, purpose=purpose.value, token_hash=token_hash, expires_at=expires_at)
        db.add(token)
        db.commit()
        db.refresh(token)
        return token

    def get_usable(
        self, db: Session, purpose: AuthTokenPurpose, token_hash: str, now: datetime, for_update: bool = False
    ) -> Optional[AuthToken]:
        """The token if it exists for this purpose, is unused and has not expired."""
        query = db.query(AuthToken).filter(
            AuthToken.token_hash == token_hash,
            AuthToken.purpose == purpose.value,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        if for_update and db.bind and db.bind.dialect.name != "sqlite":
            # Locked, so two requests presenting the same link cannot both succeed.
            query = query.with_for_update()
        return query.first()

    def invalidate_unused(self, db: Session, user_id: str, purpose: AuthTokenPurpose, now: datetime) -> None:
        """Retire every outstanding token of this kind for the user (a fresh link replaces older ones)."""
        db.query(AuthToken).filter(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose.value,
            AuthToken.used_at.is_(None),
        ).update({"used_at": now}, synchronize_session=False)

    def purge_expired(self, db: Session, cutoff: datetime) -> int:
        deleted = db.query(AuthToken).filter(AuthToken.expires_at < cutoff).delete(synchronize_session=False)
        db.commit()
        return deleted


auth_token_repository = AuthTokenRepository()
