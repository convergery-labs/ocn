import { useQuery } from '@tanstack/react-query';
import client from '@/api/client';

export interface Domain {
  id: number;
  name: string;
  slug: string;
  description: string | null;
}

export function useDomains() {
  return useQuery({
    queryKey: ['domains'],
    queryFn: () =>
      client.get<Domain[]>('/api/news/domains').then((r) => r.data),
  });
}
