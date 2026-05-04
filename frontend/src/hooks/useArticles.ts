import { useInfiniteQuery } from '@tanstack/react-query';
import client from '@/api/client';

export interface Article {
  id: number;
  run_id: number;
  url: string;
  title: string;
  summary: string | null;
  source: string;
  published: string;
  domain?: string;
}

interface ArticlesPage {
  articles: Article[];
  next_cursor: string | null;
}

interface Params {
  domains: string[];
  fromDate: string;
  toDate: string;
}

export function useArticles({ domains, fromDate, toDate }: Params) {
  return useInfiniteQuery({
    queryKey: ['articles', { domains, fromDate, toDate }],
    queryFn: ({ pageParam }) =>
      client
        .get<ArticlesPage>('/news/articles', {
          params: {
            limit: 20,
            ...(domains.length > 0 && { domain: domains }),
            ...(fromDate && { from_date: fromDate }),
            ...(toDate && { to_date: toDate }),
            ...(pageParam ? { cursor: pageParam } : {}),
          },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}
