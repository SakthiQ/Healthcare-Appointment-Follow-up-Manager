import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { Card, EmptyState, ErrorBanner, Spinner } from '../../components/ui';

export default function DoctorSearch() {
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');

  const { data, loading, error, reload } = useAsync(
    () => api.searchDoctors(query || undefined),
    [query],
  );

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setQuery(input.trim());
  }

  const doctors = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Find a doctor</h1>
          <p className="muted">Search by specialisation, then pick an available slot.</p>
        </div>
      </header>

      <Card>
        <form className="search-bar" onSubmit={handleSubmit}>
          <label className="sr-only" htmlFor="specialization">
            Specialisation
          </label>
          <input
            id="specialization"
            placeholder="e.g. Cardiology, Paediatrics, Dermatology"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button type="submit" className="btn btn-primary">
            Search
          </button>
          {query ? (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setInput('');
                setQuery('');
              }}
            >
              Clear
            </button>
          ) : null}
        </form>
      </Card>

      <Card title={query ? `Doctors matching "${query}"` : 'All available doctors'}>
        {loading ? <Spinner label="Searching…" /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          doctors.length === 0 ? (
            <EmptyState>
              No doctors found{query ? ` for "${query}"` : ''}. Try a different specialisation.
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
