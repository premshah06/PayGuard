import { useCounter } from '../hooks/useCounter';
import { useMagnetic } from '../hooks/useMagnetic';
import { useMaskReveal } from '../hooks/useMaskReveal';

function StatCard({ label, value, unit = '%', decimals = 1, accent }) {
  const { value: animated, nodeRef } = useCounter(
    value !== undefined ? parseFloat((value * 100).toFixed(decimals)) : 0,
    1200, decimals
  );
  return (
    <div className="stat-card" ref={nodeRef}
         style={accent ? { '--current-accent': accent } : undefined}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {animated.toFixed(decimals)}
        <span className="stat-unit">{unit}</span>
      </div>
    </div>
  );
}

function RawStatCard({ label, value, accent }) {
  const { value: animated, nodeRef } = useCounter(value ?? 0, 1200, 0);
  return (
    <div className="stat-card" ref={nodeRef}
         style={accent ? { '--current-accent': accent } : undefined}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{animated}</div>
    </div>
  );
}

function MagneticRefreshButton({ onClick }) {
  const magRef = useMagnetic(0.35);
  return (
    <button ref={magRef} className="mag-btn" onClick={onClick}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <path d="M12 7A5 5 0 1 1 7 2M7 2l3 1-1 3" stroke="currentColor"
              strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
      Refresh metrics
    </button>
  );
}

export default function StatsCounters({ stats, compact, detailed }) {
  const revealRef = useMaskReveal([stats?.f1]);

  const { precision = 0, recall = 0, f1 = 0, total = 0,
          tp = 0, fp = 0, fn = 0, tn = 0 } = stats || {};

  if (compact) {
    return (
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
        <StatCard label="Precision" value={precision} accent="var(--accent-stats)" />
        <StatCard label="Recall"    value={recall}    accent="var(--accent-stats)" />
        <StatCard label="F1 Score"  value={f1}        accent="var(--accent-stats)" />
        <RawStatCard label="Total (1h)" value={total} accent="var(--accent-stats)" />
      </div>
    );
  }

  return (
    <div data-testid="stats-counters" data-accent="stats" ref={revealRef}>
      {detailed && (
        <div style={{ marginBottom: 'var(--space-6)' }}>
          <div className="mask-outer">
            <div className="mask-inner">
              <p className="pg-section-label" style={{ color: '#f59e0b' }}>// 04 — Metrics</p>
            </div>
          </div>
          <div className="mask-outer">
            <div className="mask-inner">
              <h2 className="pg-section-title">Model Performance</h2>
            </div>
          </div>
          <div className="mask-outer">
            <div className="mask-inner" style={{ marginTop: 'var(--space-2)' }}>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-2)', fontFamily: "'JetBrains Mono', monospace" }}>
                Running precision / recall / F1 counters from /api/stats · last hour
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="stats-grid" style={{ marginBottom: 'var(--space-6)' }}>
        <StatCard label="Precision"   value={precision} accent="#f59e0b" />
        <StatCard label="Recall"      value={recall}    accent="#f59e0b" />
        <StatCard label="F1 Score"    value={f1}        accent="#f59e0b" />
        <RawStatCard label="Total (1h)" value={total}   accent="#f59e0b" />
      </div>

      {detailed && total > 0 && (
        <>
          <div className="pg-separator" />
          <div className="mask-outer" style={{ marginBottom: 'var(--space-4)' }}>
            <div className="mask-inner">
              <p className="pg-section-label">Confusion matrix</p>
            </div>
          </div>
          <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', maxWidth: 480 }}>
            <RawStatCard label="TP — correct flags" value={tp} accent="#00ff88" />
            <RawStatCard label="FP — false flags"   value={fp} accent="#ef4444" />
            <RawStatCard label="FN — missed fraud"  value={fn} accent="#f59e0b" />
            <RawStatCard label="TN — correct clear" value={tn} accent="#22d3ee" />
          </div>

          <div style={{ marginTop: 'var(--space-6)' }}>
            <MagneticRefreshButton onClick={() => window.location.reload()} />
          </div>
        </>
      )}
    </div>
  );
}
