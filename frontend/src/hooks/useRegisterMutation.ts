import { useMutation } from '@tanstack/react-query';
import client from '@/api/client';

interface RegisterPayload {
  username: string;
  email: string;
  password: string;
  domain_slugs: string[];
}

export function useRegisterMutation() {
  return useMutation({
    mutationFn: (payload: RegisterPayload) =>
      client.post('/auth/register', payload).then((r) => r.data),
  });
}
