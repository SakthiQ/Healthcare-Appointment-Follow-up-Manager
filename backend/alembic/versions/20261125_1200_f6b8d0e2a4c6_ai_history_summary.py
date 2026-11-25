"""ai_history_summary

Revision ID: f6b8d0e2a4c6
Revises: e5a7c9d1f3b5
Create Date: 2026-11-25 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f6b8d0e2a4c6'
down_revision: Union[str, None] = 'e5a7c9d1f3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The AI history summary (#73) is a new AISummaryType. SQLite stores enums as strings, so only
    # PostgreSQL's native enum needs the value; run outside a transaction block so it works on
    # every PostgreSQL version.
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE aisummarytype ADD VALUE IF NOT EXISTS 'HISTORY'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum. HISTORY stays in aisummarytype after a
    # downgrade, unused.
    pass
