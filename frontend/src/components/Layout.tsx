import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { InfoBanner } from './ui';
import type { UserRole } from '../api/types';

const NAV_BY_ROLE: Record<UserRole, { to: string; label: string }[]> = {
  PATIENT: [
    { to: '/patient', label: 'Dashboard' },
    { to: '/patient/doctors', label: 'Find a doctor' },
    { to: '/patient/appointments', label: 'My appointments' },
    { to: '/account', label: 'Account' },
  ],
  DOCTOR: [
    { to: '/doctor', label: 'Dashboard' },
    { to: '/doctor/appointments', label: 'Appointments' },
    { to: '/account', label: 'Account' },
  ],
  ADMIN: [
    { to: '/admin', label: 'Dashboard' },
    { to: '/admin/doctors', label: 'Doctors' },
    { to: '/admin/conflicts', label: 'Conflicted appointments' },
    { to: '/admin/audit', label: 'Audit log' },
    { to: '/account', label: 'Account' },
  ],
};

export default function Layout() {
  const { user, logout } = useAuth();
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
              <nav className="nav" aria-label="Main">
                {links.map((l) => (
                  <NavLink
                    key={l.to}
                    to={l.to}
                    end={l.to.split('/').length <= 2}
                    className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
                  >
                    {l.label}
                  </NavLink>
                ))}
              </nav>
              <div className="topbar-user">
                <span className="user-meta">
                  {user.full_name}
                  <span className="role-tag">{user.role}</span>
                </span>
                <button type="button" className="btn btn-sm" onClick={handleLogout}>
                  Log out
                </button>
              </div>
            </>
          ) : null}
        </div>
      </header>

      <main className="content">
        {user && !user.email_verified ? (
          <InfoBanner>
            Your email address is not verified yet. <Link to="/account">Open your account</Link> to
            send the confirmation link again.
          </InfoBanner>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
