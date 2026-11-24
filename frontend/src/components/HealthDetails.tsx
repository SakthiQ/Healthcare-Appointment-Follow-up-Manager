import { FormEvent, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAsync } from '../lib/useAsync';
import { todayInputValue } from '../lib/format';
import { Card, ErrorBanner, Field, InfoBanner, Spinner, SuccessBanner } from './ui';

/** The patient's own health details, on their Account page. */
export function HealthDetails() {
  const query = useAsync(() => api.getMyProfile(), []);
  const [dob, setDob] = useState('');
  const [phone, setPhone] = useState('');
  const [allergies, setAllergies] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (query.data) {
      setDob(query.data.date_of_birth ?? '');
      setPhone(query.data.phone ?? '');
      setAllergies(query.data.allergies ?? '');
    }
  }, [query.data]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    setBusy(true);
    try {
      await api.updateMyProfile({ date_of_birth: dob || null, phone: phone.trim() || null, allergies: allergies.trim() || null });
      setSaved(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Health details">
      <InfoBanner>
        Only the doctor of each of your appointments and the clinic's administrators can see these.
        Doctors see your age, not your date of birth. Every time they look, it is recorded.
      </InfoBanner>
      {query.loading ? <Spinner /> : null}
      <ErrorBanner error={query.error ?? error} />
      {saved ? <SuccessBanner>Health details saved.</SuccessBanner> : null}
      <form onSubmit={handleSave} noValidate>
        <div className="form-grid">
          <Field label="Date of birth" htmlFor="health-dob">
            <input id="health-dob" type="date" max={todayInputValue()} value={dob} onChange={(e) => setDob(e.target.value)} disabled={busy} />
          </Field>
          <Field label="Phone" htmlFor="health-phone">
            <input id="health-phone" type="tel" maxLength={32} value={phone} onChange={(e) => setPhone(e.target.value)} disabled={busy} />
          </Field>
        </div>
        <Field label="Known allergies" htmlFor="health-allergies" hint="For example: penicillin, peanuts. Leave empty if none.">
          <textarea id="health-allergies" rows={3} maxLength={1000} value={allergies} onChange={(e) => setAllergies(e.target.value)} disabled={busy} />
        </Field>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Saving…' : 'Save health details'}
        </button>
      </form>
    </Card>
  );
}
