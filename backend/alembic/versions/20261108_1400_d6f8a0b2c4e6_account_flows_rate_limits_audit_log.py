"""account_flows_rate_limits_audit_log

Revision ID: d6f8a0b2c4e6
Revises: c5e7f9a1b3d5
Create Date: 2026-11-08 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6f8a0b2c4e6'
down_revision: Union[str, None] = 'c5e7f9a1b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Email verification. Users that already exist are treated as verified (they could
    # not have been asked to verify), so turning REQUIRE_EMAIL_VERIFICATION on later
    # does not lock them out; the application sets False explicitly for new sign-ups.
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # New notification types for the password-reset and verification emails.
    # SQLite stores enums as plain strings, so only PostgreSQL's native enum needs it.
    # ALTER TYPE ... ADD VALUE is run outside a transaction block so it works on every
    # PostgreSQL version.
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'PASSWORD_RESET'")
            op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'EMAIL_VERIFICATION'")

    op.create_table(
        'rate_limits',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'auth_tokens',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_auth_tokens_user_id', 'auth_tokens', ['user_id'])
    op.create_index('ix_auth_tokens_token_hash', 'auth_tokens', ['token_hash'], unique=True)

    # Append-only audit trail. No foreign keys on purpose: entries must outlive the
    # users and appointments they mention.
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor_user_id', sa.String(length=36), nullable=True),
        sa.Column('actor_role', sa.String(length=16), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('resource_type', sa.String(length=32), nullable=True),
        sa.Column('resource_id', sa.String(length=36), nullable=True),
        sa.Column('patient_id', sa.String(length=36), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
    )
    op.create_index('ix_audit_logs_occurred_at', 'audit_logs', ['occurred_at'])
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_resource_id', 'audit_logs', ['resource_id'])
    op.create_index('ix_audit_logs_patient_id', 'audit_logs', ['patient_id'])


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('auth_tokens')
    op.drop_table('rate_limits')
    op.drop_column('users', 'email_verified')
    # PostgreSQL cannot drop a value from an enum type, so PASSWORD_RESET and
    # EMAIL_VERIFICATION stay in notificationtype after a downgrade. They are unused.
