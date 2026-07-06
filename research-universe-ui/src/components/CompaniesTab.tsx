import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../api/client';
import { safeUrl, catName } from '../utils/url';
import type { Company } from '../types';

const PAGE_SIZE = 50;

const SECTOR_COLORS = ['#c98a2b','#e07b39','#d65745','#d64f7d','#b357c9','#8a5cf0','#5b6ef0','#2f7be0','#2ba6d9','#16a39a','#1f9e84','#3a9e54','#6f9e2e','#6b78a8','#189e6e','#5e7a8f','#b8902a','#2898b0','#7d5ad0'];
const sectorColor = (cat: string) => { let h = 0; for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) >>> 0; return SECTOR_COLORS[h % SECTOR_COLORS.length]; };

const IRefresh  = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6"/></svg>;
const IChev     = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>;
const IClose    = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>;
const IGlobe    = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>;
const ISearch   = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>;

export function CompaniesTab() {
  const [all, setAll] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterCountry, setFilterCountry] = useState('');
  const [page, setPage] = useState(0);
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listCompanies();
      setAll(data);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const categoryOptions = useMemo(() => {
    const set = new Set<string>();
    all.forEach(c => (c.categories ?? []).forEach(cat => set.add(cat)));
    return [...set].sort();
  }, [all]);

  const countryOptions = useMemo(() => {
    const set = new Set<string>();
    all.forEach(c => { if (c.country) set.add(c.country); });
    return [...set].sort();
  }, [all]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter(c => {
      if (q && !c.company_name.toLowerCase().includes(q) && !c.ticker.toLowerCase().includes(q)) return false;
      if (filterStatus && c.status !== filterStatus) return false;
      if (filterCategory && !(c.categories ?? []).includes(filterCategory)) return false;
      if (filterCountry && c.country !== filterCountry) return false;
      return true;
    });
  }, [all, search, filterStatus, filterCategory, filterCountry]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const hasFilters = !!(search || filterStatus || filterCategory || filterCountry);

  useEffect(() => { setPage(0); }, [search, filterStatus, filterCategory, filterCountry]);

  const pagerPages = Array.from({ length: totalPages }, (_, i) => i).filter(i => Math.abs(i - page) <= 2);

  const selectStyle = (active: boolean): React.CSSProperties => ({
    appearance: 'none', WebkitAppearance: 'none',
    height: 40, paddingLeft: 14, paddingRight: 34,
    border: `1px solid ${active ? 'var(--blue-border)' : 'var(--line)'}`,
    borderRadius: 'var(--r-pill)',
    background: active ? 'var(--blue-soft)' : 'var(--surface)',
    color: active ? 'var(--blue)' : 'var(--ink-2)',
    fontSize: 13.5, fontWeight: 600, fontFamily: 'inherit',
    cursor: 'pointer', boxShadow: 'var(--shadow-card)', outline: 'none', minWidth: 140,
  });

  return (
    <div className="view">
      <div className="page-scroll">
        <div className="page">

          {/* Header */}
          <div className="page-head">
            <div>
              <h2>Companies</h2>
              {!loading && (
                <div className="sub">
                  {hasFilters
                    ? `${filtered.length} of ${all.length} companies`
                    : `${all.length} companies total`}
                </div>
              )}
            </div>

            <div className="actions" style={{ flexWrap: 'wrap', gap: 8 }}>
              {/* Search */}
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span style={{ position: 'absolute', left: 12, width: 16, height: 16, color: 'var(--ink-3)', display: 'flex', pointerEvents: 'none' }}><ISearch /></span>
                <input
                  type="text"
                  placeholder="Search name or ticker…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  style={{
                    height: 40, paddingLeft: 36, paddingRight: 14,
                    border: `1px solid ${search ? 'var(--blue-border)' : 'var(--line)'}`,
                    borderRadius: 'var(--r-pill)', background: search ? 'var(--blue-soft)' : 'var(--surface)',
                    color: 'var(--ink)', fontSize: 13.5, fontFamily: 'inherit',
                    outline: 'none', boxShadow: 'var(--shadow-card)', width: 220,
                  }}
                />
              </div>

              {/* Status filter */}
              <div style={{ position: 'relative' }}>
                <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={selectStyle(!!filterStatus)}>
                  <option value="">All Statuses</option>
                  <option value="verified">Verified</option>
                  <option value="pending_review">Pending Review</option>
                </select>
                <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: filterStatus ? 'var(--blue)' : 'var(--ink-3)', display: 'flex' }}><IChev /></span>
              </div>

              {/* Category filter */}
              <div style={{ position: 'relative' }}>
                <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)} style={selectStyle(!!filterCategory)}>
                  <option value="">All Categories</option>
                  {categoryOptions.map(c => <option key={c} value={c}>{catName(c)}</option>)}
                </select>
                <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: filterCategory ? 'var(--blue)' : 'var(--ink-3)', display: 'flex' }}><IChev /></span>
              </div>

              {/* Country filter */}
              <div style={{ position: 'relative' }}>
                <select value={filterCountry} onChange={e => setFilterCountry(e.target.value)} style={selectStyle(!!filterCountry)}>
                  <option value="">All Countries</option>
                  {countryOptions.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: filterCountry ? 'var(--blue)' : 'var(--ink-3)', display: 'flex' }}><IChev /></span>
              </div>

              {hasFilters && (
                <button
                  onClick={() => { setSearch(''); setFilterStatus(''); setFilterCategory(''); setFilterCountry(''); }}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 5, height: 40, padding: '0 14px', border: '1px solid var(--line)', borderRadius: 'var(--r-pill)', background: 'var(--surface)', color: 'var(--ink-3)', fontSize: 13, fontWeight: 600, cursor: 'pointer', boxShadow: 'var(--shadow-card)' }}
                >
                  <span style={{ width: 14, height: 14, display: 'flex' }}><IClose /></span> Clear
                </button>
              )}

              <div style={{ width: 1, height: 24, background: 'var(--line)', alignSelf: 'center' }} />
              <button className="btn" onClick={load} disabled={loading}><IRefresh /> Refresh</button>
            </div>
          </div>

          {/* Table */}
          {loading ? (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)' }}>
                    {['Company', 'Ticker', 'Country', 'Category', 'Status'].map(h => (
                      <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 12, fontWeight: 700, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[1,2,3,4,5,6,7,8].map(i => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                      {[180, 70, 100, 160, 80].map((w, j) => (
                        <td key={j} style={{ padding: '12px 14px' }}>
                          <div style={{ height: 14, width: w, borderRadius: 6, background: 'var(--line-soft)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '40vh', textAlign: 'center' }}>
              <div style={{ width: 64, height: 64, borderRadius: 16, background: 'var(--blue-soft)', display: 'grid', placeItems: 'center', fontSize: 28, marginBottom: 16 }}>🔍</div>
              <p style={{ fontWeight: 600, color: 'var(--ink)', margin: 0 }}>No matches</p>
              <p style={{ color: 'var(--ink-4)', fontSize: 14, marginTop: 6 }}>Try adjusting your filters.</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto', borderRadius: 12, border: '1px solid var(--line)', boxShadow: 'var(--shadow-card)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)', background: 'var(--surface-2)' }}>
                    {['Company', 'Ticker', 'Country', 'Category', 'Status'].map(h => (
                      <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11.5, fontWeight: 700, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paginated.map((c, idx) => {
                    const primaryCat = (c.categories ?? [])[0] ?? '';
                    const url = safeUrl(c.website);
                    const isEven = idx % 2 === 0;
                    return (
                      <tr
                        key={c.id}
                        onClick={() => setSelectedCompany(c)}
                        style={{ borderBottom: '1px solid var(--line-soft)', background: isEven ? 'var(--surface)' : 'var(--surface-2)', cursor: 'pointer', transition: 'background 0.12s' }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'var(--blue-soft)')}
                        onMouseLeave={e => (e.currentTarget.style.background = isEven ? 'var(--surface)' : 'var(--surface-2)')}
                      >
                        <td style={{ padding: '11px 14px', fontWeight: 600, color: 'var(--ink)', fontSize: 13.5 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ width: 8, height: 8, borderRadius: '50%', background: sectorColor(primaryCat), flexShrink: 0 }} />
                            {c.company_name}
                            {url && (
                              <a href={url} target="_blank" rel="noreferrer noopener"
                                onClick={e => e.stopPropagation()}
                                style={{ color: 'var(--ink-3)', display: 'flex', width: 14, height: 14, flexShrink: 0 }}>
                                <IGlobe />
                              </a>
                            )}
                          </div>
                        </td>
                        <td style={{ padding: '11px 14px', fontSize: 12.5, fontFamily: 'monospace', color: c.ticker === 'Private' ? 'var(--ink-3)' : 'var(--ink-2)', fontWeight: 600 }}>
                          {c.ticker || '—'}
                        </td>
                        <td style={{ padding: '11px 14px', fontSize: 13, color: 'var(--ink-2)' }}>{c.country || '—'}</td>
                        <td style={{ padding: '11px 14px', fontSize: 12.5, color: 'var(--ink-2)', maxWidth: 220 }}>
                          <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 6, fontSize: 11.5, fontWeight: 600, background: sectorColor(primaryCat) + '22', color: sectorColor(primaryCat), whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 200 }}>
                            {catName(primaryCat) || '—'}
                          </span>
                        </td>
                        <td style={{ padding: '11px 14px' }}>
                          <span style={{
                            display: 'inline-block', padding: '3px 10px', borderRadius: 20, fontSize: 11.5, fontWeight: 700,
                            background: c.status === 'verified' ? '#dcfce7' : '#fffbeb',
                            color: c.status === 'verified' ? '#15803d' : '#b45309',
                          }}>
                            {c.status === 'verified' ? 'Verified' : 'Pending'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {!loading && totalPages > 1 && (
            <div className="pager">
              <span className="info">Page {page + 1} of {totalPages} · {PAGE_SIZE} per page</span>
              <button className="pg" disabled={page === 0} onClick={() => setPage(0)}>«</button>
              <button className="pg" disabled={page === 0} onClick={() => setPage(p => p - 1)}>‹ Prev</button>
              {pagerPages.map(i => (
                <button key={i} className={`pg${i === page ? ' active' : ''}`} onClick={() => setPage(i)}>{i + 1}</button>
              ))}
              <button className="pg" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>Next ›</button>
              <button className="pg" disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)}>»</button>
            </div>
          )}
        </div>
      </div>

      {/* Detail drawer */}
      {selectedCompany && (
        <CompanyDrawer company={selectedCompany} onClose={() => setSelectedCompany(null)} />
      )}

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}`}</style>
    </div>
  );
}

function CompanyDrawer({ company: c, onClose }: { company: Company; onClose: () => void }) {
  const primaryCat = (c.categories ?? [])[0] ?? '';
  const url = safeUrl(c.website);

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, [onClose]);

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 40, animation: 'fadeIn .15s ease-out' }} />
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 420, background: 'var(--surface)',
        boxShadow: '-4px 0 32px rgba(0,0,0,0.15)', zIndex: 50, overflowY: 'auto',
        animation: 'slideIn .2s ease-out', display: 'flex', flexDirection: 'column',
      }}>
        {/* Drawer header */}
        <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid var(--line)', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: sectorColor(primaryCat), flexShrink: 0, marginTop: 6 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: 'var(--ink)', lineHeight: 1.3 }}>{c.company_name}</h3>
            <span style={{ fontSize: 12.5, fontFamily: 'monospace', fontWeight: 600, color: 'var(--ink-3)' }}>{c.ticker || '—'}</span>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink-3)', padding: 4, display: 'flex', borderRadius: 6 }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 18, height: 18 }}><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>

        {/* Drawer body */}
        <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Status badge */}
          <span style={{
            alignSelf: 'flex-start', padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 700,
            background: c.status === 'verified' ? '#dcfce7' : '#fffbeb',
            color: c.status === 'verified' ? '#15803d' : '#b45309',
          }}>
            {c.status === 'verified' ? 'Verified' : 'Pending Review'}
          </span>

          {/* Fields */}
          {[
            { label: 'Country', value: c.country },
            { label: 'Market', value: c.market },
            { label: 'Category', value: (c.categories ?? []).map(catName).join(', ') },
            { label: 'Subcategory', value: (c.subcategories ?? []).join(', ') },
            { label: 'Added by', value: c.added_by },
            { label: 'Added at', value: c.added_at ? new Date(c.added_at).toLocaleDateString() : null },
            { label: 'Verified by', value: c.verified_by },
            { label: 'Verified at', value: c.verified_at ? new Date(c.verified_at).toLocaleDateString() : null },
          ].filter(f => f.value).map(({ label, value }) => (
            <div key={label}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-3)', marginBottom: 3 }}>{label}</div>
              <div style={{ fontSize: 13.5, color: 'var(--ink)', fontWeight: 500 }}>{value}</div>
            </div>
          ))}

          {c.multi_category_reason && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-3)', marginBottom: 3 }}>Multi-category reason</div>
              <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.5, background: 'var(--surface-2)', padding: '10px 12px', borderRadius: 8 }}>{c.multi_category_reason}</div>
            </div>
          )}

          {url && (
            <a href={url} target="_blank" rel="noreferrer noopener" className="btn" style={{ alignSelf: 'flex-start', textDecoration: 'none' }}>
              <IGlobe /> Visit Website
            </a>
          )}
        </div>
      </div>
      <style>{`
        @keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes slideIn { from { transform: translateX(100%) } to { transform: translateX(0) } }
      `}</style>
    </>
  );
}
