import { useMaskReveal } from '../hooks/useMaskReveal';

function ScoreBar({ score, decision }) {
  const pct = Math.round((score ?? 0) * 100);
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div
          className={`score-bar-fill ${decision}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="score-val">{(score ?? 0).toFixed(2)}</span>
    </div>
  );
}

export default function TransactionFeed({ transactions }) {
  const revealRef = useMaskReveal([transactions.length]);

  if (!transactions || transactions.length === 0) {
    return (
      <div className="empty-state" data-testid="empty-feed">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <rect x="8" y="8" width="32" height="32" rx="4" stroke="currentColor" strokeWidth="1.5"/>
          <line x1="14" y1="18" x2="34" y2="18" stroke="currentColor" strokeWidth="1.5"/>
          <line x1="14" y1="24" x2="34" y2="24" stroke="currentColor" strokeWidth="1.5"/>
          <line x1="14" y1="30" x2="24" y2="30" stroke="currentColor" strokeWidth="1.5"/>
        </svg>
        <span>No transactions yet — start the generator to see live data.</span>
      </div>
    );
  }

  return (
    <div data-testid="transaction-feed" data-accent="feed" ref={revealRef}>
      {/* Section label + title */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <div className="mask-outer">
          <div className="mask-inner">
            <p className="pg-section-label">// 01 — Live Feed</p>
          </div>
        </div>
        <div className="mask-outer">
          <div className="mask-inner">
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-3)' }}>
              <h2 className="pg-section-title">Recent Transactions</h2>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 'var(--text-xs)',
                color: 'var(--text-3)'
              }}>
                {transactions.length} shown
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Column headers */}
      <div className="txn-table-header" aria-hidden="true">
        <span>Decision</span>
        <span>User</span>
        <span>Merchant</span>
        <span>Amount</span>
        <span>Score</span>
        <span>Fraud type</span>
        <span>Time</span>
      </div>

      {/* Rows */}
      <div className="txn-list">
        {transactions.map((txn) => (
          <div
            key={txn.transaction_id}
            className={`txn-row row-${txn.decision || 'clear'}`}
          >
            <span className={`decision-badge ${txn.decision || 'clear'}`}>
              {txn.decision || 'clear'}
            </span>
            <span style={{ color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  title={txn.user_id}>
              {txn.user_id?.slice(0, 8)}…
            </span>
            <span style={{ color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {txn.merchant_category}
            </span>
            <span style={{
              color: 'var(--text-1)', fontWeight: 700,
              fontVariantNumeric: 'tabular-nums', textAlign: 'right'
            }}>
              ${Number(txn.amount).toFixed(2)}
            </span>
            <ScoreBar score={txn.anomaly_score} decision={txn.decision || 'clear'} />
            <span>
              {txn.fraud_type
                ? <span className="fraud-tag">{txn.fraud_type}</span>
                : <span style={{ color: 'var(--text-3)' }}>—</span>
              }
            </span>
            <span style={{
              color: 'var(--text-3)',
              fontVariantNumeric: 'tabular-nums',
              textAlign: 'right',
              whiteSpace: 'nowrap'
            }}>
              {txn.created_at ? new Date(txn.created_at).toLocaleTimeString() : '—'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
