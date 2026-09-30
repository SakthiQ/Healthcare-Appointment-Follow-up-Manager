import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, nullIfNotFound } from '../../api/client';
import type { PostVisitPayload, PreVisitPayload, SlotItem } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { useNow } from '../../lib/useNow';
import { bookableSlots, formatDateTime, formatTime, todayInputValue, urgencyTone } from '../../lib/format';
import {
  Badge,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  InfoBanner,
  Spinner,
  StatusBadge,
  SuccessBanner,
} from '../../components/ui';

const RESCHEDULABLE = new Set(['CONFIRMED', 'RESCHEDULED', 'CONFLICTED']);
const CANCELLABLE = new Set(['CONFIRMED', 'RESCHEDULED', 'CONFLICTED', 'HELD']);
const SUMMARY_EDITABLE = new Set(['CONFIRMED', 'RESCHEDULED']);

export default function PatientAppointmentDetail() {
  const { appointmentId = '' } = useParams();

  const apptQuery = useAsync(() => api.getAppointment(appointmentId), [appointmentId]);
  const preVisitQuery = useAsync(
    () => nullIfNotFound(api.getPreVisitSummary(appointmentId)),
    [appointmentId],
  );
  const postVisitQuery = useAsync(
    () => nullIfNotFound(api.getPostVisitSummary(appointmentId)),
    [appointmentId],
  );

  const [showReschedule, setShowReschedule] = useState(false);
  const [date, setDate] = useState(todayInputValue());
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const [symptoms, setSymptoms] = useState('');
  const [symptomError, setSymptomError] = useState<string | undefined>();
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<unknown>(null);

  const now = useNow();

  const appt = apptQuery.data;
  const doctorProfileId = appt?.doctor_profile_id ?? '';

  const slotsQuery = useAsync(
    () =>
      showReschedule && doctorProfileId
        ? api.getSlots(doctorProfileId, date)
        : Promise.resolve(null),
    [showReschedule, doctorProfileId, date],
  );

  async function handleReschedule(slot: SlotItem) {
    setActionError(null);
    setBusy(true);
    try {
      await api.rescheduleAppointment(appointmentId, {
        new_start_time: slot.start_time,
        new_end_time: slot.end_time,
      });
      setNotice('Your appointment has been rescheduled.');
      setShowReschedule(false);
      apptQuery.reload();
    } catch (err) {
      setActionError(err);
      slotsQuery.reload();
    } finally {
      setBusy(false);
    }
  }

  async function handleGeneratePreVisit() {
    if (symptoms.trim().length < 3) {
      setSymptomError('Please describe your symptoms (at least 3 characters).');
      return;
    }
    setSymptomError(undefined);
    setGenerateError(null);
    setGenerating(true);
    try {
      await api.submitSymptomReport(appointmentId, symptoms.trim());
      await api.generatePreVisitSummary(appointmentId);
      preVisitQuery.reload();
    } catch (err) {
      setGenerateError(err);
    } finally {
      setGenerating(false);
    }
  }

  async function handleCancel() {
    setActionError(null);
    setBusy(true);
    try {
      await api.cancelAppointment(appointmentId);
      setNotice('Your appointment has been cancelled.');
      setConfirmCancel(false);
      apptQuery.reload();
    } catch (err) {
      setActionError(err);
      setConfirmCancel(false);
    } finally {
      setBusy(false);
    }
  }

  // Only block the page on the first load; reloads after an action keep it on screen.
  if (apptQuery.loading && !apptQuery.data) return <Spinner label="Loading appointment…" />;
  if (apptQuery.error)
    return (
      <div className="page">
        <ErrorBanner error={apptQuery.error} onRetry={apptQuery.reload} />
        <Link className="btn" to="/patient/appointments">
          Back to appointments
        </Link>
      </div>
    );
  if (!appt) return null;

  const preVisit = preVisitQuery.data;
  const postVisit = postVisitQuery.data;
  const preVisitPayload = preVisit?.status === 'SUCCESS' ? (preVisit.payload as PreVisitPayload) : null;
  const postVisitPayload =
    postVisit?.status === 'SUCCESS' ? (postVisit.payload as PostVisitPayload) : null;

  const availableSlots = bookableSlots(slotsQuery.data?.slots ?? [], now);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Appointment details</h1>
          <p className="muted">{formatDateTime(appt.start_time)}</p>
        </div>
        <Link className="btn" to="/patient/appointments">
          Back
        </Link>
      </header>

      {notice ? <SuccessBanner>{notice}</SuccessBanner> : null}
      <ErrorBanner error={actionError} />

      {appt.status === 'CONFLICTED' ? (
        <div className="banner banner-danger" role="alert">
          <div>
            <strong>Your doctor is unavailable for this date</strong>
            <div>This appointment can no longer go ahead. Please pick a new slot below.</div>
          </div>
        </div>
      ) : null}

      <Card title="Summary">
        <div className="summary-row">
          <span>Doctor</span>
          <strong>
            {appt.doctor_name ?? 'Unknown doctor'}
            {appt.doctor_specialization ? ` · ${appt.doctor_specialization}` : ''}
          </strong>
        </div>
        <div className="summary-row">
          <span>Status</span>
          <StatusBadge status={appt.status} />
        </div>
        <div className="summary-row">
          <span>Starts</span>
          <strong>{formatDateTime(appt.start_time)}</strong>
        </div>
        <div className="summary-row">
          <span>Ends</span>
          <strong>{formatDateTime(appt.end_time)}</strong>
        </div>
        <div className="summary-row">
          <span>Booked</span>
          <span>{formatDateTime(appt.created_at)}</span>
        </div>

        <div className="row-actions">
          {RESCHEDULABLE.has(appt.status) ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setShowReschedule((v) => !v)}
            >
              {showReschedule ? 'Cancel rescheduling' : 'Reschedule'}
            </button>
          ) : null}
          {CANCELLABLE.has(appt.status) ? (
            <button type="button" className="btn btn-danger" onClick={() => setConfirmCancel(true)}>
              Cancel appointment
            </button>
          ) : null}
        </div>
      </Card>

      {showReschedule ? (
        <Card title="Pick a new slot">
          {!doctorProfileId ? (
            <InfoBanner>
              This appointment isn't linked to a doctor profile, so new slots can't be listed.
            </InfoBanner>
          ) : (
            <>
              <Field label="Date" htmlFor="reschedule-date">
                <input
                  id="reschedule-date"
                  type="date"
                  value={date}
                  min={todayInputValue()}
                  onChange={(e) => setDate(e.target.value)}
                />
              </Field>

              {slotsQuery.loading ? <Spinner label="Checking availability…" /> : null}
              <ErrorBanner error={slotsQuery.error} onRetry={slotsQuery.reload} />

              {!slotsQuery.loading && !slotsQuery.error ? (
                availableSlots.length === 0 ? (
                  <EmptyState>No slots available on this date. Try another.</EmptyState>
                ) : (
                  <div className="slot-grid">
                    {availableSlots.map((slot) => (
                      <button
                        key={slot.start_time}
                        type="button"
                        className="slot"
                        disabled={busy}
                        onClick={() => handleReschedule(slot)}
                      >
                        {formatTime(slot.start_time)}
                        <span className="slot-end">–{formatTime(slot.end_time)}</span>
                      </button>
                    ))}
                  </div>
                )
              ) : null}
              {busy ? <Spinner label="Rescheduling…" /> : null}
            </>
          )}
        </Card>
      ) : null}

      <Card title="Pre-visit summary">
        {preVisitQuery.loading ? <Spinner /> : null}
        <ErrorBanner error={preVisitQuery.error} onRetry={preVisitQuery.reload} />
        {!preVisitQuery.loading && preVisitPayload ? (
          <>
            <div className="summary-row">
              <span>Urgency</span>
              <Badge tone={urgencyTone(preVisitPayload.urgency)}>{preVisitPayload.urgency}</Badge>
            </div>
            <div className="summary-row">
              <span>Chief complaint</span>
              <strong>{preVisitPayload.chief_complaint}</strong>
            </div>
            <span className="muted small">Questions to ask your doctor</span>
            <ol className="numbered">
              {preVisitPayload.suggested_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
          </>
        ) : null}
        {!preVisitQuery.loading && !preVisitQuery.error && !preVisitPayload ? (
          <EmptyState>
            {preVisit?.status === 'FAILED'
              ? `The summary could not be generated${preVisit.error_message ? `: ${preVisit.error_message}` : '.'}`
              : 'No pre-visit summary has been generated for this appointment.'}
          </EmptyState>
        ) : null}
        {!preVisitQuery.loading && !preVisitQuery.error && !preVisitPayload && SUMMARY_EDITABLE.has(appt.status) ? (
          <>
            <ErrorBanner error={generateError} />
            <Field
              label="Symptoms"
              htmlFor="symptoms"
              error={symptomError}
              hint="What's bothering you, when it started, and how it's changed."
            >
              <textarea
                id="symptoms"
                rows={5}
                value={symptoms}
                onChange={(e) => setSymptoms(e.target.value)}
                disabled={generating}
              />
            </Field>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleGeneratePreVisit}
              disabled={generating}
            >
              {generating ? 'Generating summary…' : 'Generate pre-visit summary'}
            </button>
          </>
        ) : null}
      </Card>

      <Card title="After your visit">
        {postVisitQuery.loading ? <Spinner /> : null}
        <ErrorBanner error={postVisitQuery.error} onRetry={postVisitQuery.reload} />
        {!postVisitQuery.loading && postVisitPayload ? (
          <>
            <h3>Summary</h3>
            <p>{postVisitPayload.summary}</p>
            <h3>Medication schedule</h3>
            <p>{postVisitPayload.medication_schedule}</p>
            <h3>Follow-up steps</h3>
            <p>{postVisitPayload.follow_up_steps}</p>
          </>
        ) : null}
        {!postVisitQuery.loading && !postVisitQuery.error && !postVisitPayload ? (
          <EmptyState>
            Your doctor hasn't published a post-visit summary yet. It will appear here after your
            consultation.
          </EmptyState>
        ) : null}
      </Card>

      <ConfirmDialog
        open={confirmCancel}
        title="Cancel this appointment?"
        message={
          <>
            <p>
              This will release the slot on {formatDateTime(appt.start_time)} and notify your doctor.
            </p>
            <p className="muted small">This cannot be undone — you'd need to book again.</p>
          </>
        }
        confirmLabel="Yes, cancel it"
        busy={busy}
        onConfirm={handleCancel}
        onCancel={() => setConfirmCancel(false)}
      />
    </div>
  );
}
