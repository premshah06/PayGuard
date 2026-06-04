"""
Shared pytest fixtures for PayGuard test suite.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Make sure repo root is on the path so all modules are importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from consumer.features import reset_state  # noqa: E402
from producer.generator import make_user_profiles  # noqa: E402


@pytest.fixture(autouse=True)
def clear_user_state():
    """Reset the in-memory per-user state before every test so tests are
    independent of each other."""
    reset_state()
    yield
    reset_state()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


@pytest.fixture
def profiles(rng: random.Random):
    return make_user_profiles(20, rng)


@pytest.fixture
def sample_user_id(profiles) -> str:
    return next(iter(profiles))


@pytest.fixture
def normal_txn(sample_user_id: str, profiles) -> dict:
    profile = profiles[sample_user_id]
    return {
        "transaction_id": "txn-test-001",
        "user_id": sample_user_id,
        "amount": profile["avg_amount"],
        "merchant_category": profile["typical_merchants"][0],
        "location": {
            "city": "New York",
            "country": "US",
            "lat": profile["home_location"]["lat"],
            "lng": profile["home_location"]["lng"],
        },
        "timestamp": datetime(2024, 6, 10, 14, 30, 0, tzinfo=timezone.utc).isoformat(),
        "device": "mobile",
        "card_present": True,
        "ground_truth_label": 0,
        "fraud_type": None,
    }
