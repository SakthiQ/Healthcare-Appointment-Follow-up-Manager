import { FormEvent, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import type { WorkingHoursInput } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { DAY_NAMES, formatDate, todayInputValue } from '../../lib/format';
import {
  Badge,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  InfoBanner,
  Spinner,
  SuccessBanner,
} from '../../components/ui';

function blankWeek(): WorkingHoursInput[] {
  return DAY_NAMES.map((_, i) => ({
    day_of_week: i,
    start_time: '09:00:00',
    end_time: '17:00:00',
    is_active: false,
  }));
}

export default function DoctorConfig() {
  const { doctorId = '' } = useParams();

  const doctorQuery = useAsync(() => api.getDoctor(doctorId), [doctorId]);
  const scheduleQuery = useAsync(() => api.getDoctorSchedule(doctorId), [doctorId]);
  const leavesQuery = useAsync(() => api.getDoctorLeaves(doctorId), [doctorId]);

  // Profile form
  const [specialization, setSpecialization] = useState('');
  const [slotDuration, setSlotDuration] = useState(30);
  const [profileErrors, setProfileErrors] = useState<Record<string, string>>({});
  const [profileError, setProfileError] = useState<unknown>(null);
  const [savingProfile, setSavingProfile] = useState(false);

  // Schedule form
  const [week, setWeek] = useState<WorkingHoursInput[]>(blankWeek());
  const [scheduleErrors, setScheduleErrors] = useState<Record<number, string>>({});
  const [scheduleError, setScheduleError] = useState<unknown>(null);
  const [savingSchedule, setSavingSchedule] = useState(false);

  // Leave form
  const [leaveDate, setLeaveDate] = useState(todayInputValue());
  const [leaveReason, setLeaveReason] = useState('');
  const [leaveError, setLeaveError] = useState<unknown>(null);
  const [savingLeave, setSavingLeave] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (doctorQuery.data) {
      setSpecialization(doctorQuery.data.specialization);
      setSlotDuration(doctorQuery.data.slot_duration_minutes);
    }
  }, [doctorQuery.data]);

  useEffect(() => {
    if (scheduleQuery.data) {
      const next = blankWeek();
      for (const wh of scheduleQuery.data) {
        next[wh.day_of_week] = {
          day_of_week: wh.day_of_week,
          start_time: wh.start_time,
          end_time: wh.end_time,
          is_active: wh.is_active,
        };
      }
      setWeek(next);
    }
  }, [scheduleQuery.data]);

  async function handleSaveProfile(e: FormEvent) {
    e.preventDefault();
    setProfileError(null);
    setNotice(null);

    const errs: Record<string, string> = {};
    if (specialization.trim().length < 2) errs.specialization = 'Specialisation is required.';
    if (slotDuration < 5 || slotDuration > 240)
      errs.slotDuration = 'Slot duration must be between 5 and 240 minutes.';
    setProfileErrors(errs);
    if (Object.keys(errs).length) return;

    setSavingProfile(true);
    try {
      await api.updateDoctor(doctorId, {
        specialization: specialization.trim(),
        slot_duration_minutes: slotDuration,
      });
      setNotice('Profile updated.');
      doctorQuery.reload();
    } catch (err) {
      setProfileError(err);
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleToggleActive() {
    if (!doctorQuery.data) return;
    setProfileError(null);
    setNotice(null);
    setSavingProfile(true);
    try {
      await api.setDoctorStatus(doctorId, !doctorQuery.data.is_active);
      setNotice(
        doctorQuery.data.is_active
          ? 'Doctor deactivated — they no longer appear in patient search.'
          : 'Doctor activated.',
      );
      doctorQuery.reload();
    } catch (err) {
      setProfileError(err);
    } finally {
      setSavingProfile(false);
    }
  }

  function updateDay(index: number, patch: Partial<WorkingHoursInput>) {
    setWeek((w) => w.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  async function handleSaveSchedule(e: FormEvent) {
    e.preventDefault();
    setScheduleError(null);
    setNotice(null);

    const errs: Record<number, string> = {};
    for (const day of week) {
      if (!day.is_active) continue;
      if (day.end_time <= day.start_time)
        errs[day.day_of_week] = 'End time must be after start time.';
    }
    setScheduleErrors(errs);
    if (Object.keys(errs).length) return;

    setSavingSchedule(true);
    try {
      // Only active days are sent; the backend replaces the whole schedule.
      await api.configureWorkingHours(
        doctorId,
        week.filter((d) => d.is_active),
      );
      setNotice('Working hours saved.');
      scheduleQuery.reload();
    } catch (err) {
      setScheduleError(err);
    } finally {
      setSavingSchedule(false);
    }
  }

  async function handleAddLeave(e: FormEvent) {
    e.preventDefault();
    setLeaveError(null);
    setNotice(null);
    setSavingLeave(true);
    try {
      await api.createLeave(doctorId, {
        leave_date: leaveDate,
        reason: leaveReason.trim() || undefined,
      });
      setNotice(
        'Leave added. Any appointments on that date were marked conflicted and those patients notified.',
      );
      setLeaveReason('');
      leavesQuery.reload();
    } catch (err) {
      setLeaveError(err);
    } finally {
      setSavingLeave(false);
    }
  }

  async function handleDeleteLeave() {
    if (!deleteTarget) return;
    setLeaveError(null);
    setSavingLeave(true);
    try {
      await api.deleteLeave(doctorId, deleteTarget);
      setNotice('Leave removed.');
      leavesQuery.reload();
    } catch (err) {
      setLeaveError(err);
    } finally {
      setDeleteTarget(null);
      setSavingLeave(false);
    }
  }

  if (doctorQuery.loading) return <Spinner label="Loading doctor…" />;
  if (doctorQuery.error)
    return (
      <div className="page">
        <ErrorBanner error={doctorQuery.error} onRetry={doctorQuery.reload} />
        <Link className="btn" to="/admin/doctors">
          Back
        </Link>
      </div>
    );

  const doctor = doctorQuery.data;
  const leaves = leavesQuery.data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{doctor?.full_name}</h1>
          <p className="muted">{doctor?.email}</p>
        </div>
        <Link className="btn" to="/admin/doctors">
          Back
        </Link>
      </header>

      {notice ? <SuccessBanner>{notice}</SuccessBanner> : null}

      <Card
        title="Profile"
        actions={
          <Badge tone={doctor?.is_active ? 'ok' : 'muted'}>
            {doctor?.is_active ? 'Active' : 'Inactive'}
          </Badge>
        }
      >
        <ErrorBanner error={profileError} />
        <form onSubmit={handleSaveProfile} noValidate>
          <div className="form-grid">
            <Field label="Specialisation" htmlFor="specialization" error={profileErrors.specialization}>
              <input
                id="specialization"
                value={specialization}
                onChange={(e) => setSpecialization(e.target.value)}
                disabled={savingProfile}
              />
            </Field>
            <Field
              label="Slot duration (minutes)"
              htmlFor="slotDuration"
              error={profileErrors.slotDuration}
              hint="Between 5 and 240."
            >
              <input
                id="slotDuration"
                type="number"
                min={5}
                max={240}
                value={slotDuration}
                onChange={(e) => setSlotDuration(Number(e.target.value))}
                disabled={savingProfile}
              />
            </Field>
          </div>
          <div className="row-actions">
            <button type="submit" className="btn btn-primary" disabled={savingProfile}>
              {savingProfile ? 'Saving…' : 'Save profile'}
            </button>
            <button
              type="button"
              className={doctor?.is_active ? 'btn btn-danger' : 'btn'}
              onClick={handleToggleActive}
              disabled={savingProfile}
            >
              {doctor?.is_active ? 'Deactivate' : 'Activate'}
            </button>
          </div>
        </form>
      </Card>

      <Card title="Working hours">
        {scheduleQuery.loading ? <Spinner /> : null}
        <ErrorBanner error={scheduleError} />
        <p className="muted small">
          Tick the days this doctor works. Saving replaces the entire weekly schedule. Times are UTC.
        </p>
        <form onSubmit={handleSaveSchedule} noValidate>
          {week.map((day, i) => (
            <div key={day.day_of_week} className="day-row">
              <label className="day-toggle">
                <input
                  type="checkbox"
                  checked={day.is_active}
                  onChange={(e) => updateDay(i, { is_active: e.target.checked })}
                  disabled={savingSchedule}
                />
                <span>{DAY_NAMES[day.day_of_week]}</span>
              </label>
              <input
                type="time"
                value={day.start_time.slice(0, 5)}
                onChange={(e) => updateDay(i, { start_time: `${e.target.value}:00` })}
                disabled={!day.is_active || savingSchedule}
                aria-label={`${DAY_NAMES[day.day_of_week]} start time`}
              />
              <span className="muted">to</span>
              <input
                type="time"
                value={day.end_time.slice(0, 5)}
                onChange={(e) => updateDay(i, { end_time: `${e.target.value}:00` })}
                disabled={!day.is_active || savingSchedule}
                aria-label={`${DAY_NAMES[day.day_of_week]} end time`}
              />
              {scheduleErrors[day.day_of_week] ? (
                <small className="field-error" role="alert">
                  {scheduleErrors[day.day_of_week]}
                </small>
              ) : null}
            </div>
          ))}
          <button type="submit" className="btn btn-primary" disabled={savingSchedule}>
            {savingSchedule ? 'Saving…' : 'Save working hours'}
          </button>
        </form>
      </Card>

      <Card title="Leave">
        <ErrorBanner error={leaveError} />
        <InfoBanner>
          Marking a date as leave immediately flags any existing appointments that day as conflicted and
          queues notifications to those patients.
        </InfoBanner>

        <form onSubmit={handleAddLeave} noValidate>
          <div className="form-grid">
            <Field label="Leave date" htmlFor="leaveDate">
              <input
                id="leaveDate"
                type="date"
                value={leaveDate}
                onChange={(e) => setLeaveDate(e.target.value)}
                disabled={savingLeave}
              />
            </Field>
            <Field label="Reason (optional)" htmlFor="leaveReason">
              <input
                id="leaveReason"
                value={leaveReason}
                onChange={(e) => setLeaveReason(e.target.value)}
                disabled={savingLeave}
                placeholder="e.g. Conference"
              />
            </Field>
          </div>
          <button type="submit" className="btn btn-primary" disabled={savingLeave}>
            {savingLeave ? 'Saving…' : 'Add leave date'}
          </button>
        </form>

        <h3>Scheduled leave</h3>
        {leavesQuery.loading ? <Spinner /> : null}
        <ErrorBanner error={leavesQuery.error} onRetry={leavesQuery.reload} />
        {!leavesQuery.loading && leaves.length === 0 ? (
          <EmptyState>No leave dates recorded.</EmptyState>
        ) : null}
        {leaves.length > 0 ? (
          <ul className="list">
            {leaves.map((leave) => (
              <li key={leave.id} className="list-row">
                <div>
                  <strong>{formatDate(`${leave.leave_date}T00:00:00Z`)}</strong>
                  {leave.reason ? <div className="muted small">{leave.reason}</div> : null}
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => setDeleteTarget(leave.id)}
                  disabled={savingLeave}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Remove this leave date?"
        message={
          <p>
            The doctor's slots become bookable again for that date. Appointments already marked
            conflicted stay conflicted — they are not automatically restored.
          </p>
        }
        confirmLabel="Remove leave"
        busy={savingLeave}
        onConfirm={handleDeleteLeave}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
