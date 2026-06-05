import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../api/client';
import { safeUrl, catName } from '../utils/url';
import type { Company } from '../types';

const PAGE_SIZE = 50;

const SECTOR_COLORS = ['#c98a2b','#e07b39','#d65745','#d64f7d','#b357c9','#8a5cf0','#5b6ef0','#2f7be0','#2ba6d9','#16a39a','#1f9e84','#3a9e54','#6f9e2e','#6b78a8','#189e6e','#5e7a8f','#b8902a','#2898b0','#7d5ad0'];
const sectorColor = (cat: string) => { const m = /^(\d+)/.exec(cat || ''); const i = m ? parseInt(m[1],10)-1 : 0; return SECTOR_COLORS[i] ?? SECTOR_COLORS[0]; };

const ICheck   = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>;
const IGlobe   = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>;
const IRefresh = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6"/></svg>;
const IChev    = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>;
const IClose   = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>;

interface PendingTabProps { onPendingCountChange: (count: number) => void; }

export function PendingTab({ onPendingCountChange }: PendingTabProps) {
  // All companies loaded at once for client-side filtering
  const [all, setAll] = useState<Company[]>([]);
  const [allCategories, setAllCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvingAll, setApprovingAll] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [approved, setApproved] = useState<Record<string, boolean>>({});
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // Filters
  const [filterCategory, setFilterCategory] = useState('');
  const [filterCountry, setFilterCountry] = useState('');
  const [page, setPage] = useState(0);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [data, stats, cats] = await Promise.all([
        api.pending(5000, 0),
        api.stats(),
        api.categories(),
      ]);
      setAll(data);
      setAllCategories(cats.map(c => c.name));
      onPendingCountChange(stats.pending);
    } catch { showToast('Failed to load', false); }
    finally { setLoading(false); }
  }, [onPendingCountChange]);

  useEffect(() => { load(); }, [load]);

  // Derive unique filter options from all companies
  const categoryOptions = allCategories;

  const countryOptions = useMemo(() => {
    const set = new Set<string>();
    all.forEach(c => { if (c.country) set.add(c.country); });
    return [...set].sort();
  }, [all]);

  // Apply filters
  const filtered = useMemo(() => {
    return all.filter(c => {
      if (filterCategory && !(c.categories ?? []).includes(filterCategory)) return false;
      if (filterCountry && c.country !== filterCountry) return false;
      return true;
    });
  }, [all, filterCategory, filterCountry]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const hasFilters = !!(filterCategory || filterCountry);

  // Reset to page 0 when filters change
  useEffect(() => { setPage(0); }, [filterCategory, filterCountry]);

  const verifyOne = async (id: string) => {
    setApprovingId(id);
    try {
      await api.verify(id);
      setApproved(prev => ({ ...prev, [id]: true }));
      setTimeout(() => {
        setAll(prev => prev.filter(c => c.id !== id));
        onPendingCountChange(all.filter(c => c.id !== id).length);
        setApproved(prev => { const n = {...prev}; delete n[id]; return n; });
      }, 400);
      showToast('Company approved');
    } catch { showToast('Failed to approve', false); }
    finally { setApprovingId(null); }
  };

  const verifyAll = async () => {
    const toApprove = paginated.filter(c => !approved[c.id]);
    if (!window.confirm(`Approve ${toApprove.length} ${hasFilters ? 'filtered ' : ''}companies?`)) return;
    setApprovingAll(true);
    const ids = new Set(toApprove.map(c => c.id));
    let done = 0;
    for (const c of toApprove) {
      try { await api.verify(c.id); done++; setApproved(prev => ({ ...prev, [c.id]: true })); } catch {}
    }
    setTimeout(() => {
      setAll(prev => prev.filter(c => !ids.has(c.id)));
      onPendingCountChange(all.filter(c => !ids.has(c.id)).length);
      setApprovingAll(false);
      showToast(`${done} of ${toApprove.length} approved`);
    }, 500);
  };

  const pagerPages = Array.from({ length: totalPages }, (_, i) => i).filter(i => Math.abs(i - page) <= 2);

  return (
    <div className="view">
      <div className="page-scroll">
        <div className="page">

          {/* Header */}
          <div className="page-head">
            <div>
              <h2>Pending Review</h2>
              {!loading && (
                <div className="sub">
                  {hasFilters
                    ? `${filtered.length} of ${all.length} entries (filtered)`
                    : `${all.length} ${all.length === 1 ? 'entry' : 'entries'} awaiting review`}
                </div>
              )}
            </div>

            {/* All controls on the right */}
            <div className="actions" style={{ flexWrap: 'wrap', gap: 8 }}>
              {/* Category filter */}
              <div style={{ position: 'relative' }}>
                <select
                  value={filterCategory}
                  onChange={e => setFilterCategory(e.target.value)}
                  style={{
                    appearance: 'none', WebkitAppearance: 'none',
                    height: 40, paddingLeft: 14, paddingRight: 34,
                    border: `1px solid ${filterCategory ? 'var(--blue-border)' : 'var(--line)'}`,
                    borderRadius: 'var(--r-pill)', background: filterCategory ? 'var(--blue-soft)' : 'var(--surface)',
                    color: filterCategory ? 'var(--blue)' : 'var(--ink-2)',
                    fontSize: 13.5, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
                    boxShadow: 'var(--shadow-card)', outline: 'none', minWidth: 150,
                  }}
                >
                  <option value="">All Categories</option>
                  {categoryOptions.map(c => (
                    <option key={c} value={c}>{catName(c)}</option>
                  ))}
                </select>
                <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: filterCategory ? 'var(--blue)' : 'var(--ink-3)', display: 'flex' }}>
                  <IChev />
                </span>
              </div>

              {/* Country filter */}
              <div style={{ position: 'relative' }}>
                <select
                  value={filterCountry}
                  onChange={e => setFilterCountry(e.target.value)}
                  style={{
                    appearance: 'none', WebkitAppearance: 'none',
                    height: 40, paddingLeft: 14, paddingRight: 34,
                    border: `1px solid ${filterCountry ? 'var(--blue-border)' : 'var(--line)'}`,
                    borderRadius: 'var(--r-pill)', background: filterCountry ? 'var(--blue-soft)' : 'var(--surface)',
                    color: filterCountry ? 'var(--blue)' : 'var(--ink-2)',
                    fontSize: 13.5, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
                    boxShadow: 'var(--shadow-card)', outline: 'none', minWidth: 140,
                  }}
                >
                  <option value="">All Countries</option>
                  {countryOptions.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: filterCountry ? 'var(--blue)' : 'var(--ink-3)', display: 'flex' }}>
                  <IChev />
                </span>
              </div>

              {/* Clear */}
              {hasFilters && (
                <button
                  onClick={() => { setFilterCategory(''); setFilterCountry(''); }}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5, height: 40, padding: '0 14px',
                    border: '1px solid var(--line)', borderRadius: 'var(--r-pill)',
                    background: 'var(--surface)', color: 'var(--ink-3)', fontSize: 13, fontWeight: 600,
                    cursor: 'pointer', boxShadow: 'var(--shadow-card)',
                  }}
                >
                  <span style={{ width: 14, height: 14, display: 'flex' }}><IClose /></span> Clear
                </button>
              )}

              <div style={{ width: 1, height: 24, background: 'var(--line)', alignSelf: 'center' }} />

              <button className="btn" onClick={load} disabled={loading}><IRefresh /> Refresh</button>
              {paginated.length > 0 && (
                <button className="btn btn-primary" onClick={verifyAll} disabled={approvingAll || loading}>
                  <span className="chk"><ICheck /></span>
                  {approvingAll ? 'Approving…' : `Approve${hasFilters ? ' Filtered' : ' All'} (${paginated.length})`}
                </button>
              )}
            </div>
          </div>

          {/* Cards */}
          {loading ? (
            <div className="cards">
              {[1,2,3,4].map(i => <div key={i} className="card" style={{height:200,background:'var(--line-soft)',animation:'pulse 1.5s ease-in-out infinite'}} />)}
            </div>
          ) : filtered.length === 0 ? (
            <div style={{display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',minHeight:'40vh',textAlign:'center'}}>
              <div style={{width:64,height:64,borderRadius:16,background: hasFilters ? 'var(--blue-soft)' : '#dcfce7',display:'grid',placeItems:'center',fontSize:28,marginBottom:16}}>
                {hasFilters ? '🔍' : '✅'}
              </div>
              <p style={{fontWeight:600,color:'var(--ink)',margin:0}}>
                {hasFilters ? 'No matches' : 'All caught up!'}
              </p>
              <p style={{color:'var(--ink-4)',fontSize:14,marginTop:6}}>
                {hasFilters ? 'Try adjusting your filters.' : 'No companies pending review right now.'}
              </p>
            </div>
          ) : (
            <div className="cards">
              {paginated.map(c => (
                <PendingCard
                  key={c.id} company={c}
                  approved={!!approved[c.id]}
                  approving={approvingId === c.id}
                  onApprove={() => verifyOne(c.id)}
                />
              ))}
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

      {toast && (
        <div style={{position:'fixed',bottom:24,right:24,padding:'12px 20px',borderRadius:12,background:toast.ok?'var(--ink)':'var(--red)',color:'#fff',fontSize:14,fontWeight:600,boxShadow:'var(--shadow-pop)',zIndex:50,animation:'fadeUp .22s ease-out'}}>
          {toast.msg}
        </div>
      )}

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}} @keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}`}</style>
    </div>
  );
}

function PendingCard({ company: c, approved, approving, onApprove }: {
  company: Company; approved: boolean; approving: boolean; onApprove: () => void;
}) {
  const priv = c.ticker === 'Private';
  const primaryCat = (c.categories ?? [])[0] ?? '';
  const cats = (c.categories ?? []).map(catName).join(', ');
  const subs = (c.subcategories ?? []).join(', ');
  const url = safeUrl(c.website);

  return (
    <div className={`card${approved ? ' approved' : ''}`} style={approving ? { opacity: 0.5 } : undefined}>
      <div className="card-top">
        <div className="name-wrap">
          <span className="sdot" style={{ background: sectorColor(primaryCat) }} />
          <h3>{c.company_name}</h3>
        </div>
        <span className={`ticker${priv ? ' priv' : ''}`}>{c.ticker}</span>
      </div>

      <div className="meta">
        <div><div className="label">Country</div><div className="value">{c.country || '—'}</div></div>
        <div><div className="label">Market</div><div className="value">{c.market || '—'}</div></div>
        <div><div className="label">Category</div><div className="value">{cats || '—'}</div></div>
        <div><div className="label">Subcategory</div>
          <div className="value">{subs || '—'}
            {(c.proposed_subcategories ?? []).map(name => (
              <span key={name} style={{display:'inline-flex',alignItems:'center',gap:4,marginTop:4,padding:'2px 8px',borderRadius:6,fontSize:11,fontWeight:600,background:'#fffbeb',color:'#b45309',border:'1px solid #fde68a'}}>
                ⚠️ New: {name}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="card-actions">
        {url
          ? <a href={url} target="_blank" rel="noreferrer noopener" className="btn-visit"><IGlobe /> Visit</a>
          : <span />
        }
        <button className="btn-approve" onClick={onApprove} disabled={approving}>
          <ICheck /> Approve
        </button>
      </div>
    </div>
  );
}
