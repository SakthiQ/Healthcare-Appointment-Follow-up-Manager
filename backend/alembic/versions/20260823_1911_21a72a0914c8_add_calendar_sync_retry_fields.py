"""add_calendar_sync_retry_fields

Revision ID: 21a72a0914c8
Revises: 'f39781a8abe6'
Create Date: 2026-08-23 19:11:18.927288+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21a72a0914c8'
down_revision: Union[str, None] = 'f39781a8abe6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase 10: calendar sync needs a pending-operation marker, bounded-retry
    # bookkeeping, and a stable idempotency key so a retried create cannot
    # produce a duplicate external event.
    #
    # Unlike every other enum in this project, `calendaroperation` is added to
    # an already-existing table (add_column) rather than declared inline in a
    # create_table() call. SQLAlchemy only auto-emits CREATE TYPE as part of
    # compiling a CREATE TABLE statement — a standalone add_column() does not,
    # so on PostgreSQL the type must be created explicitly first. `.create()`
    # is a no-op on SQLite (which has no native enum type), so this stays
    # dialect-safe and doesn't affect the SQLite-backed test suite.
    calendar_operation_enum = sa.Enum('NONE', 'CREATE', 'UPDATE', 'DELETE', name='calendaroperation')
    calendar_operation_enum.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('calendar_events') as batch_op:
        batch_op.add_column(sa.Column(
            'pending_operation',
            calendar_operation_enum,
            nullable=False,
            server_default='CREATE',
        ))
        batch_op.add_column(sa.Column(
            'idempotency_key', sa.String(length=255), nullable=False, server_default=''
        ))
        batch_op.add_column(sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_error', sa.Text(), nullable=True))
        # One calendar event row per appointment per side — the DB-level guard
        # against duplicate event rows on repeated syncs.
        batch_op.create_unique_constraint(
            'uq_calendar_event_appointment_recipient', ['appointment_id', 'recipient_type']
        )

    op.create_index(
        op.f('ix_calendar_events_pending_operation'), 'calendar_events', ['pending_operation'], unique=False
    )
    op.create_index(
        op.f('ix_calendar_events_next_retry_at'), 'calendar_events', ['next_retry_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_calendar_events_next_retry_at'), table_name='calendar_events')
    op.drop_index(op.f('ix_calendar_events_pending_operation'), table_name='calendar_events')
    with op.batch_alter_table('calendar_events') as batch_op:
        batch_op.drop_constraint('uq_calendar_event_appointment_recipient', type_='unique')
        batch_op.drop_column('last_error')
        batch_op.drop_column('next_retry_at')
        batch_op.drop_column('attempts')
        batch_op.drop_column('idempotency_key')
        batch_op.drop_column('pending_operation')

    sa.Enum(name='calendaroperation').drop(op.get_bind(), checkfirst=True)
