import { useState, useEffect, useCallback } from 'react';
import { api, getApiKey, setApiKey, clearAuth, setSessionExpiredHandler } from './api/client';
import { LoginScreen } from './components/LoginScreen';
import { Sidebar } from './components/Sidebar';
import { ChatTab } from './components/ChatTab';
import { PendingTab } from './components/PendingTab';
import { DiscoveryTab } from './components/DiscoveryTab';
import type { Tab, User } from './types';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('chat');
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const [apiKey, setApiKeyState] = useState(getApiKey());
  const [authStatus, setAuthStatus] = useState<'idle' | 'ok' | 'error' | 'unreachable'>('idle');
  const [checking, setChecking] = useState(() => !!getApiKey());

  const refreshPendingCount = useCallback(async () => {
    try { const s = await api.stats(); setPendingCount(s.pending); } catch {}
  }, []);

  const verifyApiKey = useCallback(async (key: string) => {
    if (!key) { setCurrentUser(null); setAuthStatus('idle'); return; }
    try {
      const user = await api.me();
      setCurrentUser(user);
      setAuthStatus('ok');
      refreshPendingCount();
    } catch (e) {
      setCurrentUser(null);
      const msg = e instanceof Error ? e.message : '';
      setAuthStatus(msg.startsWith('HTTP') ? 'error' : 'unreachable');
    }
  }, [refreshPendingCount]);

  const handleLogin = (sessionToken: string) => {
    setApiKeyState(sessionToken);
    setApiKey(sessionToken);
    verifyApiKey(sessionToken);
  };

  const handleLogout = async () => {
    try { await api.logout(); } catch {}
    clearAuth();
    setCurrentUser(null);
    setApiKeyState('');
    setAuthStatus('idle');
  };

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setCurrentUser(null); setApiKeyState(''); setAuthStatus('idle');
    });
  }, []);

  useEffect(() => {
    const saved = getApiKey();
    if (saved) { verifyApiKey(saved).finally(() => setChecking(false)); }
    else { setChecking(false); }
  }, [verifyApiKey]);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    if (tab === 'pending') refreshPendingCount();
  };

  if (checking) return null;

  if (authStatus !== 'ok' && !currentUser) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return (
    <div className="app">
      <Sidebar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        currentUser={currentUser}
        authStatus={authStatus}
        onLogout={handleLogout}
      />
      <main className="main">
        {activeTab === 'chat' && (
          <ChatTab onPendingCountChange={setPendingCount} onNavigateToPending={() => handleTabChange('pending')} />
        )}
        {activeTab === 'pending' && <PendingTab onPendingCountChange={setPendingCount} />}
        {activeTab === 'discovery' && <DiscoveryTab onPendingCountChange={setPendingCount} />}
      </main>
    </div>
  );
}
