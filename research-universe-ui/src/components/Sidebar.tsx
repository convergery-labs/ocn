import { useRef, useEffect, useState } from 'react';
import type { Tab, User } from '../types';

interface SidebarProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  currentUser: User | null;

  authStatus: 'idle' | 'ok' | 'error' | 'unreachable';
  onLogout: () => void;
}





const IconLogout = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>
  </svg>
);

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'chat',      label: 'Chat' },
  { id: 'pending',   label: 'Pending Review' },
  { id: 'discovery', label: 'Discovery' },
];

function Account({ currentUser, authStatus, onLogout }: {
  currentUser: User | null; authStatus: string; onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', k);
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k); };
  }, [open]);

  const initial = currentUser?.email?.[0]?.toUpperCase() ?? 'U';

  return (
    <div className="account-pill" ref={ref}>
      <button className={`avatar-btn${open ? ' open' : ''}`} onClick={() => setOpen(o => !o)} aria-label="Account" style={{ position: 'relative' }}>
        <span className="avatar">{initial}</span>
        <span className="conn-dot" />
      </button>

      {open && (
        <div className="acct-menu">
          <div className="acct-head">
            <span className="avatar lg">{initial}</span>
            <div>
              <div className="acct-email">{currentUser?.email ?? '—'}</div>
              <div className="acct-conn">{authStatus === 'ok' ? 'Connected' : 'Disconnected'}</div>
            </div>
          </div>
          <div className="acct-div" />
          <button className="acct-row danger" onClick={() => { setOpen(false); onLogout(); }}>
            <IconLogout /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function Sidebar({ activeTab, onTabChange, currentUser, authStatus, onLogout }: SidebarProps) {
  return (
    <header className="topbar">
      <div className="nav-pill">
        <div className="brand">
          <div className="word">AI ECONOMY UNIVERSE</div>
        </div>
        <div className="nav-divider" />
        <nav className="nav">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              className={`nav-tab${activeTab === id ? ' active' : ''}`}
              onClick={() => onTabChange(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>
      <Account currentUser={currentUser} authStatus={authStatus} onLogout={onLogout} />
    </header>
  );
}
