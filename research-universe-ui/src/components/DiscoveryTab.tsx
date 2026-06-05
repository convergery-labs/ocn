import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { Category, ScanJob, ScheduleSummary } from '../types';
import { catName } from '../utils/url';


const IPlay     = () => <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5v14l11-7z"/></svg>;
const ICalendar = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9h18M8 2.5v4M16 2.5v4"/></svg>;
const ICheck    = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>;
const ISearch   = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>;
const IDedup    = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M21 2v6h-6M3 22v-6h6"/><path d="M21 8A9 9 0 0 0 6 5.3L3 8m0 8a9 9 0 0 0 15 2.7l3-2.7"/></svg>;
const IClipboard= () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="3" width="8" height="4" rx="1"/><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/><path d="M9 12h6M9 16h4"/></svg>;

interface DiscoveryTabProps { onPendingCountChange: (count: number) => void; }

export function DiscoveryTab({ onPendingCountChange }: DiscoveryTabProps) {
  const [subTab, setSubTab] = useState<'scan' | 'schedule'>('scan');
  const [categories, setCategories] = useState<Category[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [catsLoading, setCatsLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [job, setJob] = useState<ScanJob | null>(null);
  const [schedule, setSchedule] = useState<ScheduleSummary | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 4000); };

  useEffect(() => {
    api.categories()
      .then(cats => { setCategories(cats); setSelected(new Set(cats.map(c => c.id))); })
      .catch(() => {})
      .finally(() => setCatsLoading(false));
  }, []);

  const loadSchedule = useCallback(async () => {
    try { setSchedule(await api.schedule()); } catch {}
  }, []);

  useEffect(() => { if (subTab === 'schedule') loadSchedule(); }, [subTab, loadSchedule]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const toggleCat = (id: number) => setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const startScan = async () => {
    if (!selected.size) { showToast('Select at least one category'); return; }
    setScanning(true); setJob(null);
    try {
      const { job_id } = await api.startScan([...selected]);
      pollRef.current = setInterval(async () => {
        try {
          const j = await api.pollScan(job_id);
          setJob(j);
          if (j.status === 'completed' || j.status === 'failed') {
            clearInterval(pollRef.current!); setScanning(false);
            if (j.status === 'completed') {
              showToast(`Done — ${j.companies_proposed} companies proposed`);
              api.stats().then(s => onPendingCountChange(s.pending)).catch(() => {});
            }
          }
        } catch { clearInterval(pollRef.current!); setScanning(false); }
      }, 5000);
    } catch { setScanning(false); showToast('Failed to start scan'); }
  };

  const totalSelected = selected.size;
  const pct = job && totalSelected ? Math.round((job.categories_done / totalSelected) * 100) : 0;
  const doneIds = new Set(job?.category_results?.map(r => r.category_id) ?? []);

  return (
    <div className="view">
      <div className="disc-wrap">
        {/* Sub-tab toggle */}
        <div className="disc-topbar">
          <div className="run-toggle">
            <button className={subTab === 'scan' ? 'on' : ''} onClick={() => setSubTab('scan')}><IPlay /> Scan</button>
            <button className={subTab === 'schedule' ? 'on' : ''} onClick={() => setSubTab('schedule')}><ICalendar /> Schedule</button>
          </div>
        </div>

        {subTab === 'scan' ? (
          <div className="disc">
            {/* Left — category selector */}
            <div className="disc-left">
              <div className="cat-head">
                <div>
                  <div className="t">Categories</div>
                  <div className="c">{selected.size} of {categories.length} selected</div>
                </div>
                <div className="seg">
                  <button onClick={() => setSelected(new Set(categories.map(c => c.id)))}>All</button>
                  <button onClick={() => setSelected(new Set())}>None</button>
                </div>
              </div>

              <div className="cat-list">
                {catsLoading
                  ? Array.from({length:10}).map((_,i) => <div key={i} style={{height:46,background:'var(--line-soft)',borderRadius:'var(--r-md)',animation:'pulse 1.5s ease-in-out infinite'}} />)
                  : categories.map(c => {
                      const on = selected.has(c.id);
                      return (
                        <div key={c.id} className={`cat${on ? ' on' : ''}`} onClick={() => toggleCat(c.id)}>
                          <span className="cbx"><ICheck /></span>
                          <span>{catName(c.name)}</span>
                        </div>
                      );
                    })
                }
              </div>

              <div className="run-scan-big">
                <button onClick={startScan} disabled={scanning || !selected.size || catsLoading}>
                  {scanning
                    ? <><span style={{width:16,height:16,border:'2px solid rgba(255,255,255,.3)',borderTopColor:'#fff',borderRadius:'50%',animation:'spin .7s linear infinite',display:'inline-block'}} /> {job ? `${job.categories_done} / ${totalSelected} done` : 'Starting…'}</>
                    : <><IPlay /> Run Scan ({selected.size})</>
                  }
                </button>
              </div>
            </div>

            {/* Right — ready state or progress */}
            <div className="disc-right">
              <div className="glow" />
              {!job && !scanning ? (
                <div className="ready">
                  <div className="ready-hero">
                    <div className="ready-hero-text">
                      <h2>Ready to scan</h2>
                      <p>Select categories on the left and click <b>Run Scan</b>.<br />Newly discovered companies will appear in Pending Review.</p>
                    </div>
                  </div>
                  <div className="ready-cards">
                    <div className="ready-card">
                      <div className="rc-icon"><ISearch /></div>
                      <div className="rc-t">Searches globally</div>
                      <div className="rc-s">Scans NYSE, Nasdaq, LSE, TSE, HKEX, ASX and all other major exchanges worldwide.</div>
                    </div>
                    <div className="ready-card">
                      <div className="rc-icon"><IDedup /></div>
                      <div className="rc-t">Deduplicates</div>
                      <div className="rc-s">Automatically skips companies already in the universe using fuzzy name and ticker matching.</div>
                    </div>
                    <div className="ready-card">
                      <div className="rc-icon"><IClipboard /></div>
                      <div className="rc-t">Queues for review</div>
                      <div className="rc-s">Every new discovery lands in Pending Review — you approve, edit, or reject each one.</div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="prog-panel">
                  {/* Stats */}
                  <div className="prog-stat-grid">
                    {[
                      { label: 'Categories Done', val: `${job?.categories_done ?? 0} / ${totalSelected}` },
                      { label: 'Proposed',         val: job?.companies_proposed ?? 0, green: true },
                      { label: 'Skipped',          val: job?.companies_skipped ?? 0 },
                    ].map(s => (
                      <div className="prog-stat" key={s.label}>
                        <div className="ps-label">{s.label}</div>
                        <div className="ps-val" style={s.green ? {color:'var(--green)'} : undefined}>{s.val}</div>
                      </div>
                    ))}
                  </div>

                  {/* Progress bar */}
                  <div className="prog-bar-wrap">
                    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:4}}>
                      <span style={{fontWeight:700,fontSize:14,color:'var(--ink)'}}>Overall Progress</span>
                      <div style={{display:'flex',alignItems:'center',gap:8}}>
                        <span style={{fontWeight:800,fontSize:14,color:'var(--ink)'}}>{pct}%</span>
                        {job && (
                          <span className="status-badge" style={{
                            background: job.status==='completed'?'#dcfce7': job.status==='failed'?'#fee2e2':'#dbeafe',
                            color: job.status==='completed'?'#166534': job.status==='failed'?'#991b1b':'#1e40af',
                          }}>{job.status}</span>
                        )}
                      </div>
                    </div>
                    <div className="prog-bar-track"><div className="prog-bar-fill" style={{width:`${pct}%`}} /></div>
                  </div>

                  {/* Per-category results */}
                  <div className="cat-results">
                    <div style={{fontWeight:700,fontSize:14,color:'var(--ink)',marginBottom:10}}>Category Results</div>
                    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6}}>
                      {categories.filter(c => selected.has(c.id)).map(c => {
                        const isDone = doneIds.has(c.id);
                        const result = job?.category_results?.find(r => r.category_id === c.id);
                        const isRunning = scanning && !isDone && job && job.categories_done < totalSelected;
                        return (
                          <div key={c.id} className={`cat-result-row${isDone?' done':isRunning?' running':' pending'}`}>
                            <div className="cat-dot" style={{background: isDone?'#22c55e': isRunning?'#3b82f6':'#d1d5db'}} />
                            <span style={{flex:1,fontSize:12,color:'var(--ink-2)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{catName(c.name)}</span>
                            {isDone && result && (
                              <span style={{fontSize:11,color:'var(--ink-4)',whiteSpace:'nowrap'}}>
                                <span style={{color:'var(--green)',fontWeight:600}}>+{result.proposed}</span> · {result.skipped} skip
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Schedule tab — full width */
          <div style={{flex:1,overflow:'auto',padding:'36px 48px'}}>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:24,marginBottom:24}}>
              {[
                { label:'Last Run', val: schedule?.last_run_at ? new Date(schedule.last_run_at).toLocaleString() : 'Never', sub:'Most recent completed sweep' },
                { label:'Next Run', val: schedule?.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : '—',     sub:'Next scheduled sweep' },
              ].map(r => (
                <div key={r.label} style={{background:'var(--surface)',border:'1px solid var(--line)',borderRadius:'var(--r-xl)',padding:'28px 32px',boxShadow:'var(--shadow-card)'}}>
                  <div style={{fontSize:11,textTransform:'uppercase',letterSpacing:'.06em',color:'var(--ink-4)',marginBottom:12}}>{r.label}</div>
                  <div style={{fontSize:22,fontWeight:800,color:'var(--ink)',marginBottom:6,letterSpacing:'-.4px'}}>
                    {schedule ? r.val : <span style={{display:'block',height:28,width:200,background:'var(--line-soft)',borderRadius:6,animation:'pulse 1.5s ease-in-out infinite'}} />}
                  </div>
                  <div style={{fontSize:13,color:'var(--ink-4)'}}>{r.sub}</div>
                </div>
              ))}
            </div>

            <div style={{background:'var(--surface)',border:'1px solid var(--line)',borderRadius:'var(--r-xl)',padding:'28px 32px',boxShadow:'var(--shadow-card)'}}>
              <div style={{fontSize:16,fontWeight:700,color:'var(--ink)',marginBottom:8}}>Schedule</div>
              <p style={{fontSize:14,color:'var(--ink-3)',margin:'0 0 20px',lineHeight:1.6}}>
                A full sweep of all 19 categories runs automatically every <strong style={{color:'var(--ink)'}}>Monday and Thursday at 09:00 UTC</strong>.<br/>
                Each run scans globally, deduplicates against existing companies, and queues discoveries in Pending Review.
              </p>
              <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
                {[
                  { day:'Monday',    time:'09:00 UTC', note:'Start of week scan' },
                  { day:'Thursday',  time:'09:00 UTC', note:'Mid-week scan' },
                  { day:'On-demand', time:'Any time',  note:'Run Scan tab' },
                ].map(s => (
                  <div key={s.day} style={{background:'var(--cream)',borderRadius:'var(--r-md)',padding:'16px 18px'}}>
                    <div style={{fontSize:13,fontWeight:700,color:'var(--ink)',marginBottom:4}}>{s.day}</div>
                    <div style={{fontSize:13,color:'var(--blue)',fontWeight:600,marginBottom:4}}>{s.time}</div>
                    <div style={{fontSize:12,color:'var(--ink-4)'}}>{s.note}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {toast && (
        <div style={{position:'fixed',bottom:24,right:24,padding:'12px 20px',borderRadius:12,background:'var(--ink)',color:'#fff',fontSize:14,fontWeight:600,boxShadow:'var(--shadow-pop)',zIndex:50,animation:'fadeUp .22s ease-out'}}>
          {toast}
        </div>
      )}

      <style>{`@keyframes spin{to{transform:rotate(360deg)}} @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}} @keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}`}</style>
    </div>
  );
}
