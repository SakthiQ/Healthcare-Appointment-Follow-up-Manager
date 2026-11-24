"""appointment_no_show_status

Revision ID: b2d4f6a8c0e2
Revises: a9c1d3e5f7b9
Create Date: 2026-11-24 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e2'
down_revision: Union[str, None] = 'a9c1d3e5f7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Doctors can now record that a patient did not attend. SQLite stores enums as strings, so
    # only PostgreSQL's native enum needs the new value; run outside a transaction block so it
    # works on every PostgreSQL version. NO_SHOW is not in the active-status list of the
    # double-booking index or the overlap constraint, so neither needs to change.
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE appointmentstatus ADD VALUE IF NOT EXISTS 'NO_SHOW'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum. NO_SHOW stays in appointmentstatus after a
    # downgrade, unused.
    pass
