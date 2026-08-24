"""add_double_booking_unique_constraint

Revision ID: f39781a8abe6
Revises: 'bcd7ea881066'
Create Date: 2026-08-23 09:06:21.462111+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f39781a8abe6'
down_revision: Union[str, None] = 'bcd7ea881066'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Database-level double-booking guard: at most one active (HELD /
    # CONFIRMED / RESCHEDULED) appointment may exist for a given doctor
    # profile and start_time. This is the final authority against
    # double-booking, independent of any application-level locking.
    op.create_index(
        'uq_doctor_profile_start_time_active',
        'appointments',
        ['doctor_profile_id', 'start_time'],
        unique=True,
        postgresql_where=sa.text("status IN ('HELD', 'CONFIRMED', 'RESCHEDULED')"),
        sqlite_where=sa.text("status IN ('HELD', 'CONFIRMED', 'RESCHEDULED')"),
    )


def downgrade() -> None:
    op.drop_index('uq_doctor_profile_start_time_active', table_name='appointments')
