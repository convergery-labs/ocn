import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { useLoginMutation } from '@/hooks/useLoginMutation';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const loginMutation = useLoginMutation();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      const data = await loginMutation.mutateAsync({ username, password });
      login(data.access_token);
      navigate('/');
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      if (status === 401) {
        setError('Invalid username or password.');
      } else {
        setError('Something went wrong. Please try again.');
      }
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <h1 style={styles.heading}>Sign in</h1>
        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Username
            <input
              style={styles.input}
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label style={styles.label}>
            Password
            <input
              style={styles.input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && <p style={styles.error}>{error}</p>}
          <button
            style={styles.button}
            type="submit"
            disabled={loginMutation.isPending}
          >
            {loginMutation.isPending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p style={styles.footer}>
          No account? <Link to="/register">Create one</Link>
        </p>
      </div>
    </div>
  );
}

const styles = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '1rem',
  },
  card: {
    width: '100%',
    maxWidth: '400px',
  },
  heading: {
    marginBottom: '1.5rem',
  },
  form: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '1rem',
  },
  label: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.25rem',
    fontSize: '0.9rem',
  },
  input: {
    padding: '0.5rem',
    fontSize: '1rem',
    border: '1px solid #ccc',
    borderRadius: '4px',
    width: '100%',
    boxSizing: 'border-box' as const,
  },
  error: {
    color: '#c00',
    margin: 0,
    fontSize: '0.875rem',
  },
  button: {
    padding: '0.6rem',
    fontSize: '1rem',
    cursor: 'pointer',
  },
  footer: {
    marginTop: '1rem',
    fontSize: '0.875rem',
  },
} as const;
