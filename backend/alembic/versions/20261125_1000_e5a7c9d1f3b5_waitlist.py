"""waitlist

Revision ID: e5a7c9d1f3b5
Revises: d4f6b8c0e2a4
Create Date: 2026-11-25 10:00:00.000000+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9d1f3b5'
down_revision: Union[str, None] = 'd4f6b8c0e2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'waitlist_entries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('doctor_id', sa.String(length=36), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['patient_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('patient_id', 'doctor_id', 'date', name='uq_waitlist_patient_doctor_date'),
    )
    op.create_index(op.f('ix_waitlist_entries_patient_id'), 'waitlist_entries', ['patient_id'])
    op.create_index('ix_waitlist_entries_doctor_date', 'waitlist_entries', ['doctor_id', 'date'])
    # The "a slot opened up" email. Only PostgreSQL has a native enum to extend, outside a
    # transaction block so it works on every PostgreSQL version.
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'WAITLIST_SLOT_OPEN'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; WAITLIST_SLOT_OPEN stays, unused.
    op.drop_index('ix_waitlist_entries_doctor_date', table_name='waitlist_entries')
    op.drop_index(op.f('ix_waitlist_entries_patient_id'), table_name='waitlist_entries')
    op.drop_table('waitlist_entries')
