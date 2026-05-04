import { useMutation } from '@tanstack/react-query';
import client from '@/api/client';

interface LoginCredentials {
  username: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
}

export function useLoginMutation() {
  return useMutation({
    mutationFn: (creds: LoginCredentials) =>
      client
        .post<LoginResponse>('/auth/login', creds)
        .then((r) => r.data),
  });
}
