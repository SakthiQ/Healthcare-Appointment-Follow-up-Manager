"""staff_invitations

Revision ID: e7a9b1c3d5f7
Revises: d6f8a0b2c4e6
Create Date: 2026-11-08 16:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a9b1c3d5f7'
down_revision: Union[str, None] = 'd6f8a0b2c4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New notification type for the invitation email. SQLite stores enums as strings, so only
    # PostgreSQL's native enum needs it; run outside a transaction block so it works on every
    # PostgreSQL version.
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'INVITATION'")

    # An invitee has no account yet, so a notification job may be addressed to an email
    # address instead of a user. The CHECK keeps the old guarantee that a job always has a
    # recipient. batch_alter_table runs plain ALTERs on PostgreSQL and rebuilds the table on
    # SQLite, which cannot alter a column in place.
    with op.batch_alter_table('notification_jobs') as batch:
        batch.alter_column('recipient_id', existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column('recipient_email', sa.String(length=255), nullable=True))
        batch.create_check_constraint(
            'ck_notification_has_recipient', 'recipient_id IS NOT NULL OR recipient_email IS NOT NULL'
        )

    op.create_table(
        'invitations',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('specialization', sa.String(length=255), nullable=True),
        sa.Column('slot_duration_minutes', sa.Integer(), nullable=True),
        sa.Column('timezone', sa.String(length=64), nullable=True),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('invited_by', sa.String(length=36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_invitations_email', 'invitations', ['email'])
    op.create_index('ix_invitations_token_hash', 'invitations', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_table('invitations')
    # Invitation emails have no user to point at, so they cannot survive the column going back
    # to NOT NULL.
    op.execute("DELETE FROM notification_jobs WHERE recipient_id IS NULL")
    with op.batch_alter_table('notification_jobs') as batch:
        batch.drop_constraint('ck_notification_has_recipient', type_='check')
        batch.drop_column('recipient_email')
        batch.alter_column('recipient_id', existing_type=sa.String(length=36), nullable=False)
    # PostgreSQL cannot drop a value from an enum type, so INVITATION stays in notificationtype
    # after a downgrade. It is unused.
