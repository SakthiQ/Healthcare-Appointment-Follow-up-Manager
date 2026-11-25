import { useState } from 'react';
import { api, nullIfNotFound } from '../api/client';
import type { HistoryPayload } from '../api/types';
import { formatDate } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import { Card, EmptyState, ErrorBanner, Spinner } from './ui';

/** An AI summary of the patient's earlier visits, for the doctor (#73). Generated on demand,
 *  since each generation is an LLM call that counts towards the AI limits. */
export function PreviousVisitsCard({ appointmentId }: { appointmentId: string }) {
  const query = useAsync(() => nullIfNotFound(api.getHistorySummary(appointmentId)), [appointmentId]);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<unknown>(null);

  async function generate() {
    setGenerateError(null);
    setGenerating(true);
    try {
      await api.generateHistorySummary(appointmentId);
      query.reload();
    } catch (err) {
      setGenerateError(err);
    } finally {
      setGenerating(false);
    }
  }

  const summary = query.data;
  const payload = summary?.status === 'SUCCESS' ? (summary.payload as HistoryPayload) : null;
  const busy = query.loading || generating;

  return (
    <Card
      title="Previous visits"
      actions={
        <button type="button" className="btn btn-sm btn-primary" onClick={generate} disabled={busy}>
          {generating ? 'Generating…' : payload ? 'Regenerate' : 'Generate'}
        </button>
      }
    >
      <ErrorBanner error={generateError} />
      <ErrorBanner error={query.error} onRetry={query.reload} />
      {busy ? <Spinner /> : null}

      {!busy && payload ? (
        <>
          {payload.recent_visits.length === 0 ? (
            <EmptyState>{payload.notes_for_doctor}</EmptyState>
          ) : (
            <>
              <ul className="history-visits">
                {payload.recent_visits.map((visit, i) => (
                  <li key={`${visit.date}-${i}`}>
                    <div className="summary-row">
                      <span>{formatDate(`${visit.date}T00:00:00Z`, 'UTC')}</span>
                      <strong className="prewrap">{visit.complaint}</strong>
                    </div>
                    {visit.medications.length > 0 ? (
                      <p className="muted small">{visit.medications.join('; ')}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
              {payload.recurring_issues.length > 0 ? (
                <>
                  <h3>Recurring</h3>
                  <ul>
                    {payload.recurring_issues.map((issue, i) => (
                      <li key={i}>{issue}</li>
                    ))}
                  </ul>
                </>
              ) : null}
              <p className="prewrap">{payload.notes_for_doctor}</p>
            </>
          )}
          <p className="muted small">
            AI-generated from the clinic's records of earlier visits. Not a diagnosis: check the records
            before relying on it.
          </p>
        </>
      ) : null}

      {!busy && !query.error && !payload ? (
        <EmptyState>
          {summary?.status === 'FAILED'
            ? `The last attempt failed${summary.error_message ? `: ${summary.error_message}` : '.'} You can try again.`
            : "Generate a summary of the patient's earlier visits with the clinic."}
        </EmptyState>
      ) : null}
    </Card>
  );
}
