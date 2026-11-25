import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { Card, EmptyState, ErrorBanner, Spinner } from '../../components/ui';

export default function DoctorSearch() {
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
          <h1>Find a doctor</h1>
          <p className="muted">Search by name or specialisation, then pick an available slot.</p>
        </div>
      </header>

      {departments.length > 0 ? (
        <div className="filter-row" role="group" aria-label="Departments">
          <button type="button" className={departmentId === '' ? 'pill active' : 'pill'} aria-pressed={departmentId === ''}
            onClick={() => setDepartmentId('')}>
            All departments
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
            Doctor's name
          </label>
          <input
            id="doctor-name"
            placeholder="Doctor's name, e.g. Rao"
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
          />
          <label className="sr-only" htmlFor="specialization">
            Specialisation
          </label>
          <input
            id="specialization"
            placeholder="Specialisation, e.g. Cardiology"
            value={specInput}
            onChange={(e) => setSpecInput(e.target.value)}
          />
          <button type="submit" className="btn btn-primary">
            Search
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
              Clear
            </button>
          ) : null}
        </form>
      </Card>

      <Card title={searching ? `Doctors matching "${searchLabel}"` : 'All available doctors'}>
        {loading ? <Spinner label="Searching…" /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          doctors.length === 0 ? (
            <EmptyState>
              No doctors found{searching ? ` for "${searchLabel}"` : ''}. Try a different name or
              specialisation.
            </EmptyState>
          ) : (
            <div className="grid">
              {doctors.map((doc) => (
                <article key={doc.id} className="tile">
                  <h3>{doc.full_name}</h3>
                  <p className="tile-sub">{doc.specialization}</p>
                  <dl className="kv">
                    <div>
                      <dt>Appointment length</dt>
                      <dd>{doc.slot_duration_minutes} minutes</dd>
                    </div>
                  </dl>
                  <Link className="btn btn-primary btn-block" to={`/patient/doctors/${doc.id}`}>
                    View availability
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
