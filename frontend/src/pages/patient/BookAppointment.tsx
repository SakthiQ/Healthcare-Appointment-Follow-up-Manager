import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import type { AISummary, Appointment, Hold, PreVisitPayload, SlotItem } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { useNow } from '../../lib/useNow';
import { JoinWaitlistButton } from '../../components/Waitlist';
import { useT } from '../../i18n/I18n';
import {
  bookableSlots,
  DAY_NAMES,
  formatCountdown,
  formatDateTime,
  formatTime,
  timeZoneName,
  secondsUntil,
  todayInputValue,
  urgencyTone,
} from '../../lib/format';
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  InfoBanner,
  Spinner,
  SuccessBanner,
} from '../../components/ui';

type Step = 'slot' | 'symptoms' | 'done';

export default function BookAppointment() {
  const t = useT();
  const { doctorId = '' } = useParams();
  const navigate = useNavigate();

  const [date, setDate] = useState(todayInputValue());
  const [step, setStep] = useState<Step>('slot');

  const [hold, setHold] = useState<Hold | null>(null);
  const [holdError, setHoldError] = useState<unknown>(null);
  const [holding, setHolding] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const [symptoms, setSymptoms] = useState('');
  const [notes, setNotes] = useState('');
  const [symptomError, setSymptomError] = useState<string | undefined>();

  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<unknown>(null);
  const [appointment, setAppointment] = useState<Appointment | null>(null);
  const [preVisit, setPreVisit] = useState<AISummary | null>(null);

  const doctorQuery = useAsync(() => api.getDoctor(doctorId), [doctorId]);
  const scheduleQuery = useAsync(() => api.getDoctorSchedule(doctorId), [doctorId]);
  const slotsQuery = useAsync(() => api.getSlots(doctorId, date), [doctorId, date]);

  const doctor = doctorQuery.data;
  const slots: SlotItem[] = slotsQuery.data?.slots ?? [];
  const now = useNow();
  const available = useMemo(() => bookableSlots(slots, now), [slots, now]);

  // Leaving the page with an unconfirmed hold releases it, so the slot isn't
  // blocked for everyone until the hold times out.
  const activeHoldId = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    activeHoldId.current = hold?.id ?? null;
  }, [hold]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (activeHoldId.current) void api.releaseHold(activeHoldId.current).catch(() => undefined);
    };
  }, []);

  // Live countdown on the hold — an expired hold cannot be confirmed, and the
  // backend is the authority on that, so we surface the deadline clearly.
  useEffect(() => {
    if (!hold) return;
    setSecondsLeft(secondsUntil(hold.expires_at));
    const timer = setInterval(() => setSecondsLeft(secondsUntil(hold.expires_at)), 1000);
    return () => clearInterval(timer);
  }, [hold]);

  const holdExpired = hold !== null && secondsLeft <= 0;

  async function handleSelectSlot(slot: SlotItem) {
    setHoldError(null);
    setConfirmError(null);
    setHolding(true);
    try {
      const created = await api.createHold({
        doctor_id: doctorId,
        start_time: slot.start_time,
        end_time: slot.end_time,
      });
      if (!mounted.current) {
        // The patient left while the hold was being created — give it back.
        void api.releaseHold(created.id).catch(() => undefined);
        return;
      }
      setHold(created);
      setStep('symptoms');
    } catch (err) {
      setHoldError(err);
      // Someone else may have taken it — refresh availability from the backend.
      slotsQuery.reload();
    } finally {
      setHolding(false);
    }
  }

  async function handleReleaseHold() {
    if (!hold) return;
    try {
      await api.releaseHold(hold.id);
    } catch {
      // Releasing is best-effort; the hold expires on its own regardless.
    }
    setHold(null);
    setStep('slot');
    slotsQuery.reload();
  }

  async function handleConfirm() {
    if (!hold) return;
    if (symptoms.trim().length < 3) {
      setSymptomError(t('book.symptomsTooShort'));
      return;
    }
    setSymptomError(undefined);
    setConfirmError(null);
    setConfirming(true);

    try {
      // The backend keys the symptom report and the AI summary to an
      // appointment id, so the appointment is created first and the symptoms
      // captured above are submitted immediately afterwards.
      const created = await api.createAppointment({
        doctor_id: doctorId,
        hold_id: hold.id,
        notes: notes.trim() || undefined,
      });
      activeHoldId.current = null; // consumed by the booking — nothing to release
      setAppointment(created);

      try {
        await api.submitSymptomReport(created.id, symptoms.trim());
        const summary = await api.generatePreVisitSummary(created.id);
        setPreVisit(summary);
      } catch (aiErr) {
        // The appointment is already confirmed and valid — an AI/symptom
        // failure must never present as a failed booking.
        console.warn('Pre-visit summary could not be generated', aiErr);
      }

      setHold(null);
      setStep('done');
    } catch (err) {
      setConfirmError(err);
      if (err instanceof ApiError && (err.status === 409 || err.status === 422)) {
        // Hold expired or slot taken — return to slot selection with fresh data.
        setHold(null);
        setStep('slot');
        slotsQuery.reload();
      }
    } finally {
      setConfirming(false);
    }
  }

  if (doctorQuery.loading) return <Spinner label={t('book.loadingDoctor')} />;
  if (doctorQuery.error)
    return (
      <div className="page">
        <ErrorBanner error={doctorQuery.error} onRetry={doctorQuery.reload} />
        <Link className="btn" to="/patient/doctors">
          {t('book.backToSearch')}
        </Link>
      </div>
    );

  // ---- Step 3: confirmed ----
  if (step === 'done' && appointment) {
    const payload = preVisit?.payload as PreVisitPayload | null;
    return (
      <div className="page">
        <header className="page-head">
          <h1>{t('book.confirmed')}</h1>
        </header>

        <SuccessBanner>
          <div>
            <strong>{t('book.bookedWith', { doctor: doctor?.full_name ?? '' })}</strong>
            <div>{formatDateTime(appointment.start_time, appointment.doctor_timezone)}</div>
          </div>
        </SuccessBanner>

        <Card title={t('book.summaryTitle')}>
          {preVisit?.status === 'SUCCESS' && payload ? (
            <>
              <p className="muted small">
                {t('book.summaryShared')}
              </p>
              <div className="summary-row">
                <span>{t('book.urgency')}</span>
                <Badge tone={urgencyTone(payload.urgency)}>{payload.urgency}</Badge>
              </div>
              <div className="summary-row">
                <span>{t('book.chiefComplaint')}</span>
                <strong>{payload.chief_complaint}</strong>
              </div>
              <div>
                <span className="muted small">{t('book.questions')}</span>
                <ol className="numbered">
                  {payload.suggested_questions.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ol>
              </div>
            </>
          ) : (
            <InfoBanner>
              {t('book.summaryFailed', { reason: preVisit?.error_message ? `: ${preVisit.error_message}.` : '.' })}
            </InfoBanner>
          )}
        </Card>

        <div className="row-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate(`/patient/appointments/${appointment.id}`)}
          >
            {t('book.viewAppointment')}
          </button>
          <Link className="btn" to="/patient/appointments">
            {t('book.allAppointments')}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{doctor?.full_name}</h1>
          <p className="muted">
            {doctor?.specialization} · {doctor?.slot_duration_minutes} minute appointments
          </p>
        </div>
        <Link className="btn" to="/patient/doctors">
          {t('book.backToSearch')}
        </Link>
      </header>

      <ol className="steps" aria-label={t('book.progress')}>
        <li className={step === 'slot' ? 'current' : 'complete'}>{t('book.step1')}</li>
        <li className={step === 'symptoms' ? 'current' : step === 'slot' ? '' : 'complete'}>
          {t('book.step2')}
        </li>
        <li>{t('book.step3')}</li>
      </ol>

      {/* ---- Step 1: slot selection ---- */}
      {step === 'slot' ? (
        <>
          <Card title={t('book.weekly')}>
            {scheduleQuery.loading ? <Spinner /> : null}
            <ErrorBanner error={scheduleQuery.error} onRetry={scheduleQuery.reload} />
            {scheduleQuery.data ? (
              scheduleQuery.data.length === 0 ? (
                <EmptyState>{t('book.noHours')}</EmptyState>
              ) : (
                <ul className="chips">
                  {scheduleQuery.data
                    .filter((wh) => wh.is_active)
                    .map((wh) => (
                      <li key={wh.id} className="chip">
                        {DAY_NAMES[wh.day_of_week]} {wh.start_time.slice(0, 5)}–{wh.end_time.slice(0, 5)} {timeZoneName(doctor?.timezone)}
                      </li>
                    ))}
                </ul>
              )
            ) : null}
          </Card>

          <Card title={t('book.availableSlots')}>
            <ErrorBanner error={confirmError} />
            <ErrorBanner error={holdError} />

            <Field label={t('book.date')} htmlFor="date">
              <input
                id="date"
                type="date"
                value={date}
                min={todayInputValue()}
                onChange={(e) => setDate(e.target.value)}
              />
            </Field>

            {slotsQuery.loading ? <Spinner label={t('book.checking')} /> : null}
            <ErrorBanner error={slotsQuery.error} onRetry={slotsQuery.reload} />

            {!slotsQuery.loading && !slotsQuery.error ? (
              available.length === 0 ? (
                <>
                <EmptyState>
                  {slotsQuery.data && slotsQuery.data.total_slots > 0 ? t('book.noSlotsTaken') : t('book.noSlotsOff')}
                </EmptyState>
                {/* A working day with every slot taken: offer the waitlist (future dates only). */}
                {slotsQuery.data && slotsQuery.data.total_slots > 0 && date > todayInputValue() ? (
                  <JoinWaitlistButton key={date} doctorId={doctorId} date={date} />
                ) : null}
                </>
              ) : (
                <>
                  <p className="muted small">
                    {t('book.slotsAvailable', { available: available.length, total: slotsQuery.data?.total_slots ?? 0, zone: timeZoneName(doctor?.timezone) })}
                  </p>
                  <div className="slot-grid">
                    {available.map((slot) => (
                      <button
                        key={slot.start_time}
                        type="button"
                        className="slot"
                        disabled={holding}
                        onClick={() => handleSelectSlot(slot)}
                      >
                        {formatTime(slot.start_time, doctor?.timezone)}
                        <span className="slot-end">–{formatTime(slot.end_time, doctor?.timezone)}</span>
                      </button>
                    ))}
                  </div>
                  {holding ? <Spinner label={t('book.reserving')} /> : null}
                </>
              )
            ) : null}
          </Card>
        </>
      ) : null}

      {/* ---- Step 2: symptoms ---- */}
      {step === 'symptoms' && hold ? (
        <>
          <Card title={t('book.reserved')}>
            <div className="summary-row">
              <span>{t('book.time')}</span>
              <strong>{formatDateTime(hold.start_time, doctor?.timezone)}</strong>
            </div>
            <div className="summary-row">
              <span>{t('book.holdExpiresIn')}</span>
              {holdExpired ? (
                <Badge tone="danger">{t('book.expired')}</Badge>
              ) : (
                <Badge tone={secondsLeft < 120 ? 'warn' : 'info'}>{formatCountdown(secondsLeft)}</Badge>
              )}
            </div>
            {holdExpired ? (
              <InfoBanner>
                {t('book.holdExpired')}
              </InfoBanner>
            ) : null}
            <div className="row-actions">
              <button type="button" className="btn" onClick={handleReleaseHold} disabled={confirming}>
                {holdExpired ? t('book.chooseAnother') : t('book.release')}
              </button>
            </div>
          </Card>

          <Card title={t('book.describe')}>
            <p className="muted small">
              {t('book.describeHelp')}
            </p>
            <ErrorBanner error={confirmError} />

            <Field
              label={t('book.symptoms')}
              htmlFor="symptoms"
              error={symptomError}
              hint={t('book.symptomsHint')}
            >
              <textarea
                id="symptoms"
                rows={6}
                value={symptoms}
                onChange={(e) => setSymptoms(e.target.value)}
                disabled={confirming || holdExpired}
                placeholder="e.g. Persistent headache for the last three days, worse in the morning…"
              />
            </Field>

            <Field
              label={t('book.notes')}
              htmlFor="booking-notes"
              hint={t('book.notesHint')}
            >
              <textarea
                id="booking-notes"
                rows={3}
                maxLength={2000}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                disabled={confirming || holdExpired}
              />
            </Field>

            <button
              type="button"
              className="btn btn-primary btn-block"
              onClick={handleConfirm}
              disabled={confirming || holdExpired}
            >
              {confirming ? t('book.confirming') : t('book.confirm')}
            </button>
          </Card>
        </>
      ) : null}
    </div>
  );
}
