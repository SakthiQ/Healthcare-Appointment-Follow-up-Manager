from datetime import date, datetime, timedelta, timezone
from typing import List
from sqlalchemy.orm import Session
from app.exceptions import NotFoundError
from repositories.doctor_repository import doctor_repository
from repositories.hold_repository import hold_repository
from schemas.slot import SlotItem, SlotGenerationResponse


from app.core.datetime_utils import ensure_utc, get_zone, local_day_bounds_utc, local_to_utc


class SlotService:
    """Working hours and leave dates are wall-clock values in the DOCTOR's timezone
    (Doctor.timezone); slots, holds and appointments are absolute instants stored in
    UTC. Every conversion between the two goes through the doctor's zone here."""

    def generate_slots(
        self, db: Session, doctor_id: str, target_date: date
    ) -> SlotGenerationResponse:
        # 1. Retrieve Doctor
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        duration = doctor.slot_duration_minutes
        zone = get_zone(doctor.timezone)

        def empty() -> SlotGenerationResponse:
            return SlotGenerationResponse(
                doctor_id=doctor_id,
                target_date=target_date,
                slot_duration_minutes=duration,
                timezone=str(zone),
                total_slots=0,
                available_slots=0,
                slots=[]
            )

        if not doctor.is_active:
            return empty()

        # 2. Check Doctor Leave (target_date is the doctor's local calendar date)
        if doctor_repository.get_leave_by_date(db, doctor_id, target_date):
            return empty()

        # 3. Get Working Hours for day_of_week (0=Monday, 6=Sunday)
        day_of_week = target_date.weekday()
        all_hours = doctor_repository.get_working_hours(db, doctor_id)
        day_hours = [h for h in all_hours if h.day_of_week == day_of_week and h.is_active]

        if not day_hours:
            return empty()

        # 4. Generate candidate time intervals
        day_start, day_end = local_day_bounds_utc(target_date, zone)

        # Fetch active holds and active appointments for doctor on target date
        active_holds = hold_repository.get_active_holds_for_doctor_date(db, doctor_id, day_start, day_end)
        active_appts = hold_repository.get_active_appointments_for_doctor_date(db, doctor_id, day_start, day_end)

        occupied_intervals = []
        for h in active_holds:
            occupied_intervals.append((ensure_utc(h.start_time), ensure_utc(h.end_time)))
        for a in active_appts:
            occupied_intervals.append((ensure_utc(a.start_time), ensure_utc(a.end_time)))

        candidate_slots: List[SlotItem] = []
        for wh in day_hours:
            # Converted to UTC before stepping, so each slot is exactly `duration`
            # minutes long even across a daylight-saving change.
            curr_start = local_to_utc(target_date, wh.start_time, zone)
            wh_end = local_to_utc(target_date, wh.end_time, zone)

            while curr_start + timedelta(minutes=duration) <= wh_end:
                curr_end = curr_start + timedelta(minutes=duration)

                # Check overlap with holds or appointments
                is_avail = True
                for occ_start, occ_end in occupied_intervals:
                    # Overlap if max(start1, start2) < min(end1, end2)
                    if max(curr_start, occ_start) < min(curr_end, occ_end):
                        is_avail = False
                        break

                candidate_slots.append(SlotItem(
                    start_time=curr_start,
                    end_time=curr_end,
                    is_available=is_avail
                ))
                curr_start = curr_end

        available_count = sum(1 for s in candidate_slots if s.is_available)
        return SlotGenerationResponse(
            doctor_id=doctor_id,
            target_date=target_date,
            slot_duration_minutes=duration,
            timezone=str(zone),
            total_slots=len(candidate_slots),
            available_slots=available_count,
            slots=candidate_slots
        )

    def validate_slot_boundary(
        self, db: Session, doctor_id: str, start_time: datetime, end_time: datetime
    ) -> bool:
        """Verify slot falls strictly within active working hours, matches duration, and is not a leave date."""
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor or not doctor.is_active:
            return False

        zone = get_zone(doctor.timezone)
        start_time = ensure_utc(start_time)
        end_time = ensure_utc(end_time)

        # Which day it is, and which working hours apply, is decided in the doctor's zone.
        target_date = start_time.astimezone(zone).date()
        if doctor_repository.get_leave_by_date(db, doctor_id, target_date):
            return False

        # Validate slot duration
        expected_end = start_time + timedelta(minutes=doctor.slot_duration_minutes)
        if end_time != expected_end:
            return False

        # Check working hours
        day_of_week = target_date.weekday()
        all_hours = doctor_repository.get_working_hours(db, doctor_id)
        day_hours = [h for h in all_hours if h.day_of_week == day_of_week and h.is_active]

        for wh in day_hours:
            wh_start = local_to_utc(target_date, wh.start_time, zone)
            wh_end = local_to_utc(target_date, wh.end_time, zone)
            if start_time >= wh_start and end_time <= wh_end:
                return True

        return False



slot_service = SlotService()
