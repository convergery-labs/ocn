import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { useDomains } from '@/hooks/useDomains';
import { useLoginMutation } from '@/hooks/useLoginMutation';
import { useRegisterMutation } from '@/hooks/useRegisterMutation';

export default function RegisterPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const { data: domains, isLoading: domainsLoading } = useDomains();
  const registerMutation = useRegisterMutation();
  const loginMutation = useLoginMutation();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [selectedSlugs, setSelectedSlugs] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);

  function toggleSlug(slug: string) {
    setSelectedSlugs((prev) =>
      prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const validationErrors: string[] = [];
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      validationErrors.push('Please enter a valid email address.');
    }
    if (password !== confirmPassword) {
      validationErrors.push('Passwords do not match.');
    }
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }

    setErrors([]);
    try {
      await registerMutation.mutateAsync({
        username,
        email,
        password,
        domain_slugs: selectedSlugs,
      });
      const data = await loginMutation.mutateAsync({ username, password });
      login(data.access_token);
      navigate('/');
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      if (status === 409) {
        setErrors(['Username already taken.']);
      } else {
        setErrors(['Registration failed. Please try again.']);
      }
    }
  }

  const submitting = registerMutation.isPending || loginMutation.isPending;

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <h1 style={styles.heading}>Create account</h1>
        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            <span>Username <span style={styles.required}>*</span></span>
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
            <span>Email <span style={styles.required}>*</span></span>
            <input
              style={styles.input}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label style={styles.label}>
            <span>Password <span style={styles.required}>*</span></span>
            <input
              style={styles.input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <label style={styles.label}>
            <span>Confirm password <span style={styles.required}>*</span></span>
            <input
              style={styles.input}
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <fieldset style={styles.fieldset}>
            <legend style={styles.legend}>Domain preferences</legend>
            {domainsLoading && <p style={styles.hint}>Loading domains…</p>}
            {domains?.map((d) => (
              <label key={d.slug} style={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={selectedSlugs.includes(d.slug)}
                  onChange={() => toggleSlug(d.slug)}
                />
                {d.name}
              </label>
            ))}
          </fieldset>
          {errors.length > 0 && (
            <ul style={styles.errorList}>
              {errors.map((msg) => (
                <li key={msg}>{msg}</li>
              ))}
            </ul>
          )}
          <button style={styles.button} type="submit" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>
        <p style={styles.footer}>
          Already have an account? <Link to="/login">Sign in</Link>
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
  fieldset: {
    border: '1px solid #ccc',
    borderRadius: '4px',
    padding: '0.75rem',
  },
  legend: {
    fontSize: '0.9rem',
    padding: '0 0.25rem',
  },
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.9rem',
    cursor: 'pointer',
    marginBottom: '0.25rem',
  },
  hint: {
    margin: 0,
    fontSize: '0.875rem',
    color: '#666',
  },
  errorList: {
    color: '#c00',
    margin: 0,
    paddingLeft: '1.25rem',
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
  required: {
    color: '#c00',
  },
} as const;
