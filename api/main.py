"""
PayGuard REST API + WebSocket server.

Serves scored transaction data from PostgreSQL and proxies ad-hoc
scoring requests to the inference sidecar.

Auth: X-API-Key header required on all routes except GET /health.
      Key is read from the API_KEY environment variable.

Endpoints:
    GET  /health                — liveness; no auth
    GET  /api/transactions      — recent scored transactions
    GET  /api/flagged           — decision='flag' rows only
    GET  /api/stats             — precision / recall / F1 over last hour
    POST /api/score             — proxy to inference sidecar + audit log
    WS   /ws                   — live stream of flagged transactions
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://payguard:payguard_secret@localhost:5432/payguard",
)
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "dev-secret-key")

# -------------------------------------------------------------------
# Schema DDL (idempotent — also run by consumer on startup)
# -------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS transaction_audit (
    transaction_id     TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    amount             NUMERIC(12, 2),
    merchant_category  TEXT,
    anomaly_score      DOUBLE PRECISION,
    decision           TEXT,
    ground_truth_label INTEGER,
    fraud_type         TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ta_user_created
    ON transaction_audit (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ta_decision
    ON transaction_audit (decision);
"""

# -------------------------------------------------------------------
# App lifecycle + shared resources
# -------------------------------------------------------------------

_db_pool: asyncpg.Pool | None = None
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db_pool, _http_client
    _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=20)
    async with _db_pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    _http_client = httpx.AsyncClient(base_url=INFERENCE_URL, timeout=10.0)
    print("[api] startup complete")
    yield
    await _http_client.aclose()
    await _db_pool.close()


app = FastAPI(title="PayGuard API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Auth
# -------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Depends(_api_key_header)) -> None:
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key")


# -------------------------------------------------------------------
# WebSocket connection manager
# -------------------------------------------------------------------


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        dead: set[WebSocket] = set()
        msg = json.dumps(payload)
        for ws in list(self._active):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001
                dead.add(ws)
        self._active -= dead


_ws_manager = ConnectionManager()

# -------------------------------------------------------------------
# DB helpers — graceful fallback on any failure
# -------------------------------------------------------------------


async def _fetch(query: str, *args) -> list[dict]:
    if _db_pool is None:
        return []
    try:
        async with _db_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        print(f"[api] DB error: {exc}")
        return []


async def _execute(query: str, *args) -> None:
    if _db_pool is None:
        return
    try:
        async with _db_pool.acquire() as conn:
            await conn.execute(query, *args)
    except Exception as exc:  # noqa: BLE001
        print(f"[api] DB write error: {exc}")


# -------------------------------------------------------------------
# Request / response models
# -------------------------------------------------------------------


class ScoreRequest(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    merchant_category: str
    location: dict[str, Any]
    timestamp: str
    device: str
    card_present: bool
    ground_truth_label: int | None = None
    fraud_type: str | None = None


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    """Liveness probe — no auth required."""
    db_ok = False
    if _db_pool:
        try:
            async with _db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            pass
    return {"status": "ok", "db_connected": db_ok, "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/transactions", dependencies=[Depends(require_api_key)])
async def get_transactions(limit: int = Query(default=50, le=500)) -> list[dict]:
    """Return the most recent *limit* scored transactions."""
    return await _fetch(
        "SELECT * FROM transaction_audit ORDER BY created_at DESC LIMIT $1",
        limit,
    )


@app.get("/api/flagged", dependencies=[Depends(require_api_key)])
async def get_flagged(limit: int = Query(default=100, le=1000)) -> list[dict]:
    """Return transactions with decision='flag', newest first."""
    return await _fetch(
        "SELECT * FROM transaction_audit WHERE decision = 'flag' "
        "ORDER BY created_at DESC LIMIT $1",
        limit,
    )


@app.get("/api/stats", dependencies=[Depends(require_api_key)])
async def get_stats() -> dict:
    """Compute precision / recall / F1 over the last hour using the
    audit log ground-truth labels as the reference signal."""
    rows = await _fetch(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE ground_truth_label = 1 AND decision IN ('flag', 'review')
            ) AS tp,
            COUNT(*) FILTER (
                WHERE ground_truth_label = 0 AND decision IN ('flag', 'review')
            ) AS fp,
            COUNT(*) FILTER (
                WHERE ground_truth_label = 1 AND decision = 'clear'
            ) AS fn,
            COUNT(*) FILTER (
                WHERE ground_truth_label = 0 AND decision = 'clear'
            ) AS tn,
            COUNT(*) AS total
        FROM transaction_audit
        WHERE created_at >= NOW() - INTERVAL '1 hour'
          AND ground_truth_label IS NOT NULL
        """
    )
    if not rows:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "total": 0}

    r = rows[0]
    tp, fp, fn, tn, total = int(r["tp"]), int(r["fp"]), int(r["fn"]), int(r["tn"]), int(r["total"])
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "total": total,
        "window": "1h",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/score", dependencies=[Depends(require_api_key)])
async def score_transaction(req: ScoreRequest) -> dict:
    """Proxy a raw transaction to the inference sidecar, write result to
    the audit log, and broadcast flagged transactions over WebSocket."""
    if _http_client is None:
        raise HTTPException(status_code=503, detail="HTTP client not initialised")

    try:
        resp = await _http_client.post("/score", json=req.model_dump())
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Inference sidecar error: {exc}") from exc

    score_resp = resp.json()

    await _execute(
        """
        INSERT INTO transaction_audit
            (transaction_id, user_id, amount, merchant_category,
             anomaly_score, decision, ground_truth_label, fraud_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (transaction_id) DO UPDATE
            SET anomaly_score = EXCLUDED.anomaly_score,
                decision      = EXCLUDED.decision
        """,
        req.transaction_id,
        req.user_id,
        req.amount,
        req.merchant_category,
        float(score_resp["anomaly_score"]),
        score_resp["decision"],
        req.ground_truth_label,
        req.fraud_type,
    )

    if score_resp["decision"] == "flag":
        broadcast_payload = {
            **score_resp,
            "user_id": req.user_id,
            "amount": req.amount,
            "merchant_category": req.merchant_category,
            "fraud_type": req.fraud_type,
            "ground_truth_label": req.ground_truth_label,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        }
        asyncio.create_task(_ws_manager.broadcast(broadcast_payload))

    return score_resp


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Live stream of flagged transactions. Clients do not need auth
    (WebSocket headers are awkward in browsers); the data contains no PII."""
    await _ws_manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; data is pushed by broadcast().
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_manager.disconnect(ws)
