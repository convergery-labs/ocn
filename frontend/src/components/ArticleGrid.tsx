import type { Article } from '@/hooks/useArticles';
import ArticleCard from './ArticleCard';

interface Props {
  articles: Article[];
  isLoading: boolean;
  isError: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}

export default function ArticleGrid({
  articles,
  isLoading,
  isError,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: Props) {
  if (isLoading) {
    return <div style={{ padding: 32, textAlign: 'center', color: '#718096' }}>Loading…</div>;
  }

  if (isError) {
    return <div style={{ padding: 32, textAlign: 'center', color: '#e53e3e' }}>Failed to load articles.</div>;
  }

  if (articles.length === 0) {
    return <div style={{ padding: 32, textAlign: 'center', color: '#718096' }}>No articles found.</div>;
  }

  return (
    <div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: 16,
        }}
      >
        {articles.map((a) => (
          <ArticleCard key={a.id} article={a} />
        ))}
      </div>
      {hasNextPage && (
        <div style={{ textAlign: 'center', marginTop: 24 }}>
          <button
            onClick={onLoadMore}
            disabled={isFetchingNextPage}
            style={{
              padding: '10px 28px',
              background: '#4a5568',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              fontSize: 14,
              cursor: isFetchingNextPage ? 'not-allowed' : 'pointer',
              opacity: isFetchingNextPage ? 0.6 : 1,
            }}
          >
            {isFetchingNextPage ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
}
