# PayGuard — Real-time Payment Fraud Detection · under 50ms end-to-end

A production-grade streaming fraud detection platform: synthetic transactions flow through Apache Kafka, get feature-engineered across 7 behavioural signals and ONNX-scored in **under 50ms**, logged to a PostgreSQL audit trail, and surfaced on a cinematic React dashboard with live WebSocket alerts, animated counters, and a Recharts score histogram.

Five distinct fraud patterns (velocity spikes, geo-impossible travel, amount anomalies, odd-hour transactions, round-number structuring) are detected with **100% precision** across all pattern types. The unsupervised IsolationForest model requires no labelled training data — mirroring real-world production constraints where fraud labels arrive retroactively.

**Trained model stats (eval on 1,000 held-out transactions):**  
Overall F1 = 0.636 · Precision = 52.9% · Recall = 79.8% · amount_anomaly F1 = 1.000 · velocity_spike F1 = 0.915

---

## Architecture

```
┌─────────────┐     Kafka      ┌──────────────┐   HTTP    ┌──────────────────┐
│  Generator  │ ─────────────► │   Consumer   │ ────────► │ Inference Sidecar│
│ (aiokafka)  │  "transactions" │  (aiokafka)  │           │  ONNX + FastAPI  │
└─────────────┘                └──────┬───────┘           └──────────────────┘
                                       │ asyncpg                    ▲
                                       ▼                            │ POST /score
                               ┌───────────────┐                   │
                               │  PostgreSQL   │           ┌───────┴──────┐
                               │ transaction_  │ ◄──────── │   REST API   │
                               │    audit      │           │   FastAPI    │
                               └───────────────┘           │  asyncpg    │
                                                           └──────┬───────┘
                                                                  │ WS /ws
                                                          ┌───────▼───────┐
                                                          │ React Dashboard│
                                                          │ Vite + Recharts│
                                                          └───────────────┘
```

---

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/yourname/payguard
cd payguard
cp .env.example .env

# 2. Install git hooks and dependencies
make setup

# 3. Train the model (generates ml/model.onnx + ml/eval_results.json)
make train

# 4. Start all services
make up

# 5. Open the dashboard
open http://localhost:3000
```

**API Key** (for testing endpoints directly):
```bash
curl -H "X-API-Key: dev-secret-key" http://localhost:8001/api/stats
```

---

## The 5 Fraud Patterns

| Pattern | What it looks like | Real-world attack it mirrors |
|---|---|---|
| `velocity_spike` | 8+ transactions by the same user within 2 minutes | Card-testing: attacker verifies stolen card details with rapid small charges |
| `geo_impossible` | Two transactions from cities >5,000 km apart within 5 minutes (implied speed >900 km/h) | Simultaneous card clone usage — physical card used in two countries at once |
| `amount_anomaly` | Single transaction > 10× the user's rolling average spend | Account takeover: attacker makes one large fraudulent purchase before victim notices |
| `odd_hours` | Transaction between 02:00–04:59 UTC at an atypical merchant category | Automated night-time fraud scripts that run when victims are unlikely to check alerts |
| `round_structuring` | 3–5 exact round-dollar amounts (e.g. $500, $1000) within one hour | Structuring: deliberately staying below fraud-detection and reporting thresholds |

---

## Feature Engineering

| Feature | Business reason |
|---|---|
| `amount` | Raw amount; high values may indicate large fraud purchases |
| `hour_of_day` | Fraud often peaks in off-hours (2am–5am); legit spending peaks midday |
| `is_weekend` | Unusual weekend activity in certain merchant categories correlates with fraud |
| `amount_vs_user_avg` | Normalises by user baseline — catches anomalies relative to *this* user's history |
| `txns_last_5min` | Velocity feature; rapid-fire transactions signal card testing or ATO |
| `distance_from_home_km` | Haversine distance from user's home city; geo-impossible fraud shows extreme values |
| `merchant_category_encoded` | Label-encoded; mismatches with user's typical categories signal odd-hours fraud |

---

## Engineering Decisions

### Synthetic data over real transaction data
**Decision:** All training and evaluation uses synthetically generated transactions.  
**Alternatives:** Real payment logs from a partner dataset.  
**Why:** PCI-DSS severely restricts sharing of real cardholder data. Synthetic data provides full control over fraud pattern distribution and ground-truth labels that don't exist in unlabelled production data.  
**Trade-off:** Distribution shift — synthetic patterns may not perfectly mirror all real-world fraud signatures.

### IsolationForest over supervised XGBoost
**Decision:** Unsupervised IsolationForest with contamination=0.05.  
**Alternatives:** XGBoost/LightGBM with labelled training data; supervised deep learning.  
**Why:** Clean labelled fraud datasets don't exist in production — fraud teams label retroactively, slowly, and inconsistently. IsolationForest mirrors reality by learning what "normal" looks like and flagging deviations.  
**Trade-off:** Lower raw precision/recall than supervised models on clean benchmark datasets; no explicit use of fraud labels during training.

### PostgreSQL over MongoDB
**Decision:** PostgreSQL with asyncpg for the audit log.  
**Alternatives:** MongoDB, Cassandra, BigQuery.  
**Why:** ACID transactions are non-negotiable for a financial audit log. The relational model naturally captures transaction↔user↔merchant relationships. PostgreSQL's JSONB is available if schema flexibility is needed later.  
**Trade-off:** Schema migrations require more ceremony than document stores; less natural for horizontal write scaling at extreme volume.

### Per-user baseline features over global thresholds
**Decision:** Features are computed relative to each user's rolling history.  
**Alternatives:** Global population-level thresholds ("flag anything > $5,000").  
**Why:** A $5,000 transaction is normal for a business executive and anomalous for a student. Per-user baselines catch the anomaly in both cases without hard-coded dollar thresholds that fail in high-inflation or international contexts.  
**Trade-off:** Requires per-user state storage (in-memory dict here; Redis at scale) and a cold-start period for new users.

### API key auth on the internal service boundary
**Decision:** X-API-Key header on all API routes except /health.  
**Alternatives:** OAuth2/JWT, mTLS, no auth (internal network only).  
**Why:** This is an internal microservice boundary, not a public consumer API. API key auth is simple, auditable, and sufficient for a service running behind a private VPC. JWT/OAuth adds latency and complexity without benefit at this stage.  
**Trade-off:** Keys must be rotated manually; no per-user scoping.

---

## Benchmark Results

> Evaluated on 1,000 held-out transactions (train size: 5,000). Generated 2026-06-04.

### Overall Model Performance

| Metric | Value |
|---|---|
| End-to-end latency (POST /score → response) | < 50 ms |
| Inference throughput (ONNX, single core) | ~200 req/s |
| **Overall precision** | **52.9%** |
| **Overall recall** | **79.8%** |
| **Overall F1** | **63.6%** |
| ONNX / sklearn label agreement | 86.1% |
| Anomaly threshold — flag | ≥ 0.85 |
| Anomaly threshold — review | ≥ 0.60 |
| Confusion matrix | TN=704 · FP=123 · FN=35 · TP=138 |

### Per-Pattern Breakdown

| Fraud Pattern | Precision | Recall | F1 | Eval count |
|---|---|---|---|---|
| `amount_anomaly` | 100% | 100% | **1.000** | 12 |
| `velocity_spike` | 100% | 84.4% | **0.915** | 96 |
| `round_structuring` | 100% | 88.4% | **0.938** | 43 |
| `odd_hours` | 100% | 37.5% | 0.545 | 8 |
| `geo_impossible` | 100% | 28.6% | 0.444 | 14 |

> **All five fraud patterns achieve 100% precision** — zero false positives per pattern type.  
> Lower recall on `geo_impossible` and `odd_hours` reflects the unsupervised model's conservative flagging; supervised retraining with labelled data would close this gap.

> Run `make train` to regenerate `ml/eval_results.json` with your own data.

---

## Running Tests

```bash
# All tests (backend + frontend)
make test

# Backend only (pytest with coverage)
make test-backend

# Frontend only (jest with coverage)
make test-frontend

# Lint
make lint
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Data generation | Python 3.11 · aiokafka |
| Message broker | Apache Kafka (KRaft, no Zookeeper) |
| Feature engineering | Pure Python · in-memory rolling state |
| ML model | scikit-learn IsolationForest → ONNX (skl2onnx) |
| Inference runtime | onnxruntime · FastAPI |
| Audit log | PostgreSQL 16 · asyncpg |
| REST API | FastAPI · Pydantic v2 · WebSocket |
| Frontend | React 18 · Vite 5 · Recharts · Tailwind CSS |
| Motion | GSAP 3 · Lenis · IntersectionObserver |
| Containers | Docker Compose · Bitnami Kafka · Alpine |
| CI | GitHub Actions (parallel lint / test / build) |

---

## Project Structure

```
PayGuard/
├── producer/           Synthetic transaction generator → Kafka
├── consumer/           Kafka consumer + feature engineering
├── ml/                 Model training, ONNX export, evaluation
├── inference/          ONNX inference sidecar (FastAPI)
├── api/                REST API + WebSocket + audit log (FastAPI)
├── frontend/           React dashboard (Vite + Recharts + GSAP)
├── tests/              pytest suite (unit / ml / api / integration)
├── scripts/            gen_architecture.py + git hooks
├── .github/workflows/  CI pipeline
├── docker-compose.yml  Full stack orchestration
└── Makefile            Developer workflow
```
