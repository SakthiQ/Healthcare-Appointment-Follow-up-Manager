import { useState } from 'react';
import { api } from '../api/client';
import { saveTextFile } from '../lib/download';
import { ErrorBanner } from './ui';

/** Downloads the appointment as an .ics file for Apple Calendar, Outlook or any calendar app.
 *  The API needs the sign-in header, so the file is fetched and saved, not linked. */
export function AddToCalendarButton({ appointmentId }: { appointmentId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleClick() {
    setError(null);
    setBusy(true);
    try {
      const ics = await api.getAppointmentCalendar(appointmentId);
      saveTextFile(`appointment-${appointmentId}.ics`, ics, 'text/calendar;charset=utf-8');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="btn" onClick={handleClick} disabled={busy}>
        {busy ? 'Preparing…' : 'Add to calendar'}
      </button>
      <ErrorBanner error={error} />
    </>
  );
}
