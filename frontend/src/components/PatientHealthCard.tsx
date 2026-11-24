import { api } from '../api/client';
import { useAsync } from '../lib/useAsync';
import { Card, ErrorBanner, Spinner } from './ui';

/** The patient's age and allergies on the doctor's appointment page. Allergies come first and
 *  stand out, because they matter when prescribing. */
export function PatientHealthCard({ appointmentId }: { appointmentId: string }) {
  const { data, loading, error, reload } = useAsync(() => api.getPatientHealth(appointmentId), [appointmentId]);
  return (
    <Card title="Patient health">
      {loading ? <Spinner /> : null}
      <ErrorBanner error={error} onRetry={reload} />
      {data ? (
        <>
          <div className={data.allergies ? 'banner banner-danger' : 'summary-row'}>
            <strong>Allergies:</strong> <span className="prewrap">{data.allergies ?? 'None recorded'}</span>
          </div>
          <div className="summary-row">
            <span>Age</span>
            <strong>{data.age ?? 'Not recorded'}</strong>
          </div>
        </>
      ) : null}
    </Card>
  );
}
