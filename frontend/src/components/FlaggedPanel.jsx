import { useMaskReveal } from '../hooks/useMaskReveal';

export default function FlaggedPanel({ flagged }) {
  const revealRef = useMaskReveal([flagged.length]);

  if (!flagged || flagged.length === 0) {
    return (
      <div className="empty-state" data-testid="empty-flagged">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <circle cx="24" cy="24" r="16" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M24 16v8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          <circle cx="24" cy="30" r="1.5" fill="currentColor"/>
        </svg>
        <span>No flagged transactions yet — model is running cleanly.</span>
      </div>
    );
  }

  return (
    <div data-testid="flagged-panel" data-accent="flagged" ref={revealRef}>
      {/* Section label */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <div className="mask-outer">
          <div className="mask-inner">
            <p className="pg-section-label" style={{ color: '#ef4444' }}>// 02 — Flagged Transactions</p>
          </div>
        </div>
        <div className="mask-outer">
          <div className="mask-inner">
            <div className="flagged-header">
              <h2 className="pg-section-title">Threat Alerts</h2>
              <span className="flagged-count-pill">{flagged.length} flagged</span>
            </div>
          </div>
        </div>
      </div>

      {/* Rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, overflow: 'auto', maxHeight: '65vh' }}>
        {flagged.map((txn, i) => (
          <div
            key={txn.transaction_id || i}
            className="flagged-row"
            style={{ animationDelay: `${Math.min(i * 40, 400)}ms` }}
          >
            {/* Left: id + meta */}
            <div>
              <div className="flagged-txn-id">
                {txn.transaction_id?.slice(0, 12) ?? 'unknown'}…
              </div>
              <div className="flagged-meta">
                <span>{txn.user_id?.slice(0, 10)}…</span>
                <span>{txn.merchant_category}</span>
                {txn.fraud_type && (
                  <span className="fraud-tag">{txn.fraud_type}</span>
                )}
              </div>
            </div>

            {/* Amount */}
            <span className="flagged-amount">
              ${Number(txn.amount).toFixed(2)}
            </span>

            {/* Score */}
            <span className="flagged-score">
              {txn.anomaly_score !== undefined
                ? `score ${Number(txn.anomaly_score).toFixed(3)}`
                : '—'}
            </span>

            {/* Time */}
            <span className="flagged-time">
              {txn.created_at || txn.flagged_at
                ? new Date(txn.created_at || txn.flagged_at).toLocaleTimeString()
                : '—'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
