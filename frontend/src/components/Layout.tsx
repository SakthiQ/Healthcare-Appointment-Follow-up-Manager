import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { InfoBanner } from './ui';
import type { UserRole } from '../api/types';
import { LanguagePicker, useT } from '../i18n/I18n';
import type { MessageKey } from '../locales/en';

const NAV_BY_ROLE: Record<UserRole, { to: string; label: MessageKey }[]> = {
  PATIENT: [
    { to: '/patient', label: 'nav.dashboard' },
    { to: '/patient/doctors', label: 'nav.findDoctor' },
    { to: '/patient/appointments', label: 'nav.myAppointments' },
    { to: '/patient/history', label: 'nav.healthHistory' },
    { to: '/account', label: 'nav.account' },
  ],
  DOCTOR: [
    { to: '/doctor', label: 'nav.dashboard' },
    { to: '/doctor/appointments', label: 'nav.appointments' },
    { to: '/doctor/schedule', label: 'nav.mySchedule' },
    { to: '/account', label: 'nav.account' },
  ],
  ADMIN: [
    { to: '/admin', label: 'nav.dashboard' },
    { to: '/admin/doctors', label: 'nav.doctors' },
    { to: '/admin/departments', label: 'nav.departments' },
    { to: '/admin/invitations', label: 'nav.invitations' },
    { to: '/admin/conflicts', label: 'nav.conflicts' },
    { to: '/admin/failed-jobs', label: 'nav.failedJobs' },
    { to: '/admin/audit', label: 'nav.audit' },
    { to: '/account', label: 'nav.account' },
  ],
};

export default function Layout() {
  const { user, logout } = useAuth();
  const t = useT();
  const navigate = useNavigate();

  const links = user ? NAV_BY_ROLE[user.role] : [];

  function handleLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span>Healthcare Manager</span>
          </div>

          {user ? (
            <>
              <nav className="nav" aria-label={t('layout.mainNav')}>
                {links.map((l) => (
                  <NavLink
                    key={l.to}
                    to={l.to}
                    end={l.to.split('/').length <= 2}
                    className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
                  >
                    {t(l.label)}
                  </NavLink>
                ))}
              </nav>
              <div className="topbar-user">
                <span className="user-meta">
                  {user.full_name}
                  <span className="role-tag">{user.role}</span>
                </span>
                <button type="button" className="btn btn-sm" onClick={handleLogout}>
                  {t('layout.logout')}
                </button>
              </div>
            </>
          ) : null}
          <LanguagePicker />
        </div>
      </header>

      <main className="content">
        {user && !user.email_verified ? (
          <InfoBanner>
            {t('layout.unverified')} <Link to="/account">{t('layout.openAccount')}</Link>{' '}
            {t('layout.unverifiedRest')}
          </InfoBanner>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
