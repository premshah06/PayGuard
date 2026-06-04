"""
API endpoint tests.

Uses FastAPI's TestClient (sync) and httpx AsyncClient for async routes.
PostgreSQL and the inference sidecar are mocked via dependency overrides
and httpx mock transport.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

# -------------------------------------------------------------------
# We mock asyncpg and the inference sidecar before importing the app
# so no real network connections are attempted.
# -------------------------------------------------------------------

# Minimal asyncpg mock
_mock_rows_transactions = [
    {
        "transaction_id": "txn-001",
        "user_id": "user-1",
        "amount": 100.0,
        "merchant_category": "grocery",
        "anomaly_score": 0.3,
        "decision": "clear",
        "ground_truth_label": 0,
        "fraud_type": None,
        "created_at": "2024-06-10T14:00:00+00:00",
    }
]


@pytest.fixture
def mock_db_pool(monkeypatch):
    """Replace asyncpg pool calls with a mock that returns canned data."""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    # fetch returns list of Record-like dicts
    mock_conn.fetch = AsyncMock(
        return_value=[type("Row", (), {"__iter__": lambda s: iter([]), **r})()
                      for r in _mock_rows_transactions]
    )

    # For single-row queries return the stats row
    mock_stats_row = {
        "tp": 10, "fp": 2, "fn": 5, "tn": 83, "total": 100
    }
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.execute = AsyncMock(return_value=None)

    return mock_pool, mock_conn


@pytest.fixture
def api_client():
    """Create a FastAPI TestClient with mocked external dependencies."""
    # We need to patch asyncpg.create_pool and httpx.AsyncClient before
    # importing the app (or before lifespan fires).
    with patch("asyncpg.create_pool") as mock_create_pool, \
         patch("httpx.AsyncClient") as mock_httpx:

        # asyncpg pool mock
        pool = AsyncMock()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchval = AsyncMock(return_value=1)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        pool.close = AsyncMock()
        mock_create_pool.return_value = pool

        # httpx client mock (inference sidecar)
        http_client = AsyncMock()
        http_client.aclose = AsyncMock()
        http_client.post = AsyncMock(
            return_value=Response(
                200,
                json={
                    "transaction_id": "txn-test",
                    "anomaly_score": 0.92,
                    "decision": "flag",
                    "features_used": {},
                },
            )
        )
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=http_client)
        mock_httpx.return_value = http_client

        from api.main import app, _db_pool, _http_client
        import api.main as api_module

        # Inject mocks directly
        api_module._db_pool = pool
        api_module._http_client = http_client

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client, pool, conn, http_client


API_KEY = "dev-secret-key"


# -------------------------------------------------------------------
# /health — no auth required
# -------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, api_client):
        client, pool, conn, _ = api_client
        conn.fetchval = AsyncMock(return_value=1)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_no_auth_needed(self, api_client):
        client, *_ = api_client
        resp = client.get("/health")
        # Must not return 403
        assert resp.status_code != 403

    def test_health_response_has_status(self, api_client):
        client, *_ = api_client
        data = client.get("/health").json()
        assert "status" in data


# -------------------------------------------------------------------
# Auth — X-API-Key enforcement
# -------------------------------------------------------------------

class TestAuth:
    PROTECTED = [
        ("GET", "/api/transactions"),
        ("GET", "/api/flagged"),
        ("GET", "/api/stats"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_missing_key_returns_403(self, api_client, method, path):
        client, *_ = api_client
        resp = getattr(client, method.lower())(path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_wrong_key_returns_403(self, api_client, method, path):
        client, *_ = api_client
        resp = getattr(client, method.lower())(path, headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_valid_key_not_403(self, api_client, method, path):
        client, pool, conn, _ = api_client
        conn.fetch = AsyncMock(return_value=[])
        resp = getattr(client, method.lower())(path, headers={"X-API-Key": API_KEY})
        assert resp.status_code != 403


# -------------------------------------------------------------------
# GET /api/transactions
# -------------------------------------------------------------------

class TestTransactions:
    def test_returns_list(self, api_client):
        client, pool, conn, _ = api_client
        conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/transactions", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_accepts_limit_param(self, api_client):
        client, pool, conn, _ = api_client
        conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/transactions?limit=10", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200

    def test_limit_too_large_rejected(self, api_client):
        client, *_ = api_client
        resp = client.get("/api/transactions?limit=9999", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 422


# -------------------------------------------------------------------
# GET /api/flagged
# -------------------------------------------------------------------

class TestFlagged:
    def test_returns_list(self, api_client):
        client, pool, conn, _ = api_client
        conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/flagged", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# -------------------------------------------------------------------
# GET /api/stats
# -------------------------------------------------------------------

class TestStats:
    def test_returns_stats_keys(self, api_client):
        client, pool, conn, _ = api_client
        # Simulate a stats row return
        stats_row = MagicMock()
        stats_row.__getitem__ = lambda s, k: {
            "tp": 10, "fp": 2, "fn": 5, "tn": 83, "total": 100
        }[k]
        conn.fetch = AsyncMock(return_value=[stats_row])
        resp = client.get("/api/stats", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200

    def test_empty_db_returns_zeros(self, api_client):
        client, pool, conn, _ = api_client
        conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/stats", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        data = resp.json()
        assert "precision" in data
        assert "recall" in data
        assert "f1" in data


# -------------------------------------------------------------------
# POST /api/score
# -------------------------------------------------------------------

class TestScore:
    SCORE_PAYLOAD = {
        "transaction_id": "txn-x001",
        "user_id": "user-abc",
        "amount": 50.00,
        "merchant_category": "grocery",
        "location": {"city": "NY", "country": "US", "lat": 40.7, "lng": -74.0},
        "timestamp": "2024-06-10T14:30:00+00:00",
        "device": "mobile",
        "card_present": True,
        "ground_truth_label": 0,
        "fraud_type": None,
    }

    def test_requires_auth(self, api_client):
        client, *_ = api_client
        resp = client.post("/api/score", json=self.SCORE_PAYLOAD)
        assert resp.status_code == 403

    def test_returns_score(self, api_client):
        client, pool, conn, http_client = api_client
        conn.execute = AsyncMock(return_value=None)
        resp = client.post(
            "/api/score",
            json=self.SCORE_PAYLOAD,
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "anomaly_score" in data
        assert "decision" in data
