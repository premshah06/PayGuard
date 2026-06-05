"""
PayGuard Kafka consumer.

Reads raw transactions from the "transactions" topic, forwards each
to the inference sidecar for feature engineering + ONNX scoring, and
writes the scored result to the PostgreSQL audit log.

The consumer is intentionally stateless — feature engineering state
lives inside the inference sidecar (and would be Redis-backed in
production), while durable state lives in PostgreSQL.

Environment variables:
    KAFKA_BOOTSTRAP_SERVERS   default: localhost:9092
    KAFKA_TOPIC               default: transactions
    KAFKA_GROUP_ID            default: payguard-consumer
    INFERENCE_URL             default: http://localhost:8000
    DATABASE_URL              default: postgresql://…
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import asyncpg
import httpx
from aiokafka import AIOKafkaConsumer

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "payguard-consumer")
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://localhost:8000")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://payguard:payguard_secret@localhost:5432/payguard",
)

# -------------------------------------------------------------------
# Database helpers
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


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)


async def write_audit(pool: asyncpg.Pool, txn: dict, score_resp: dict) -> None:
    """Upsert a scored transaction into the audit log."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO transaction_audit
                (transaction_id, user_id, amount, merchant_category,
                 anomaly_score, decision, ground_truth_label, fraud_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (transaction_id) DO UPDATE
                SET anomaly_score = EXCLUDED.anomaly_score,
                    decision      = EXCLUDED.decision
            """,
            txn["transaction_id"],
            txn["user_id"],
            float(txn["amount"]),
            txn["merchant_category"],
            float(score_resp["anomaly_score"]),
            score_resp["decision"],
            txn.get("ground_truth_label"),
            txn.get("fraud_type"),
        )


# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------


async def consume() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await ensure_schema(pool)

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="latest",
    )
    await consumer.start()
    print(f"[consumer] listening  topic={KAFKA_TOPIC}  group={KAFKA_GROUP_ID}")

    async with httpx.AsyncClient(base_url=INFERENCE_URL, timeout=5.0) as client:
        try:
            async for msg in consumer:
                txn: dict = msg.value
                try:
                    resp = await client.post("/score", json=txn)
                    resp.raise_for_status()
                    score_resp = resp.json()
                    await write_audit(pool, txn, score_resp)
                    if score_resp["decision"] == "flag":
                        ts = datetime.now(UTC).isoformat()
                        print(
                            f"[consumer] FLAGGED  txn={txn['transaction_id'][:8]}…  "
                            f"score={score_resp['anomaly_score']:.3f}  "
                            f"type={txn.get('fraud_type', '?')}  at={ts}"
                        )
                except Exception as exc:  # noqa: BLE001
                    print(f"[consumer] ERROR processing {txn.get('transaction_id')}: {exc}")
        finally:
            await consumer.stop()
            await pool.close()


if __name__ == "__main__":
    asyncio.run(consume())
