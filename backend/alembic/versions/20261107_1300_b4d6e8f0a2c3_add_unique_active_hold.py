"""add_unique_active_hold

Revision ID: b4d6e8f0a2c3
Revises: a3c5d7e9f1b2
Create Date: 2026-11-07 13:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d6e8f0a2c3'
down_revision: Union[str, None] = 'a3c5d7e9f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Holds only live ~10 minutes, but a database that already has two active
    # holds on one slot would reject the index. Keep one per (doctor, start) and
    # deactivate the rest; the survivor is arbitrary, which is fine for rows
    # that expire within minutes anyway.
    op.get_bind().execute(
        sa.text(
            "UPDATE appointment_holds SET is_active = :inactive "
            "WHERE is_active = :active AND id NOT IN ("
            "  SELECT MIN(id) FROM appointment_holds WHERE is_active = :active "
            "  GROUP BY doctor_id, start_time)"
        ),
        {"inactive": False, "active": True},
    )
    op.create_index(
        'uq_active_hold_doctor_start_time',
        'appointment_holds',
        ['doctor_id', 'start_time'],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index('uq_active_hold_doctor_start_time', table_name='appointment_holds')
