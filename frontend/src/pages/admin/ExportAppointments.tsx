import { FormEvent, useState } from 'react';
import { api, type AppointmentExportFilters } from '../../api/client';
import type { AppointmentStatus, Doctor } from '../../api/types';
import { Card, ErrorBanner, Field } from '../../components/ui';
import { saveTextFile } from '../../lib/download';

const STATUSES: AppointmentStatus[] = ['CONFIRMED', 'RESCHEDULED', 'CONFLICTED', 'COMPLETED', 'CANCELLED', 'HELD'];

function nextDay(date: string): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** Download appointments as a CSV file for spreadsheets, using the filters chosen here.
 *  Scheduling data only; the server audits every export and caps it at 10,000 rows. */
export default function ExportAppointments({ doctors }: { doctors: Doctor[] }) {
  const [status, setStatus] = useState('');
  const [doctorId, setDoctorId] = useState('');
  const [from, setFrom] = useState('');
  const [until, setUntil] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleExport(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const filters: AppointmentExportFilters = {
      status: status || undefined,
      doctor_id: doctorId || undefined,
      from: from ? `${from}T00:00:00Z` : undefined,
      // The "until" date is inclusive: everything starting before the next day.
      until: until ? `${nextDay(until)}T00:00:00Z` : undefined,
    };
    try {
      const csv = await api.exportAppointmentsCsv(filters);
      saveTextFile(`appointments-${new Date().toISOString().slice(0, 10)}.csv`, csv, 'text/csv;charset=utf-8');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Export appointments">
      <p className="muted small">
        Download appointments as a CSV file for a spreadsheet. Scheduling data only, no clinical
        notes. Every export is recorded in the audit log.
      </p>
      <ErrorBanner error={error} />
      <form onSubmit={handleExport} noValidate>
        <div className="form-grid">
          <Field label="Status" htmlFor="export-status">
            <select id="export-status" value={status} onChange={(e) => setStatus(e.target.value)} disabled={busy}>
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Doctor" htmlFor="export-doctor">
            <select id="export-doctor" value={doctorId} onChange={(e) => setDoctorId(e.target.value)} disabled={busy}>
              <option value="">All doctors</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.is_active ? d.full_name : `${d.full_name} (inactive)`}
                </option>
              ))}
            </select>
          </Field>
          <Field label="From (UTC date)" htmlFor="export-from">
            <input id="export-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} disabled={busy} />
          </Field>
          <Field label="Until (UTC date, inclusive)" htmlFor="export-until">
            <input id="export-until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} disabled={busy} />
          </Field>
        </div>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Exporting…' : 'Export CSV'}
        </button>
      </form>
    </Card>
  );
}
