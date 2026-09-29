import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, nullIfNotFound } from '../../api/client';
import type { MedicationItem, PostVisitPayload, PreVisitPayload } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { formatDateTime, urgencyTone } from '../../lib/format';
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  InfoBanner,
  Spinner,
  StatusBadge,
  SuccessBanner,
} from '../../components/ui';

// Mirrors the backend: consultations are only accepted for appointments that
// are going ahead or have taken place.
const CONSULTABLE = new Set(['CONFIRMED', 'RESCHEDULED', 'COMPLETED']);

const EMPTY_MED: MedicationItem = { name: '', dosage: '', frequency: '', duration_days: null };

export default function DoctorAppointmentDetail() {
  const { appointmentId = '' } = useParams();

  const apptQuery = useAsync(() => api.getAppointment(appointmentId), [appointmentId]);
  const preVisitQuery = useAsync(
    () => nullIfNotFound(api.getPreVisitSummary(appointmentId)),
    [appointmentId],
  );
  const consultationQuery = useAsync(
    () => nullIfNotFound(api.getConsultation(appointmentId)),
    [appointmentId],
  );
  const postVisitQuery = useAsync(
    () => nullIfNotFound(api.getPostVisitSummary(appointmentId)),
    [appointmentId],
  );

  const [notes, setNotes] = useState('');
  const [instructions, setInstructions] = useState('');
  const [medications, setMedications] = useState<MedicationItem[]>([{ ...EMPTY_MED }]);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<unknown>(null);

  function updateMedication(index: number, patch: Partial<MedicationItem>) {
    setMedications((meds) => meds.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  }

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (notes.trim().length < 1) errs.notes = 'Consultation notes are required.';

    medications.forEach((med, i) => {
      const anyFilled = med.name.trim() || med.dosage.trim() || med.frequency.trim();
      if (!anyFilled) return; // fully blank rows are ignored on submit
      if (!med.name.trim()) errs[`med-${i}-name`] = 'Medication name is required.';
      if (!med.dosage.trim()) errs[`med-${i}-dosage`] = 'Dosage is required.';
      if (!med.frequency.trim()) errs[`med-${i}-frequency`] = 'Frequency is required.';
      if (med.duration_days !== null && med.duration_days < 1)
        errs[`med-${i}-duration`] = 'Duration must be at least 1 day.';
    });

    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleSubmitConsultation() {
    setSubmitError(null);
    setNotice(null);
    if (!validate()) return;

    const payloadMeds = medications.filter(
      (m) => m.name.trim() && m.dosage.trim() && m.frequency.trim(),
    );

    setSubmitting(true);
    try {
      await api.submitConsultation(appointmentId, {
        notes: notes.trim(),
        prescription_instructions: instructions.trim() || undefined,
        medications: payloadMeds,
      });
      setNotice(
        payloadMeds.length > 0
          ? 'Consultation saved. Medication reminders have been scheduled for the patient.'
          : 'Consultation saved.',
      );
      consultationQuery.reload();
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGeneratePostVisit() {
    setGenerateError(null);
    setGenerating(true);
    try {
      await api.generatePostVisitSummary(appointmentId);
      postVisitQuery.reload();
    } catch (err) {
      setGenerateError(err);
    } finally {
      setGenerating(false);
    }
  }

  if (apptQuery.loading && !apptQuery.data) return <Spinner label="Loading appointment…" />;
  if (apptQuery.error)
    return (
      <div className="page">
        <ErrorBanner error={apptQuery.error} onRetry={apptQuery.reload} />
        <Link className="btn" to="/doctor/appointments">
          Back
        </Link>
      </div>
    );
  if (!apptQuery.data) return null;

  const appt = apptQuery.data;
  const preVisit = preVisitQuery.data;
  const preVisitPayload = preVisit?.status === 'SUCCESS' ? (preVisit.payload as PreVisitPayload) : null;
  const consultation = consultationQuery.data;
  const postVisit = postVisitQuery.data;
  const postVisitPayload =
    postVisit?.status === 'SUCCESS' ? (postVisit.payload as PostVisitPayload) : null;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Consultation</h1>
          <p className="muted">{formatDateTime(appt.start_time)}</p>
        </div>
        <Link className="btn" to="/doctor/appointments">
          Back
        </Link>
      </header>

      {notice ? <SuccessBanner>{notice}</SuccessBanner> : null}

      <Card title="Appointment">
        <div className="summary-row">
          <span>Patient</span>
          <strong>{appt.patient_name ?? 'Unknown patient'}</strong>
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
      </Card>

      <Card title="Pre-visit AI summary">
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
            <span className="muted small">Patient's suggested questions</span>
            <ol className="numbered">
              {preVisitPayload.suggested_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
            <p className="muted small">
              AI-generated from the patient's own symptom description. Not a diagnosis.
            </p>
          </>
        ) : null}
        {!preVisitQuery.loading && !preVisitQuery.error && !preVisitPayload ? (
          <EmptyState>
            {preVisit?.status === 'FAILED'
              ? `The summary could not be generated${preVisit.error_message ? `: ${preVisit.error_message}` : '.'}`
              : 'The patient has not submitted symptoms for this appointment.'}
          </EmptyState>
        ) : null}
      </Card>

      {consultation ? (
        <Card title="Consultation record">
          <InfoBanner>
            A consultation has already been submitted for this appointment and cannot be resubmitted.
          </InfoBanner>
          <h3>Notes</h3>
          <p className="prewrap">{consultation.notes}</p>
          {consultation.medications.length > 0 ? (
            <>
              <h3>Prescription</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Medication</th>
                    <th>Dosage</th>
                    <th>Frequency</th>
                    <th>Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {consultation.medications.map((m) => (
                    <tr key={m.id}>
                      <td>{m.name}</td>
                      <td>{m.dosage}</td>
                      <td>{m.frequency}</td>
                      <td>{m.duration_days ? `${m.duration_days} days` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
        </Card>
      ) : !CONSULTABLE.has(appt.status) ? (
        <Card title="Record consultation">
          <InfoBanner>
            This appointment is {appt.status.toLowerCase()}, so a consultation can't be recorded for it.
          </InfoBanner>
        </Card>
      ) : (
        <Card title="Record consultation">
          {consultationQuery.loading ? <Spinner /> : null}
          <ErrorBanner error={consultationQuery.error} onRetry={consultationQuery.reload} />
          <ErrorBanner error={submitError} />

          <Field label="Consultation notes" htmlFor="notes" error={fieldErrors.notes}>
            <textarea
              id="notes"
              rows={6}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={submitting}
              placeholder="Clinical findings, assessment, and plan…"
            />
          </Field>

          <h3>Prescription</h3>
          <Field
            label="Instructions (optional)"
            htmlFor="instructions"
            hint="General guidance, e.g. take with food."
          >
            <input
              id="instructions"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              disabled={submitting}
            />
          </Field>

          {medications.map((med, i) => (
            <div key={i} className="med-row">
              <Field label="Medication" htmlFor={`med-${i}-name`} error={fieldErrors[`med-${i}-name`]}>
                <input
                  id={`med-${i}-name`}
                  value={med.name}
                  onChange={(e) => updateMedication(i, { name: e.target.value })}
                  disabled={submitting}
                  placeholder="e.g. Amoxicillin"
                />
              </Field>
              <Field label="Dosage" htmlFor={`med-${i}-dosage`} error={fieldErrors[`med-${i}-dosage`]}>
                <input
                  id={`med-${i}-dosage`}
                  value={med.dosage}
                  onChange={(e) => updateMedication(i, { dosage: e.target.value })}
                  disabled={submitting}
                  placeholder="e.g. 250mg"
                />
              </Field>
              <Field
                label="Frequency"
                htmlFor={`med-${i}-frequency`}
                error={fieldErrors[`med-${i}-frequency`]}
              >
                <input
                  id={`med-${i}-frequency`}
                  value={med.frequency}
                  onChange={(e) => updateMedication(i, { frequency: e.target.value })}
                  disabled={submitting}
                  placeholder="e.g. Twice daily"
                />
              </Field>
              <Field
                label="Days"
                htmlFor={`med-${i}-duration`}
                error={fieldErrors[`med-${i}-duration`]}
              >
                <input
                  id={`med-${i}-duration`}
                  type="number"
                  min={1}
                  value={med.duration_days ?? ''}
                  onChange={(e) =>
                    updateMedication(i, {
                      duration_days: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                  disabled={submitting}
                />
              </Field>
              {medications.length > 1 ? (
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => setMedications((m) => m.filter((_, idx) => idx !== i))}
                  disabled={submitting}
                  aria-label={`Remove medication ${i + 1}`}
                >
                  Remove
                </button>
              ) : null}
            </div>
          ))}

          <div className="row-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setMedications((m) => [...m, { ...EMPTY_MED }])}
              disabled={submitting}
            >
              Add medication
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSubmitConsultation}
              disabled={submitting}
            >
              {submitting ? 'Saving…' : 'Submit consultation'}
            </button>
          </div>
          <p className="muted small">
            Medications with a duration generate daily reminders for the patient.
          </p>
        </Card>
      )}

      <Card
        title="Post-visit summary"
        actions={
          consultation ? (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={handleGeneratePostVisit}
              disabled={generating}
            >
              {generating ? 'Generating…' : postVisitPayload ? 'Regenerate' : 'Generate'}
            </button>
          ) : null
        }
      >
        <ErrorBanner error={generateError} />
        <ErrorBanner error={postVisitQuery.error} onRetry={postVisitQuery.reload} />
        {postVisitQuery.loading || generating ? <Spinner /> : null}

        {!consultation ? (
          <EmptyState>Submit the consultation first to generate a patient-friendly summary.</EmptyState>
        ) : null}

        {consultation && !postVisitQuery.loading && !generating && postVisitPayload ? (
          <>
            <h3>Summary</h3>
            <p className="prewrap">{postVisitPayload.summary}</p>
            <h3>Medication schedule</h3>
            <p className="prewrap">{postVisitPayload.medication_schedule}</p>
            <h3>Follow-up steps</h3>
            <p className="prewrap">{postVisitPayload.follow_up_steps}</p>
            <p className="muted small">This is what the patient sees on their appointment page.</p>
          </>
        ) : null}

        {consultation && !postVisitQuery.loading && !postVisitQuery.error && !generating && !postVisitPayload ? (
          <EmptyState>
            {postVisit?.status === 'FAILED'
              ? `The last attempt failed${postVisit.error_message ? `: ${postVisit.error_message}` : '.'} You can try again.`
              : 'No summary generated yet.'}
          </EmptyState>
        ) : null}
      </Card>
    </div>
  );
}
