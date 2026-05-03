import { useEffect, useRef, useState } from 'react';
import { useDomains } from '@/hooks/useDomains';
import { useArticles } from '@/hooks/useArticles';
import ArticleGrid from '@/components/ArticleGrid';

export default function ArticleGridPage() {
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [selectedDomains, setSelectedDomains] = useState<string[]>([]);
  const [titleQuery, setTitleQuery] = useState('');
  const [debouncedTitle, setDebouncedTitle] = useState('');

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedTitle(titleQuery), 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [titleQuery]);

  const { data: domains } = useDomains();

  function toggleDomain(slug: string) {
    setSelectedDomains((prev) =>
      prev.includes(slug) ? prev.filter((d) => d !== slug) : [...prev, slug]
    );
  }

  function toggleAll() {
    setSelectedDomains([]);
  }

  const allSelected = selectedDomains.length === 0;

  const {
    data,
    isLoading,
    isError,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useArticles({ domains: selectedDomains, fromDate, toDate });

  const allArticles = (data?.pages ?? []).flatMap((p) => p.articles);

  const filtered = debouncedTitle
    ? allArticles.filter((a) =>
        a.title.toLowerCase().includes(debouncedTitle.toLowerCase())
      )
    : allArticles;

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 24, color: '#1a202c' }}>
        Articles
      </h1>

      <div
        style={{
          background: '#f7fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: 16,
          marginBottom: 24,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 16,
          alignItems: 'flex-start',
        }}
      >
        <div>
          <label style={labelStyle}>From</label>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>To</label>
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Search</label>
          <input
            type="text"
            placeholder="Filter by title…"
            value={titleQuery}
            onChange={(e) => setTitleQuery(e.target.value)}
            style={{ ...inputStyle, minWidth: 200 }}
          />
        </div>
        {domains && domains.length > 0 && (
          <div>
            <label style={labelStyle}>Domains</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
              <label style={checkboxLabelStyle}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                />
                <span>All</span>
              </label>
              {domains.map((d) => (
                <label key={d.slug} style={checkboxLabelStyle}>
                  <input
                    type="checkbox"
                    checked={selectedDomains.includes(d.slug)}
                    onChange={() => toggleDomain(d.slug)}
                  />
                  <span>{d.name}</span>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>

      <ArticleGrid
        articles={filtered}
        isLoading={isLoading}
        isError={isError}
        hasNextPage={!!hasNextPage && !debouncedTitle}
        isFetchingNextPage={isFetchingNextPage}
        onLoadMore={fetchNextPage}
      />
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  fontWeight: 600,
  color: '#4a5568',
  marginBottom: 4,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const inputStyle: React.CSSProperties = {
  padding: '6px 10px',
  border: '1px solid #cbd5e0',
  borderRadius: 6,
  fontSize: 14,
  color: '#2d3748',
  background: '#fff',
};

const checkboxLabelStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
  fontSize: 13,
  cursor: 'pointer',
  color: '#2d3748',
};
