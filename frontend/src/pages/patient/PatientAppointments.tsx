import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { AppointmentStatus } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { formatDateTime } from '../../lib/format';
import { Card, EmptyState, ErrorBanner, Pager, Spinner, StatusBadge } from '../../components/ui';
import { useT } from '../../i18n/I18n';
import type { MessageKey } from '../../locales/en';

const PAGE_SIZE = 25;

const FILTERS: { label: MessageKey; value: AppointmentStatus | '' }[] = [
  { label: 'status.all', value: '' },
  { label: 'status.CONFIRMED', value: 'CONFIRMED' },
  { label: 'status.RESCHEDULED', value: 'RESCHEDULED' },
  { label: 'status.CONFLICTED', value: 'CONFLICTED' },
  { label: 'status.CANCELLED', value: 'CANCELLED' },
  { label: 'status.COMPLETED', value: 'COMPLETED' },
];

export default function PatientAppointments() {
  const t = useT();
  const [filter, setFilter] = useState<AppointmentStatus | ''>('');
  const [page, setPage] = useState(0);
  // One page at a time: a long history no longer means downloading every appointment.
  const { data, loading, error, reload } = useAsync(
    () =>
      api.listAppointmentsPage({
        status: filter || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    [filter, page],
  );

  const appointments = data?.items ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t('nav.myAppointments')}</h1>
          <p className="muted">Everything you've booked, past and upcoming.</p>
        </div>
        <Link to="/patient/doctors" className="btn btn-primary">
          {t('appts.bookAnother')}
        </Link>
      </header>

      <Card>
        <div className="filter-row" role="group" aria-label={t('appts.filter')}>
          {FILTERS.map((f) => (
            <button
              key={f.value || 'all'}
              type="button"
              className={filter === f.value ? 'pill active' : 'pill'}
              onClick={() => {
                setFilter(f.value);
                setPage(0);
              }}
            >
              {t(f.label)}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          appointments.length === 0 ? (
            <EmptyState>{filter ? t('appts.noneWithStatus', { status: filter }) : t('appts.none')}</EmptyState>
          ) : (
            <ul className="list">
              {appointments.map((appt) => (
                <li key={appt.id} className="list-row">
                  <div>
                    <strong>{formatDateTime(appt.start_time, appt.doctor_timezone)}</strong>
                    <div className="muted small">
                      {appt.doctor_name ?? t('appts.unknownDoctor')} · {t('appts.ends')} {formatDateTime(appt.end_time, appt.doctor_timezone)}
                    </div>
                  </div>
                  <div className="list-row-end">
                    <StatusBadge status={appt.status} />
                    <Link className="btn btn-sm" to={`/patient/appointments/${appt.id}`}>
                      {t('appts.details')}
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
        {!loading && !error && data ? (
          <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
        ) : null}
      </Card>
    </div>
  );
}
