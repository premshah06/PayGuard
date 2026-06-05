"""
Integration tests: score → audit-log write → retrieve.

These tests mock the database and inference sidecar to run without
external services, but exercise the full request path through the API
including serialisation, business logic, and DB write calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response

API_KEY = "dev-secret-key"

SAMPLE_TXN = {
    "transaction_id": "integ-txn-001",
    "user_id": "integ-user-1",
    "amount": 9999.00,
    "merchant_category": "electronics",
    "location": {"city": "Tokyo", "country": "JP", "lat": 35.68, "lng": 139.65},
    "timestamp": "2024-06-10T03:15:00+00:00",
    "device": "web",
    "card_present": False,
    "ground_truth_label": 1,
    "fraud_type": "amount_anomaly",
}

SCORE_RESPONSE = {
    "transaction_id": "integ-txn-001",
    "anomaly_score": 0.93,
    "decision": "flag",
    "features_used": {
        "amount": 9999.0,
        "hour_of_day": 3.0,
        "is_weekend": 0.0,
        "amount_vs_user_avg": 12.5,
        "txns_last_5min": 0.0,
        "distance_from_home_km": 6234.5,
        "merchant_category_encoded": 8.0,
    },
}


@pytest.fixture
def integration_client():
    """Full app fixture with mocked asyncpg and inference sidecar."""
    with patch("asyncpg.create_pool") as mock_pool_factory, \
         patch("httpx.AsyncClient") as mock_httpx:

        pool = AsyncMock()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchval = AsyncMock(return_value=1)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        pool.close = AsyncMock()
        mock_pool_factory.return_value = pool

        http_client = AsyncMock()
        http_client.aclose = AsyncMock()
        http_client.post = AsyncMock(
            return_value=Response(200, json=SCORE_RESPONSE)
        )
        mock_httpx.return_value = http_client

        import api.main as api_module
        api_module._db_pool = pool
        api_module._http_client = http_client

        from api.main import app
        with TestClient(app) as client:
            yield client, pool, conn, http_client


class TestScoreToAuditLog:
    def test_score_writes_to_db(self, integration_client):
        client, pool, conn, http_client = integration_client
        resp = client.post(
            "/api/score",
            json=SAMPLE_TXN,
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        # Verify DB write was called
        conn.execute.assert_called()

    def test_score_response_contains_decision(self, integration_client):
        client, *_ = integration_client
        resp = client.post(
            "/api/score",
            json=SAMPLE_TXN,
            headers={"X-API-Key": API_KEY},
        )
        data = resp.json()
        assert data["decision"] == "flag"
        assert data["anomaly_score"] == pytest.approx(0.93)

    def test_inference_sidecar_called_with_txn(self, integration_client):
        client, pool, conn, http_client = integration_client
        client.post(
            "/api/score",
            json=SAMPLE_TXN,
            headers={"X-API-Key": API_KEY},
        )
        http_client.post.assert_called_once()
        call_kwargs = http_client.post.call_args
        assert "/score" in str(call_kwargs)

    def test_retrieve_returns_list(self, integration_client):
        client, pool, conn, _ = integration_client
        conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/transactions", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_flagged_endpoint_filters(self, integration_client):
        client, pool, conn, _ = integration_client
        conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/flagged", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        # Verify the query fetches from fetch (DB)
        conn.fetch.assert_called()

    def test_health_check_after_score(self, integration_client):
        client, pool, conn, _ = integration_client
        # Score a transaction
        client.post("/api/score", json=SAMPLE_TXN, headers={"X-API-Key": API_KEY})
        # Health check should still pass
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_stats_computation(self, integration_client):
        """Stats endpoint should compute metrics even with mock data."""
        client, pool, conn, _ = integration_client
        # Return a mock stats aggregate row
        mock_row = {
            "tp": 8, "fp": 3, "fn": 4, "tn": 85, "total": 100
        }
        conn.fetch = AsyncMock(return_value=[mock_row])
        resp = client.get("/api/stats", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        data = resp.json()
        assert 0.0 <= data.get("precision", 0) <= 1.0
        assert 0.0 <= data.get("recall", 0) <= 1.0
        assert 0.0 <= data.get("f1", 0) <= 1.0
