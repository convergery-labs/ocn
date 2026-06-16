import { fetchEventSource } from '@microsoft/fetch-event-source';
import type { Category, ChatDoneEvent, ChatThinkingEvent, Company, ScheduleSummary, ScanJob, User } from '../types';

const API_BASE_KEY = 'ru_api_base';
const API_KEY_KEY = 'ru_api_key';

export const clearAuth = () => localStorage.removeItem(API_KEY_KEY);

const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8007';

export const getApiBase = () =>
  localStorage.getItem(API_BASE_KEY) ?? DEFAULT_API_BASE;

export const setApiBase = (url: string) =>
  localStorage.setItem(API_BASE_KEY, url.replace(/\/$/, ''));

export const getApiKey = () => localStorage.getItem(API_KEY_KEY) ?? '';

export const setApiKey = (key: string) =>
  localStorage.setItem(API_KEY_KEY, key);

type SessionExpiredHandler = () => void;
let onSessionExpired: SessionExpiredHandler | null = null;
export const setSessionExpiredHandler = (fn: SessionExpiredHandler) => { onSessionExpired = fn; };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const key = getApiKey();
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: string }).detail ?? `HTTP ${res.status}`;
    if (res.status === 401) {
      clearAuth();
      onSessionExpired?.();
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    fetch(`${getApiBase()}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }).then(async res => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      return res.json() as Promise<{ session_token: string; user: User }>;
    }),

  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  setPassword: (userId: string, password: string) =>
    request<void>(`/users/${userId}/set-password`, {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),

  me: () => request<User>('/users/me'),

  chat: (
    message: string,
    conversationId: string | undefined,
    onThinking: (evt: ChatThinkingEvent) => void,
    signal?: AbortSignal,
  ): Promise<ChatDoneEvent> => {
    const key = getApiKey();
    return new Promise((resolve, reject) => {
      fetchEventSource(`${getApiBase()}/chat`, {
        method: 'POST',
        signal,
        headers: {
          'Content-Type': 'application/json',
          ...(key ? { Authorization: `Bearer ${key}` } : {}),
        },
        body: JSON.stringify({ message, conversation_id: conversationId }),
        onopen: async (res) => {
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            const detail = (body as { detail?: string }).detail ?? `HTTP ${res.status}`;
            if (res.status === 401) { clearAuth(); onSessionExpired?.(); }
            throw new Error(detail);
          }
        },
        onmessage: (ev) => {
          const data = JSON.parse(ev.data);
          if (ev.event === 'thinking') onThinking(data as ChatThinkingEvent);
          if (ev.event === 'error')    reject(new Error((data as { message: string }).message));
          if (ev.event === 'done')     resolve(data as ChatDoneEvent);
        },
        onerror: (err) => {
          reject(err);
          throw err; // stops fetchEventSource from retrying
        },
      });
    });
  },

  stats: () => request<{ total: number; verified: number; pending: number }>('/companies/stats'),

  pending: (limit = 50, offset = 0) =>
    request<Company[]>(`/companies/pending?limit=${limit}&offset=${offset}`),

  verify: (id: string) =>
    request<Company>(`/companies/${id}/verify`, {
      method: 'POST',
      body: '{}',
    }),

  categories: () => request<Category[]>('/taxonomy/categories'),

  startScan: (categories: number[]) =>
    request<{ job_id: string; status: string }>('/jobs/scan', {
      method: 'POST',
      body: JSON.stringify({ categories }),
    }),

  pollScan: (jobId: string) => request<ScanJob>(`/jobs/scan/${jobId}`),

  schedule: () => request<ScheduleSummary>('/jobs/schedule'),
};
