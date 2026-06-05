import { useState } from 'react';
import { api } from '../api/client';
import { LOGIN_CARD_SHADOW } from '../theme';
import { TEXT, LABEL_STYLE } from '../tokens';


interface LoginScreenProps {
  onLogin: (sessionToken: string) => void;
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const { session_token } = await api.login(email, password);
      onLogin(session_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-transparent flex items-center justify-center p-4">
      <div className="w-full max-w-md" style={{ marginTop: '-5vh' }}>
        {/* Brand */}
        <div className="flex flex-col items-center text-center mb-10">
          <h1 style={{
            fontSize: 30, fontWeight: 800, letterSpacing: '-0.8px',
            margin: '0 0 10px', lineHeight: 1.1, color: 'var(--ink)',
            whiteSpace: 'nowrap',
          }}>
            AI Economy <span style={{
              background: 'linear-gradient(120deg, var(--blue-bright), var(--blue-deep))',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>Universe</span>
          </h1>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl border border-slate-200 px-9 py-8" style={{ boxShadow: LOGIN_CARD_SHADOW }}>
          <div className="text-center mb-7">
            <h2 className="text-slate-900 text-xl font-bold tracking-tight">Sign in</h2>
            <p className="text-slate-500 text-sm mt-1">Enter your credentials to continue</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="text-slate-600 text-xs block mb-1.5 font-semibold uppercase tracking-wide">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoFocus
                autoComplete="email"
                placeholder="you@example.com"
                className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-sm rounded-xl px-4 py-3 focus:outline-none focus:border-brand-400 focus:bg-white focus:shadow-input-focus transition-all placeholder-slate-400"
              />
            </div>

            <div>
              <label className="text-slate-600 text-xs block mb-1.5 font-semibold uppercase tracking-wide">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-sm rounded-xl px-4 py-3 pr-14 focus:outline-none focus:border-brand-400 focus:bg-white focus:shadow-input-focus transition-all placeholder-slate-400"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(s => !s)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-brand-600 transition-colors text-xs font-semibold"
                >
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
            </div>

            {error && (
              <p className="text-rose-600 text-xs bg-rose-50 border border-rose-200 rounded-xl px-4 py-2.5">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-brand-500 hover:bg-brand-600 active:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl py-3 transition-colors shadow-btn hover:shadow-btn-hover hover:-translate-y-0.5 active:translate-y-0 mt-1"
            >
              {loading
                ? <span className="flex items-center justify-center gap-2">
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Signing in…
                  </span>
                : 'Sign in'
              }
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
