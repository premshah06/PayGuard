import { useEffect, useState, useCallback, useRef } from 'react';
import TransactionFeed from './components/TransactionFeed';
import FlaggedPanel from './components/FlaggedPanel';
import ScoreHistogram from './components/ScoreHistogram';
import StatsCounters from './components/StatsCounters';
import { useWebSocket } from './hooks/useWebSocket';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';
const WS_URL  = import.meta.env.VITE_WS_URL  || 'ws://localhost:8001/ws';
const API_KEY = import.meta.env.VITE_API_KEY  || 'dev-secret-key';
const HEADERS = { 'X-API-Key': API_KEY };

const TABS = [
  { id: 'feed',      label: '// Live Feed',           accent: 'feed'      },
  { id: 'flagged',   label: '// Flagged',              accent: 'flagged'   },
  { id: 'histogram', label: '// Score Distribution',   accent: 'histogram' },
  { id: 'stats',     label: '// Metrics',              accent: 'stats'     },
];

export default function App({ reducedMotion }) {
  const [transactions, setTransactions] = useState([]);
  const [flagged,      setFlagged]      = useState([]);
  const [stats,        setStats]        = useState({ precision: 0, recall: 0, f1: 0, total: 0 });
  const [activeTab,    setActiveTab]    = useState('feed');
  const [loading,      setLoading]      = useState(true);
  const [lastUpdated,  setLastUpdated]  = useState(null);
  const progressRef = useRef(null);

  // Boot Lenis + GSAP accent shift after first paint.
  useEffect(() => {
    if (!reducedMotion) {
      import('./lib/motion').then(({ initMotion }) => initMotion());
    }
  }, [reducedMotion]);

  // Progress rail driven by native scroll (no GSAP dependency).
  useEffect(() => {
    if (reducedMotion) return;
    const onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
      const pct = scrollHeight === clientHeight ? 0 : (scrollTop / (scrollHeight - clientHeight)) * 100;
      if (progressRef.current) progressRef.current.style.width = `${pct}%`;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [reducedMotion]);

  // WebSocket: live flagged alerts.
  const { messages: wsFlagged, connected: wsConnected } = useWebSocket(WS_URL);

  useEffect(() => {
    if (!wsFlagged.length) return;
    setFlagged(prev => {
      const seen = new Set(prev.map(t => t.transaction_id));
      const fresh = wsFlagged.filter(t => !seen.has(t.transaction_id));
      return [...fresh, ...prev].slice(0, 200);
    });
  }, [wsFlagged]);

  // Accent shift on tab change.
  const handleTabChange = (tab) => {
    setActiveTab(tab.id);
    if (!reducedMotion) {
      const accentMap = {
        feed: '#6366f1', flagged: '#ef4444',
        histogram: '#8b5cf6', stats: '#f59e0b',
      };
      document.documentElement.style.setProperty('--current-accent', accentMap[tab.id] || '#00ff88');
    }
  };

  const fetchAll = useCallback(async () => {
    try {
      const [txnRes, flagRes, statsRes] = await Promise.all([
        fetch(`${API_URL}/api/transactions?limit=50`, { headers: HEADERS }),
        fetch(`${API_URL}/api/flagged?limit=100`,     { headers: HEADERS }),
        fetch(`${API_URL}/api/stats`,                 { headers: HEADERS }),
      ]);
      if (txnRes.ok)   setTransactions(await txnRes.json());
      if (flagRes.ok)  setFlagged(await flagRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      // Graceful degradation — leave stale state visible.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const flagCount = flagged.length;

  return (
    <>
      {/* Background canvas & custom cursor are pure DOM, not React-managed */}
      <canvas id="pg-canvas-bg" aria-hidden="true" />
      <div id="pg-cursor-dot"  aria-hidden="true" />
      <div id="pg-cursor-ring" aria-hidden="true" />
      <div ref={progressRef} className="progress-rail" aria-hidden="true" />

      <div className="pg-app">
        {/* ── Header ─────────────────────────────────────────── */}
        <header className="pg-header" data-accent="header">
          <div className="pg-header-inner">
            <div className="pg-logo">
              <div className="pg-logo-shield" aria-hidden="true">
                <svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path
                    d="M18 2L4 8v10c0 8.284 5.97 16.045 14 18 8.03-1.955 14-9.716 14-18V8L18 2z"
                    stroke="var(--current-accent)" strokeWidth="1.5" strokeLinejoin="round"
                    fill="rgba(37,99,235,0.08)"
                  />
                  <path d="M12 18l4 4 8-8" stroke="var(--current-accent)" strokeWidth="1.5"
                        strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className="pg-logo-text">
                <h1>PayGuard</h1>
                <p>Real-time Payment Fraud Detection</p>
              </div>
            </div>

            <div className="pg-header-right">
              <div className={`ws-status ${wsConnected ? 'live' : 'offline'}`}>
                <span className="ws-dot" />
                {wsConnected ? 'WS live' : 'WS offline'}
              </div>
              {lastUpdated && (
                <span className="pg-timestamp">Updated {lastUpdated}</span>
              )}
            </div>
          </div>
        </header>

        {/* ── Stats bar ───────────────────────────────────────── */}
        <div className="pg-statsbar" data-accent="stats">
          <div className="pg-statsbar-inner">
            <StatsCounters stats={stats} compact />
          </div>
        </div>

        {/* ── Tab navigation ──────────────────────────────────── */}
        <nav className="pg-nav" role="tablist">
          <div className="pg-nav-inner">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={activeTab === tab.id}
                className={`pg-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => handleTabChange(tab)}
              >
                {tab.label}
                {tab.id === 'flagged' && (
                  <span className={`pg-tab-badge ${flagCount > 0 ? 'alert' : ''}`}>
                    {flagCount}
                  </span>
                )}
                {tab.id === 'feed' && (
                  <span className="pg-tab-badge">{transactions.length}</span>
                )}
                <span className="pg-tab-indicator" aria-hidden="true" />
              </button>
            ))}
          </div>
        </nav>

        {/* ── Content ─────────────────────────────────────────── */}
        <main className="pg-main" role="tabpanel">
          {loading ? (
            <LoadingSkeleton />
          ) : (
            <>
              {activeTab === 'feed'      && <TransactionFeed  transactions={transactions} />}
              {activeTab === 'flagged'   && <FlaggedPanel     flagged={flagged} />}
              {activeTab === 'histogram' && <ScoreHistogram   transactions={transactions} />}
              {activeTab === 'stats'     && <StatsCounters    stats={stats} detailed />}
            </>
          )}
        </main>
      </div>
    </>
  );
}

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', paddingTop: '8px' }}>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: '44px', borderRadius: '10px', opacity: 1 - i * 0.08 }} />
      ))}
    </div>
  );
}
