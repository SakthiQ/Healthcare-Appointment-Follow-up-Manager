import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { Card, EmptyState, ErrorBanner, Spinner } from '../../components/ui';
import { useT } from '../../i18n/I18n';

export default function DoctorSearch() {
  const t = useT();
  const [nameInput, setNameInput] = useState('');
  const [specInput, setSpecInput] = useState('');
  const [query, setQuery] = useState({ name: '', specialization: '' });
  const [departmentId, setDepartmentId] = useState('');
  const departmentsQuery = useAsync(() => api.listDepartments().catch(() => []), []);
  const departments = departmentsQuery.data ?? [];

  const { data, loading, error, reload } = useAsync(
    () => api.searchDoctors({ ...query, department_id: departmentId || undefined }),
    [query.name, query.specialization, departmentId],
  );

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setQuery({ name: nameInput.trim(), specialization: specInput.trim() });
  }

  const searching = Boolean(query.name || query.specialization);
  const searchLabel = [query.name, query.specialization].filter(Boolean).join(', ');

  const doctors = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t('nav.findDoctor')}</h1>
          <p className="muted">{t('search.subtitle')}</p>
        </div>
      </header>

      {departments.length > 0 ? (
        <div className="filter-row" role="group" aria-label={t('search.departments')}>
          <button type="button" className={departmentId === '' ? 'pill active' : 'pill'} aria-pressed={departmentId === ''}
            onClick={() => setDepartmentId('')}>
            {t('search.allDepartments')}
          </button>
          {departments.map((d) => (
            <button key={d.id} type="button" className={departmentId === d.id ? 'pill active' : 'pill'}
              aria-pressed={departmentId === d.id} onClick={() => setDepartmentId(d.id)}>
              {d.name} ({d.active_doctor_count})
            </button>
          ))}
        </div>
      ) : null}

      <Card>
        <form className="search-bar" onSubmit={handleSubmit}>
          <label className="sr-only" htmlFor="doctor-name">
            {t('search.nameLabel')}
          </label>
          <input
            id="doctor-name"
            placeholder={t('search.namePlaceholder')}
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
          />
          <label className="sr-only" htmlFor="specialization">
            {t('search.specLabel')}
          </label>
          <input
            id="specialization"
            placeholder={t('search.specPlaceholder')}
            value={specInput}
            onChange={(e) => setSpecInput(e.target.value)}
          />
          <button type="submit" className="btn btn-primary">
            {t('search.submit')}
          </button>
          {searching ? (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setNameInput('');
                setSpecInput('');
                setQuery({ name: '', specialization: '' });
              }}
            >
              {t('search.clear')}
            </button>
          ) : null}
        </form>
      </Card>

      <Card title={searching ? t('search.matching', { query: searchLabel }) : t('search.allDoctors')}>
        {loading ? <Spinner label={t('search.searching')} /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          doctors.length === 0 ? (
            <EmptyState>
              {searching ? t('search.noneFor', { query: searchLabel }) : t('search.none')}
            </EmptyState>
          ) : (
            <div className="grid">
              {doctors.map((doc) => (
                <article key={doc.id} className="tile">
                  <h3>{doc.full_name}</h3>
                  <p className="tile-sub">{doc.specialization}</p>
                  <dl className="kv">
                    <div>
                      <dt>{t('search.length')}</dt>
                      <dd>{t('search.minutes', { count: doc.slot_duration_minutes })}</dd>
                    </div>
                  </dl>
                  <Link className="btn btn-primary btn-block" to={`/patient/doctors/${doc.id}`}>
                    {t('search.viewAvailability')}
                  </Link>
                </article>
              ))}
            </div>
          )
        ) : null}
      </Card>
    </div>
  );
}
