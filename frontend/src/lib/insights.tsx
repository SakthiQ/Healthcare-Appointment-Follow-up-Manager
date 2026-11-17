import { Analytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';

// A path segment that identifies a record (a UUID, or any long string of letters and digits
// that contains a digit), e.g. /patient/appointments/3f2c... or /admin/doctors/<id>.
const ID_SEGMENT = /^(?=.*\d)[A-Za-z0-9_-]{16,}$/;

/**
 * The URL to report to Vercel Web Analytics and Speed Insights.
 *
 * Query strings and fragments are dropped because some of them are secrets: invitation
 * links (/register?invite=...), password-reset and email-verification links carry
 * single-use tokens. Record IDs in the path are replaced with ":id", so the reports show
 * which pages are used without saying which patient, doctor or appointment was viewed.
 */
export function scrubUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return '';
  }
  const path = parsed.pathname
    .split('/')
    .map((segment) => (ID_SEGMENT.test(segment) ? ':id' : segment))
    .join('/');
  return `${parsed.origin}${path}`;
}

/**
 * Vercel Web Analytics (page views) and Speed Insights (Core Web Vitals). Both are
 * cookieless and only send data when the site runs on Vercel with the feature turned on
 * in the project's dashboard. Every URL goes through scrubUrl first.
 */
export function VercelInsights() {
  return (
    <>
      <Analytics beforeSend={(event) => ({ ...event, url: scrubUrl(event.url) })} />
      <SpeedInsights beforeSend={(event) => ({ ...event, url: scrubUrl(event.url) })} />
    </>
  );
}
