import { useRef, useState } from 'react';
import type { Article } from '@/hooks/useArticles';

interface Props {
  article: Article;
}

export default function ArticleCard({ article }: Props) {
  const [showTooltip, setShowTooltip] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleMouseEnter() {
    timerRef.current = setTimeout(() => setShowTooltip(true), 300);
  }

  function handleMouseLeave() {
    if (timerRef.current) clearTimeout(timerRef.current);
    setShowTooltip(false);
  }

  const published = article.published
    ? new Date(article.published).toLocaleDateString()
    : '';

  return (
    <div
      style={{ position: 'relative', border: '1px solid #e2e8f0', borderRadius: 8, padding: 16, background: '#fff', cursor: 'default' }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <a
        href={article.url}
        target="_blank"
        rel="noopener noreferrer"
        style={{ fontWeight: 600, fontSize: 15, color: '#1a202c', textDecoration: 'none', display: 'block', marginBottom: 6 }}
      >
        {article.title}
      </a>
      <div style={{ fontSize: 13, color: '#718096' }}>
        {article.source}
        {published && <span> · {published}</span>}
      </div>
      {showTooltip && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 10,
            background: '#2d3748',
            color: '#e2e8f0',
            padding: '10px 14px',
            borderRadius: 6,
            fontSize: 13,
            lineHeight: 1.5,
            marginTop: 4,
            boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
          }}
        >
          {article.summary ?? 'No summary available.'}
        </div>
      )}
    </div>
  );
}
