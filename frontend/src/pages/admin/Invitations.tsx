import { FormEvent, useState } from 'react';
import { api } from '../../api/client';
import type { InvitationCreated, InvitationStatus, StaffRole } from '../../api/types';
import { Badge, Card, EmptyState, ErrorBanner, Field, InfoBanner, Spinner, SuccessBanner } from '../../components/ui';
import { COMMON_TIMEZONES, formatDateTime, isValidTimeZone } from '../../lib/format';
import { useAsync } from '../../lib/useAsync';

const STATUS_TONE: Record<InvitationStatus, string> = {
  PENDING: 'info',
  ACCEPTED: 'ok',
  REVOKED: 'muted',
  EXPIRED: 'warn',
};

export default function Invitations() {
  const { data, loading, error, reload } = useAsync(() => api.listInvitations(), []);

  const [email, setEmail] = useState('');
  const [role, setRole] = useState<StaffRole>('DOCTOR');
  const [fullName, setFullName] = useState('');
  const [specialization, setSpecialization] = useState('');
  const [slotDuration, setSlotDuration] = useState(30);
  const [timezone, setTimezone] = useState('UTC');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<InvitationCreated | null>(null);
  const [revokeError, setRevokeError] = useState<unknown>(null);

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) errs.email = 'Enter a valid email address.';
    if (fullName.trim() && fullName.trim().length < 2) errs.fullName = 'Enter at least 2 characters, or leave it empty.';
    if (role === 'DOCTOR') {
      if (specialization.trim().length < 2) errs.specialization = 'Specialisation is required for a doctor.';
      if (slotDuration < 5 || slotDuration > 240) errs.slotDuration = 'Slot duration must be between 5 and 240 minutes.';
      if (!isValidTimeZone(timezone.trim() || 'UTC')) errs.timezone = 'Enter a valid timezone, e.g. Asia/Kolkata.';
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    setCreated(null);
    if (!validate()) return;

    setSubmitting(true);
    try {
      const result = await api.createInvitation({
        email: email.trim(),
        role,
        full_name: fullName.trim() || undefined,
        ...(role === 'DOCTOR'
          ? {
              specialization: specialization.trim(),
              slot_duration_minutes: slotDuration,
              timezone: timezone.trim() || 'UTC',
            }
          : {}),
      });
      setCreated(result);
      setEmail('');
      setFullName('');
      setSpecialization('');
      setSlotDuration(30);
      setTimezone('UTC');
      reload();
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke(id: string) {
    setRevokeError(null);
    try {
      await api.revokeInvitation(id);
      reload();
    } catch (err) {
      setRevokeError(err);
    }
  }

  const invitations = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Invitations</h1>
          <p className="muted">
            Invite a doctor or another administrator by email. They sign up on the normal sign-up
            page; their role comes from the invitation, never from anything they type.
          </p>
        </div>
      </header>

      {created ? (
        <SuccessBanner>
          Invitation created for {created.invitation.email}.{' '}
          {created.email_queued
            ? 'An email with the link is on its way.'
            : 'The email could not be queued, so send them this link yourself.'}
          <div className="small">
            Link (shown once; it cannot be retrieved later):
            <div className="mono" data-testid="invite-link">
              {created.invite_link}
            </div>
          </div>
        </SuccessBanner>
      ) : null}

      <Card title="Invite someone">
        <ErrorBanner error={submitError} />
        <form onSubmit={handleInvite} noValidate>
          <div className="form-grid">
            <Field label="Email" htmlFor="invite-email" error={fieldErrors.email}>
              <input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
              />
            </Field>
            <Field label="Role" htmlFor="invite-role">
              <select
                id="invite-role"
                value={role}
                onChange={(e) => setRole(e.target.value as StaffRole)}
                disabled={submitting}
              >
                <option value="DOCTOR">Doctor</option>
                <option value="ADMIN">Administrator</option>
              </select>
            </Field>
            <Field
              label="Name (optional)"
              htmlFor="invite-name"
              error={fieldErrors.fullName}
              hint="Pre-fills the sign-up form."
            >
              <input
                id="invite-name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                disabled={submitting}
              />
            </Field>
            {role === 'DOCTOR' ? (
              <>
                <Field label="Specialisation" htmlFor="invite-spec" error={fieldErrors.specialization}>
                  <input
                    id="invite-spec"
                    value={specialization}
                    onChange={(e) => setSpecialization(e.target.value)}
                    disabled={submitting}
                    placeholder="e.g. Cardiology"
                  />
                </Field>
                <Field
                  label="Slot duration (minutes)"
                  htmlFor="invite-slot"
                  error={fieldErrors.slotDuration}
                  hint="Between 5 and 240."
                >
                  <input
                    id="invite-slot"
                    type="number"
                    min={5}
                    max={240}
                    value={slotDuration}
                    onChange={(e) => setSlotDuration(Number(e.target.value))}
                    disabled={submitting}
                  />
                </Field>
                <Field
                  label="Timezone"
                  htmlFor="invite-tz"
                  error={fieldErrors.timezone}
                  hint="The timezone their working hours are in (IANA name, e.g. Asia/Kolkata)."
                >
                  <input
                    id="invite-tz"
                    list="invite-timezone-options"
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    disabled={submitting}
                  />
                  <datalist id="invite-timezone-options">
                    {COMMON_TIMEZONES.map((zone) => (
                      <option key={zone} value={zone} />
                    ))}
                  </datalist>
                </Field>
              </>
            ) : null}
          </div>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Sending…' : 'Send invitation'}
          </button>
        </form>
      </Card>

      <Card title="Recent invitations">
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        <ErrorBanner error={revokeError} />
        {!loading && !error ? (
          invitations.length === 0 ? (
            <EmptyState>No invitations yet.</EmptyState>
          ) : (
            <ul className="list">
              {invitations.map((inv) => (
                <li key={inv.id} className="list-row">
                  <div>
                    <strong>{inv.email}</strong>
                    <div className="muted small">
                      {inv.role === 'DOCTOR' ? `Doctor · ${inv.specialization ?? ''}` : 'Administrator'} · sent{' '}
                      {formatDateTime(inv.created_at)}
                      {inv.status === 'PENDING' ? ` · expires ${formatDateTime(inv.expires_at)}` : ''}
                    </div>
                  </div>
                  <div className="list-row-end">
                    <Badge tone={STATUS_TONE[inv.status]}>{inv.status}</Badge>
                    {inv.status === 'PENDING' ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        aria-label={`Revoke invitation for ${inv.email}`}
                        onClick={() => handleRevoke(inv.id)}
                      >
                        Revoke
                      </button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
        <InfoBanner>
          Sending a new invitation to the same address withdraws the older one. Patients do not need
          an invitation; they sign up themselves.
        </InfoBanner>
      </Card>
    </div>
  );
}
