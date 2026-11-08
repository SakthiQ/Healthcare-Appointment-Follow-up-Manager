"""add_no_overlap_guard

Revision ID: a3c5d7e9f1b2
Revises: 21a72a0914c8
Create Date: 2026-11-07 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3c5d7e9f1b2'
down_revision: Union[str, None] = '21a72a0914c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE = "status IN ('HELD', 'CONFIRMED', 'RESCHEDULED')"
OVERLAP_ERROR = "appointment overlaps an existing active appointment"

TRIGGERS = {
    "trg_appointments_no_active_overlap_insert": f"""
CREATE TRIGGER trg_appointments_no_active_overlap_insert
BEFORE INSERT ON appointments
WHEN NEW.doctor_profile_id IS NOT NULL AND NEW.{ACTIVE}
BEGIN
    SELECT RAISE(ABORT, '{OVERLAP_ERROR}')
    WHERE EXISTS (
        SELECT 1 FROM appointments a
        WHERE a.doctor_profile_id = NEW.doctor_profile_id
          AND a.id != NEW.id
          AND a.{ACTIVE}
          AND a.start_time < NEW.end_time
          AND a.end_time > NEW.start_time
    );
END""",
    "trg_appointments_no_active_overlap_update": f"""
CREATE TRIGGER trg_appointments_no_active_overlap_update
BEFORE UPDATE OF doctor_profile_id, start_time, end_time, status ON appointments
WHEN NEW.doctor_profile_id IS NOT NULL AND NEW.{ACTIVE}
BEGIN
    SELECT RAISE(ABORT, '{OVERLAP_ERROR}')
    WHERE EXISTS (
        SELECT 1 FROM appointments a
        WHERE a.doctor_profile_id = NEW.doctor_profile_id
          AND a.id != NEW.id
          AND a.{ACTIVE}
          AND a.start_time < NEW.end_time
          AND a.end_time > NEW.start_time
    );
END""",
}


def upgrade() -> None:
    # The unique index from f39781a8abe6 only rejects identical start times.
    # This adds the real invariant at the database level: no two active
    # appointments for one doctor may overlap. It fails to apply if existing
    # data already contains overlapping active appointments for a doctor —
    # resolve those first (cancel or move one of each pair).
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        # btree_gist lets the exclusion constraint combine "=" on the doctor
        # with "&&" on the time range. Needs a role allowed to create it;
        # Neon, Supabase and Render Postgres all permit this extension.
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute(
            "ALTER TABLE appointments ADD CONSTRAINT ex_doctor_profile_no_overlap_active "
            "EXCLUDE USING gist (doctor_profile_id WITH =, tstzrange(start_time, end_time) WITH &&) "
            f"WHERE ({ACTIVE})"
        )
    elif dialect == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ex_doctor_profile_no_overlap_active")
    elif dialect == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
