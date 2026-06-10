import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import { safeUrl, catName } from '../utils/url';
import type { ChatMessage } from '../types';
import { BADGE } from '../tokens';
import ReactMarkdown from 'react-markdown';

let _msgId = 0;
const nextId = () => `m${++_msgId}`;

const SECTOR_COLORS = ['#c98a2b','#e07b39','#d65745','#d64f7d','#b357c9','#8a5cf0','#5b6ef0','#2f7be0','#2ba6d9','#16a39a','#1f9e84','#3a9e54','#6f9e2e','#6b78a8','#189e6e','#5e7a8f','#b8902a','#2898b0','#7d5ad0'];



const ISearch = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>;
const IPlus   = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14"/></svg>;
const IPeers  = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="2.5"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><path d="M6.6 7.3 10 10.6M17.4 7.3 14 10.6M6.6 16.7 10 13.4M17.4 16.7 14 13.4"/></svg>;
const IFolder = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>;
const IArrow  = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>;

const SUGGESTIONS = [
  { Icon: ISearch, text: 'Search for NVIDIA' },
  { Icon: IPlus,   text: 'Add Cerebras to the universe' },
  { Icon: IPeers,  text: 'Who are the peers of ASML?' },
  { Icon: IFolder, text: "What's in Quantum Computing?" },
];

/* Constellation canvas */
function Constellation() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    let raf: number, w = 0, h = 0, nodes: any[] = [];
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const hexA = (hex: string, a: number) => { const n = parseInt(hex.slice(1),16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`; };
    const alphaAt = (x: number, y: number) => { const d = Math.hypot(x-w/2, y-h*.46), m = Math.min(w,h)*.52; return Math.min(0.35, 0.08+0.27*(d/m)); };
    function build() {
      const count = Math.round(Math.min(95, Math.max(42, w*h/13000)));
      nodes = Array.from({length:count}, () => ({
        x:Math.random()*w, y:Math.random()*h, vx:(Math.random()-.5)*.16, vy:(Math.random()-.5)*.16,
        r:Math.random()*2.2+1.5, c:SECTOR_COLORS[Math.floor(Math.random()*SECTOR_COLORS.length)],
        ph:Math.random()*6.28, hub:Math.random()<.16,
      }));
    }
    function resize() {
      const dpr = Math.min(window.devicePixelRatio||1,2);
      const r = canvas!.getBoundingClientRect(); w=r.width; h=r.height;
      canvas!.width=w*dpr; canvas!.height=h*dpr; ctx.setTransform(dpr,0,0,dpr,0,0); build();
    }
    function frame(t: number) {
      ctx.clearRect(0,0,w,h);
      for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++){
        const a=nodes[i],b=nodes[j],dist=Math.hypot(a.x-b.x,a.y-b.y);
        if(dist<145){const al=(1-dist/145)*.2*alphaAt((a.x+b.x)/2,(a.y+b.y)/2); ctx.strokeStyle=`rgba(31,95,224,${al})`; ctx.lineWidth=1; ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();}
      }
      for(const n of nodes){
        const pulse=reduce?1:(0.72+0.28*Math.sin(t/950+n.ph)), a=alphaAt(n.x,n.y);
        if(n.hub){const g=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,n.r*5); g.addColorStop(0,hexA(n.c,a*.34*pulse)); g.addColorStop(1,hexA(n.c,0)); ctx.fillStyle=g; ctx.beginPath(); ctx.arc(n.x,n.y,n.r*5,0,6.28); ctx.fill();}
        ctx.beginPath(); ctx.arc(n.x,n.y,n.r,0,6.28); ctx.fillStyle=hexA(n.c,a*.9*pulse); ctx.fill();
        if(!reduce){n.x+=n.vx; n.y+=n.vy; if(n.x<0||n.x>w)n.vx*=-1; if(n.y<0||n.y>h)n.vy*=-1;}
      }
      if(!reduce) raf=requestAnimationFrame(frame);
    }
    resize(); reduce ? frame(0) : (raf=requestAnimationFrame(frame));
    window.addEventListener('resize',resize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize',resize); };
  }, []);
  return <canvas ref={ref} className="constellation" aria-hidden />;
}

interface ChatTabProps {
  onPendingCountChange: (count: number) => void;
  onNavigateToPending: () => void;
}

export function ChatTab({ onPendingCountChange, onNavigateToPending }: ChatTabProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, loading]);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setInput(''); setLoading(true);
    setMessages(prev => [...prev, { id: nextId(), role: 'user', text: trimmed, timestamp: new Date() }]);
    try {
      const res = await api.chat(trimmed, conversationId);
      setConversationId(res.conversation_id);
      const cleanText = (res.message ?? '').replace(/```json[\s\S]*?```/g,'').replace(/```[\s\S]*?```/g,'').trim();
      setMessages(prev => [...prev, { id: nextId(), role: 'agent', text: cleanText, cardType: res.card_type, cardData: res.card_data, timestamp: new Date() }]);
      if (res.card_type === 'proposed_entry' || res.card_type === 'review_nudge') {
        api.pending().then(p => onPendingCountChange(p.length)).catch(() => {});
      }
    } catch {
      setMessages(prev => [...prev, { id: nextId(), role: 'agent', text: '⚠️ Could not reach the server. Please try again.', timestamp: new Date() }]);
    } finally { setLoading(false); setTimeout(() => inputRef.current?.focus(), 50); }
  }, [loading, conversationId, onPendingCountChange]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); }
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="view">
      <div className="chat-view">
        <Constellation />

        {/* Welcome or message thread */}
        {!hasMessages ? (
          <div className="chat-scroll">
            <div className="welcome">
              <h1>Explore the <span className="accent">AI Economy</span> Universe</h1>
              <p>Search companies, add new entries, discover peers, or explore all sectors of the AI economy stack.</p>
              <div className="suggest-grid">
                {SUGGESTIONS.map(({ Icon, text }) => (
                  <button key={text} className="suggest" onClick={() => { setInput(text); inputRef.current?.focus(); }}>
                    <span className="s-icon"><Icon /></span>
                    <span className="s-text">{text}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="chat-messages">
            <div className="msg-thread">
              {messages.map(msg => <MessageRow key={msg.id} message={msg} onNavigateToPending={onNavigateToPending} />)}
              {loading && (
                <div className="msg-row" style={{ marginTop: 16 }}>
                  <div className="msg-avatar agent">AI</div>
                  <div className="typing-dots">
                    <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>
        )}

        {/* Composer */}
        <div className="composer">
          <div className="composer-inner">
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={loading}
              placeholder="Search a company, ask to add one, or explore the universe…"
            />
            <button className="btn-send" disabled={loading || !input.trim()} onClick={() => send(input)}>
              {loading
                ? <span style={{ width:18,height:18,border:'2px solid rgba(255,255,255,.3)',borderTopColor:'#fff',borderRadius:'50%',animation:'spin 0.7s linear infinite',display:'inline-block' }} />
                : <>Send <span className="arr"><IArrow /></span></>
              }
            </button>
          </div>
        </div>
      </div>

      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

function MessageRow({ message: msg, onNavigateToPending }: { message: ChatMessage; onNavigateToPending: () => void }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`msg-row${isUser ? ' user' : ''}`} style={{ marginBottom: 16 }}>
      <div className={`msg-avatar ${isUser ? 'user' : 'agent'}`}>{isUser ? 'U' : 'AI'}</div>
      <div style={{ display:'flex', flexDirection:'column', gap:4, maxWidth:'78%', alignItems: isUser ? 'flex-end' : 'flex-start' }}>
        {msg.text && (
          <div className={`msg-bubble ${isUser ? 'user' : 'agent'}`}>
            {isUser ? msg.text : (
              <ReactMarkdown components={{
                p: ({ children }) => <p style={{margin:'0 0 6px',lineHeight:1.6}}>{children}</p>,
                strong: ({ children }) => <strong style={{fontWeight:600}}>{children}</strong>,
                li: ({ children }) => <li style={{display:'flex',alignItems:'flex-start',gap:8,marginBottom:4}}><span style={{width:6,height:6,borderRadius:'50%',background:'var(--blue)',flexShrink:0,marginTop:6}}/>  <span>{children}</span></li>,
              }}>{msg.text}</ReactMarkdown>
            )}
          </div>
        )}
        {!isUser && msg.cardType && msg.cardData && (
          <CardRenderer cardType={msg.cardType} cardData={msg.cardData as Record<string,unknown>} onNavigateToPending={onNavigateToPending} />
        )}
        <span className="msg-time">{msg.timestamp.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>
      </div>
    </div>
  );
}

function CardRenderer({ cardType, cardData, onNavigateToPending }: { cardType:string; cardData:Record<string,unknown>; onNavigateToPending:()=>void }) {
  if (cardType === 'company_card')   return <CompanyCard data={cardData} pending={false} />;
  if (cardType === 'proposed_entry') return <CompanyCard data={cardData} pending={true} />;
  if (cardType === 'peer_proposals') return <PeerProposals data={cardData} />;
  if (cardType === 'review_nudge')   return <ReviewNudge data={cardData} onNavigate={onNavigateToPending} />;
  return null;
}

function CompanyCard({ data, pending }: { data: Record<string,unknown>; pending: boolean }) {
  const cats = Array.isArray(data.categories) ? (data.categories as string[]).map(catName).join(', ') : catName(String(data.category ?? '-'));
  const subs = Array.isArray(data.subcategories) ? (data.subcategories as string[]).join(', ') : String(data.subcategory ?? '-');
  return (
    <div className="card" style={{width:'100%',maxWidth:400}}>
      <div className="card-top">
        <div className="name-wrap">
          <h3 style={{fontSize:16}}>{String(data.company_name ?? data.name ?? '-')}</h3>
        </div>
        <span className={`ticker${data.ticker === 'Private' ? ' priv' : ''}`}>{String(data.ticker ?? '-')}</span>
      </div>
      <div className="meta">
        <div><div className="label">Status</div><div className="value">
          <span className={pending ? BADGE.pending : BADGE.verified} style={{display:'inline-flex',alignItems:'center',gap:4,padding:'2px 8px',borderRadius:999,fontSize:12,fontWeight:600}}>
            {pending ? '⏳ Pending' : '✅ Verified'}
          </span>
        </div></div>
        <div><div className="label">Country</div><div className="value">{String(data.country ?? '-')}</div></div>
        <div><div className="label">Category</div><div className="value">{cats}</div></div>
        <div><div className="label">Subcategory</div><div className="value">{subs}</div></div>
        {safeUrl(String(data.website ?? '')) && (
          <div style={{gridColumn:'span 2'}}>
            <div className="label">Website</div>
            <a href={safeUrl(String(data.website))} target="_blank" rel="noreferrer noopener" style={{color:'var(--blue)',fontSize:13,textDecoration:'none'}}>
              {String(data.website)}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function PeerProposals({ data }: { data: Record<string,unknown> }) {
  const peers = (data.peers ?? data.companies ?? []) as Record<string,unknown>[];
  if (!peers.length) return null;
  return (
    <div className="card" style={{width:'100%',maxWidth:420}}>
      <div style={{fontSize:12,fontWeight:700,color:'var(--blue)',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:12}}>
        🔍 Peer Discovery — {peers.length} suggestions
      </div>
      <div style={{display:'flex',flexDirection:'column',gap:8,maxHeight:240,overflowY:'auto'}}>
        {peers.map((p,i) => (
          <div key={i} style={{background:'var(--cream-2)',borderRadius:'var(--r-sm)',padding:'10px 12px'}}>
            <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:3}}>
              <span style={{fontWeight:600,fontSize:13,color:'var(--ink)'}}>{String(p.company_name ?? '')}</span>
              {Boolean(p.ticker) && <span style={{fontFamily:'JetBrains Mono,monospace',fontSize:10,fontWeight:600,color:'var(--blue)',background:'var(--blue-soft)',padding:'2px 7px',borderRadius:5}}>{String(p.ticker)}</span>}
            </div>
            <p style={{fontSize:12,color:'var(--ink-4)',margin:0}}>{String(p.country ?? '')} · {String(p.market ?? '')}</p>
            {Boolean(p.reason) && <p style={{fontSize:11,color:'var(--ink-4)',margin:'3px 0 0',fontStyle:'italic'}}>{String(p.reason)}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewNudge({ data, onNavigate }: { data: Record<string,unknown>; onNavigate: () => void }) {
  const count = (data.pending_count as number) ?? (data.companies as unknown[])?.length ?? 0;
  return (
    <div style={{background:'#fffbf0',border:'1px solid #f0d080',borderRadius:'var(--r-lg)',padding:'16px 20px',maxWidth:300}}>
      <div style={{fontSize:12,fontWeight:700,color:'#b45309',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:8}}>⏳ Pending Review</div>
      <p style={{color:'var(--ink-2)',fontSize:14,margin:'0 0 12px'}}><strong>{count}</strong> {count===1?'company':'companies'} awaiting your review.</p>
      <button onClick={onNavigate} style={{fontSize:13,fontWeight:600,color:'#b45309',background:'#fef3c7',border:'none',padding:'7px 14px',borderRadius:999,cursor:'pointer'}}>
        Open Review Queue →
      </button>
    </div>
  );
}
