import {
  createContext,
  useContext,
  useReducer,
  ReactNode,
} from 'react';

const TOKEN_KEY = 'ocn_token';

interface JwtPayload {
  sub: string;
  username: string;
  role: string;
  domains: string[];
  exp: number;
}

interface User {
  id: string;
  username: string;
  role: string;
  domains: string[];
}

interface AuthState {
  user: User | null;
  token: string | null;
}

type AuthAction =
  | { type: 'LOGIN'; token: string; user: User }
  | { type: 'LOGOUT' };

interface AuthContextValue extends AuthState {
  login: (token: string) => void;
  logout: () => void;
}

function decodeToken(token: string): User | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1])) as JwtPayload;
    return {
      id: payload.sub,
      username: payload.username,
      role: payload.role,
      domains: payload.domains,
    };
  } catch {
    return null;
  }
}

function authReducer(_state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'LOGIN':
      return { user: action.user, token: action.token };
    case 'LOGOUT':
      return { user: null, token: null };
  }
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, undefined, () => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) {
      const user = decodeToken(stored);
      if (user) return { user, token: stored };
      localStorage.removeItem(TOKEN_KEY);
    }
    return { user: null, token: null };
  });

  function login(token: string) {
    const user = decodeToken(token);
    if (!user) return;
    localStorage.setItem(TOKEN_KEY, token);
    dispatch({ type: 'LOGIN', token, user });
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    dispatch({ type: 'LOGOUT' });
  }

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
