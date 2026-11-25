"""departments

Revision ID: d4f6b8c0e2a4
Revises: c3e5a7b9d1f3
Create Date: 2026-11-25 09:00:00.000000+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4f6b8c0e2a4'
down_revision: Union[str, None] = 'c3e5a7b9d1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'departments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # Unique regardless of case: "Cardiology" and "cardiology" are the same department.
    op.create_index('uq_departments_name_lower', 'departments', [sa.text('lower(name)')], unique=True)
    # Optional for every doctor, so existing doctors keep working with no department. Batch mode
    # lets SQLite add a column with a foreign key; PostgreSQL gets a plain ALTER TABLE.
    with op.batch_alter_table('doctors') as batch:
        batch.add_column(sa.Column('department_id', sa.String(length=36), nullable=True))
        batch.create_foreign_key('fk_doctors_department_id', 'departments', ['department_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_doctors_department_id', ['department_id'])


def downgrade() -> None:
    with op.batch_alter_table('doctors') as batch:
        batch.drop_index('ix_doctors_department_id')
        batch.drop_constraint('fk_doctors_department_id', type_='foreignkey')
        batch.drop_column('department_id')
    op.drop_index('uq_departments_name_lower', table_name='departments')
    op.drop_table('departments')
