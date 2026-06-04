import { useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
  ResponsiveContainer, Cell,
} from 'recharts';
import { useMaskReveal } from '../hooks/useMaskReveal';

const BINS = 20;

function buildHistogramData(transactions) {
  const counts = Array.from({ length: BINS }, (_, i) => ({
    range: `${(i / BINS).toFixed(2)}–${((i + 1) / BINS).toFixed(2)}`,
    midpoint: (i + 0.5) / BINS,
    count: 0,
  }));
  for (const txn of transactions) {
    const score = txn.anomaly_score;
    if (score === undefined || score === null) continue;
    const bin = Math.min(Math.floor(score * BINS), BINS - 1);
    counts[bin].count += 1;
  }
  return counts;
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{
      background: 'var(--surface-2)',
      border: '1px solid var(--border-bright)',
      borderRadius: 'var(--r-md)',
      padding: '10px 14px',
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 'var(--text-xs)',
      color: 'var(--text-1)',
      boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
    }}>
      <div style={{ color: 'var(--text-3)', marginBottom: 4 }}>Score {d.range}</div>
      <div style={{ fontWeight: 700 }}>{d.count} transactions</div>
    </div>
  );
}

function binColor(midpoint) {
  if (midpoint >= 0.85) return '#ef4444';
  if (midpoint >= 0.60) return '#f59e0b';
  return '#22d3ee';
}

export default function ScoreHistogram({ transactions }) {
  const revealRef = useMaskReveal([transactions.length]);
  const data = useMemo(() => buildHistogramData(transactions), [transactions]);
  const hasData = transactions.some(t => t.anomaly_score !== undefined);

  if (!hasData) {
    return (
      <div className="empty-state" data-testid="empty-histogram">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <rect x="6"  y="28" width="8"  height="14" rx="2" stroke="currentColor" strokeWidth="1.5"/>
          <rect x="20" y="18" width="8"  height="24" rx="2" stroke="currentColor" strokeWidth="1.5"/>
          <rect x="34" y="10" width="8"  height="32" rx="2" stroke="currentColor" strokeWidth="1.5"/>
        </svg>
        <span>No scored transactions yet — run the pipeline to see the distribution.</span>
      </div>
    );
  }

  return (
    <div data-testid="score-histogram" data-accent="histogram" ref={revealRef}>
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <div className="mask-outer">
          <div className="mask-inner">
            <p className="pg-section-label" style={{ color: '#a855f7' }}>// 03 — Score Distribution</p>
          </div>
        </div>
        <div className="mask-outer">
          <div className="mask-inner">
            <h2 className="pg-section-title">Anomaly Score Histogram</h2>
          </div>
        </div>
        <div className="mask-outer">
          <div className="mask-inner" style={{ marginTop: 'var(--space-2)' }}>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-2)', fontFamily: "'JetBrains Mono', monospace" }}>
              {transactions.length} transactions · thresholds: review ≥ 0.60 · flag ≥ 0.85
            </p>
          </div>
        </div>
      </div>

      <div className="histogram-wrap">
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={data} margin={{ top: 8, right: 20, left: 0, bottom: 8 }}
                    barCategoryGap="8%">
            <CartesianGrid
              strokeDasharray="2 4"
              vertical={false}
              stroke="rgba(255,255,255,0.04)"
            />
            <XAxis
              dataKey="range"
              tick={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fill: 'var(--text-3)' }}
              axisLine={{ stroke: 'var(--border)' }}
              tickLine={false}
              interval={3}
            />
            <YAxis
              tick={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fill: 'var(--text-3)' }}
              axisLine={false}
              tickLine={false}
              width={28}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />

            {/* Threshold lines */}
            <ReferenceLine x={data.find(d => d.midpoint >= 0.60)?.range}
              stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1}
              label={{ value: 'review', fill: '#f59e0b', fontSize: 10,
                       fontFamily: "'JetBrains Mono', monospace", position: 'top' }} />
            <ReferenceLine x={data.find(d => d.midpoint >= 0.85)?.range}
              stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1}
              label={{ value: 'flag', fill: '#ef4444', fontSize: 10,
                       fontFamily: "'JetBrains Mono', monospace", position: 'top' }} />

            <Bar dataKey="count" radius={[3, 3, 0, 0]} maxBarSize={32}>
              {data.map((entry, i) => (
                <Cell key={i} fill={binColor(entry.midpoint)} opacity={0.8} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
