"""timezones_login_throttle_token_version

Revision ID: c5e7f9a1b3d5
Revises: b4d6e8f0a2c3
Create Date: 2026-11-08 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e7f9a1b3d5'
down_revision: Union[str, None] = 'b4d6e8f0a2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-doctor timezone. Existing doctors default to UTC, which is how their
    # working hours and leave dates were always interpreted, so nothing shifts.
    op.add_column(
        'doctors',
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
    )

    # Token revocation: logout bumps this, and tokens carry the value they were
    # issued under. Existing tokens carry none and count as 0, so they stay valid.
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )

    # Failed-login counters, in the database so the limit holds across instances.
    op.create_table(
        'login_throttles',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('login_throttles')
    op.drop_column('users', 'token_version')
    op.drop_column('doctors', 'timezone')
