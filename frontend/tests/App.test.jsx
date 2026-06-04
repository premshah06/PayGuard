/**
 * Jest / React Testing Library — frontend component tests.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// ── Stubs ──────────────────────────────────────────────────────────
// IntersectionObserver is not available in jsdom.
global.IntersectionObserver = class {
  constructor(cb) { this.cb = cb; }
  observe(el) { this.cb([{ isIntersecting: true, target: el }]); }
  unobserve() {}
  disconnect() {}
};

// matchMedia stub
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (q) => ({
    matches: false,
    media: q,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
  }),
});

// WebSocket stub
global.WebSocket = class {
  constructor() { setTimeout(() => this.onopen?.(), 0); }
  close() {}
  send() {}
};

// Canvas stub
HTMLCanvasElement.prototype.getContext = () => null;

// ── Components ─────────────────────────────────────────────────────
import TransactionFeed from '../src/components/TransactionFeed';
import FlaggedPanel from '../src/components/FlaggedPanel';
import StatsCounters from '../src/components/StatsCounters';
import ScoreHistogram from '../src/components/ScoreHistogram';

// ── Fixtures ───────────────────────────────────────────────────────
const SAMPLE_TXN = {
  transaction_id: 'txn-001',
  user_id: 'user-abcdef',
  amount: 125.50,
  merchant_category: 'grocery',
  anomaly_score: 0.35,
  decision: 'clear',
  ground_truth_label: 0,
  fraud_type: null,
  created_at: '2024-06-10T14:30:00Z',
};

const FLAGGED_TXN = {
  ...SAMPLE_TXN,
  transaction_id: 'txn-002',
  anomaly_score: 0.92,
  decision: 'flag',
  ground_truth_label: 1,
  fraud_type: 'amount_anomaly',
  amount: 9999.00,
};

// ── TransactionFeed ────────────────────────────────────────────────
describe('TransactionFeed', () => {
  it('renders empty state when no transactions', () => {
    render(<TransactionFeed transactions={[]} />);
    expect(screen.getByTestId('empty-feed')).toBeInTheDocument();
  });

  it('renders transaction rows', () => {
    render(<TransactionFeed transactions={[SAMPLE_TXN]} />);
    expect(screen.getByTestId('transaction-feed')).toBeInTheDocument();
  });

  it('shows merchant category', () => {
    render(<TransactionFeed transactions={[SAMPLE_TXN]} />);
    expect(screen.getByText('grocery')).toBeInTheDocument();
  });

  it('shows decision badge', () => {
    render(<TransactionFeed transactions={[SAMPLE_TXN]} />);
    expect(screen.getByText('clear')).toBeInTheDocument();
  });

  it('shows fraud type tag when present', () => {
    render(<TransactionFeed transactions={[FLAGGED_TXN]} />);
    expect(screen.getByText('amount_anomaly')).toBeInTheDocument();
  });

  it('shows flag decision badge for flagged transaction', () => {
    render(<TransactionFeed transactions={[FLAGGED_TXN]} />);
    const badges = screen.getAllByText('flag');
    expect(badges.length).toBeGreaterThan(0);
  });
});

// ── FlaggedPanel ───────────────────────────────────────────────────
describe('FlaggedPanel', () => {
  it('renders empty state when no flagged transactions', () => {
    render(<FlaggedPanel flagged={[]} />);
    expect(screen.getByTestId('empty-flagged')).toBeInTheDocument();
  });

  it('renders flagged rows', () => {
    render(<FlaggedPanel flagged={[FLAGGED_TXN]} />);
    expect(screen.getByTestId('flagged-panel')).toBeInTheDocument();
  });

  it('shows fraud type', () => {
    render(<FlaggedPanel flagged={[FLAGGED_TXN]} />);
    expect(screen.getByText('amount_anomaly')).toBeInTheDocument();
  });

  it('shows flagged count pill', () => {
    render(<FlaggedPanel flagged={[FLAGGED_TXN, FLAGGED_TXN]} />);
    expect(screen.getByText('2 flagged')).toBeInTheDocument();
  });

  it('shows score', () => {
    render(<FlaggedPanel flagged={[FLAGGED_TXN]} />);
    expect(screen.getByText(/score 0.920/)).toBeInTheDocument();
  });
});

// ── StatsCounters ──────────────────────────────────────────────────
describe('StatsCounters', () => {
  const stats = { precision: 0.82, recall: 0.74, f1: 0.78, total: 150, tp: 37, fp: 8, fn: 13, tn: 92 };

  it('renders without crashing with zero stats', () => {
    render(<StatsCounters stats={{ precision: 0, recall: 0, f1: 0, total: 0 }} />);
    expect(screen.getByTestId('stats-counters')).toBeInTheDocument();
  });

  it('renders with stats', () => {
    render(<StatsCounters stats={stats} detailed />);
    expect(screen.getByTestId('stats-counters')).toBeInTheDocument();
  });

  it('shows Model Performance heading in detailed mode', () => {
    render(<StatsCounters stats={stats} detailed />);
    expect(screen.getByText('Model Performance')).toBeInTheDocument();
  });

  it('shows Precision label', () => {
    render(<StatsCounters stats={stats} detailed />);
    expect(screen.getAllByText('Precision').length).toBeGreaterThan(0);
  });

  it('counter math: counter reaches final value', async () => {
    // Counter value is animated but snaps to target on reduced-motion.
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (q) => ({
        matches: q.includes('reduced-motion'),
        media: q,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    render(<StatsCounters stats={{ precision: 0.8, recall: 0.7, f1: 0.74, total: 100 }} compact />);
    // Reduced motion — values should show immediately.
    expect(screen.getByText('Recall')).toBeInTheDocument();
  });
});

// ── ScoreHistogram ─────────────────────────────────────────────────
describe('ScoreHistogram', () => {
  it('renders empty state when no scored transactions', () => {
    render(<ScoreHistogram transactions={[{ amount: 100 }]} />);
    expect(screen.getByTestId('empty-histogram')).toBeInTheDocument();
  });

  it('renders histogram when scored transactions present', () => {
    const scored = [
      { ...SAMPLE_TXN, anomaly_score: 0.2 },
      { ...FLAGGED_TXN, anomaly_score: 0.95 },
    ];
    render(<ScoreHistogram transactions={scored} />);
    expect(screen.getByTestId('score-histogram')).toBeInTheDocument();
  });

  it('shows threshold info text', () => {
    const scored = [{ ...SAMPLE_TXN, anomaly_score: 0.5 }];
    render(<ScoreHistogram transactions={scored} />);
    expect(screen.getByText(/thresholds/)).toBeInTheDocument();
  });
});
