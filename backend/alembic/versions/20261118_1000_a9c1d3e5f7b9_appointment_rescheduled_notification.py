"""appointment_rescheduled_notification

Revision ID: a9c1d3e5f7b9
Revises: f8b0c2d4e6a8
Create Date: 2026-11-18 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a9c1d3e5f7b9'
down_revision: Union[str, None] = 'f8b0c2d4e6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rescheduling now sends its own email (old and new time) instead of a booking
    # confirmation. SQLite stores enums as strings, so only PostgreSQL's native enum needs the
    # new value; run outside a transaction block so it works on every PostgreSQL version.
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'APPOINTMENT_RESCHEDULED'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum. APPOINTMENT_RESCHEDULED stays in
    # notificationtype after a downgrade, unused.
    pass
