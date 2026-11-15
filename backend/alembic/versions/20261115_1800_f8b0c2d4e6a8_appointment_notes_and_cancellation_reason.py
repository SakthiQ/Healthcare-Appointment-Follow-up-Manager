"""appointment_notes_and_cancellation_reason

Revision ID: f8b0c2d4e6a8
Revises: e7a9b1c3d5f7
Create Date: 2026-11-15 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8b0c2d4e6a8'
down_revision: Union[str, None] = 'e7a9b1c3d5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The booking request has always accepted `notes` and the cancel request a
    # `cancellation_reason`, but neither was stored. Both are optional, so existing rows
    # simply have none; adding nullable columns works in place on SQLite and PostgreSQL.
    op.add_column('appointments', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('appointments', sa.Column('cancellation_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite cannot drop a column in place; batch mode rebuilds the table there.
    with op.batch_alter_table('appointments') as batch:
        batch.drop_column('cancellation_reason')
        batch.drop_column('notes')
