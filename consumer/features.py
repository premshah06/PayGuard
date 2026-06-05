"""
Feature engineering pipeline for PayGuard.

Computes 7 features per transaction from the raw event + per-user rolling state.
All pure functions are unit-testable in isolation.

NOTE: Per-user state is held in an in-memory dict here for simplicity.
      Replace _USER_STATE with Redis at production scale to support
      horizontal scaling and state persistence across restarts.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import UTC, datetime
from typing import Any

# -------------------------------------------------------------------
# Merchant category encoding
# -------------------------------------------------------------------

MERCHANT_CATEGORIES: list[str] = [
    "grocery",
    "restaurant",
    "gas_station",
    "online_retail",
    "pharmacy",
    "entertainment",
    "travel",
    "clothing",
    "electronics",
    "healthcare",
]

_MC_INDEX: dict[str, int] = {cat: idx for idx, cat in enumerate(MERCHANT_CATEGORIES)}

# Ordered list of feature names — must match the column order used during training.
FEATURE_ORDER: list[str] = [
    "amount",
    "hour_of_day",
    "is_weekend",
    "amount_vs_user_avg",
    "txns_last_5min",
    "distance_from_home_km",
    "merchant_category_encoded",
]


# -------------------------------------------------------------------
# Haversine distance — standalone so it can be unit-tested independently
# -------------------------------------------------------------------


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two lat/lng points.

    Uses the Haversine formula (numerically stable for small angles).
    """
    R = 6_371.0  # Earth mean radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# -------------------------------------------------------------------
# Merchant encoding
# -------------------------------------------------------------------


def encode_merchant(category: str) -> int:
    """Label-encode a merchant category. Unknown categories return -1."""
    return _MC_INDEX.get(category, -1)


# -------------------------------------------------------------------
# Per-user rolling state
# -------------------------------------------------------------------


class UserState:
    """Rolling behavioural baseline for a single user.

    Tracks a sliding window of recent transaction timestamps (for velocity)
    and a bounded deque of recent amounts (for running average).

    NOTE: Replace with a Redis-backed implementation at production scale.
    """

    def __init__(self, profile: dict[str, Any] | None = None) -> None:
        # Bounded deque of recent transaction amounts (max 50 kept).
        self._amounts: deque[float] = deque(maxlen=50)
        # Bounded deque of recent transaction datetimes (max 500 kept).
        self._recent_ts: deque[datetime] = deque(maxlen=500)
        # Home location; bootstrapped from profile or inferred on first transaction.
        self.home_lat: float | None = None
        self.home_lng: float | None = None

        if profile:
            self.home_lat = profile["home_location"]["lat"]
            self.home_lng = profile["home_location"]["lng"]
            # Seed average with the profile's known mean so early transactions
            # have a meaningful baseline rather than defaulting to 1.
            self._amounts.append(float(profile["avg_amount"]))

    # ------------------------------------------------------------------

    def update(self, amount: float, ts: datetime, lat: float, lng: float) -> None:
        """Record a completed transaction into rolling state."""
        self._amounts.append(amount)
        self._recent_ts.append(ts)
        # Latch home location from the first transaction if not set via profile.
        if self.home_lat is None:
            self.home_lat = lat
            self.home_lng = lng

    @property
    def rolling_avg_amount(self) -> float:
        """Running mean of recent transaction amounts. Returns 1.0 when empty
        to avoid division-by-zero in downstream features."""
        if not self._amounts:
            return 1.0
        return sum(self._amounts) / len(self._amounts)

    def txns_in_window(self, ts: datetime, window_sec: int = 300) -> int:
        """Count transactions that occurred within the last *window_sec* seconds
        before *ts* (exclusive of *ts* itself)."""
        cutoff = ts.timestamp() - window_sec
        return sum(1 for t in self._recent_ts if t.timestamp() >= cutoff)


# -------------------------------------------------------------------
# Global in-memory state store
# NOTE: Replace with Redis at production scale.
# -------------------------------------------------------------------

_USER_STATE: dict[str, UserState] = {}


def reset_state() -> None:
    """Wipe all per-user state. Useful between training and evaluation runs."""
    _USER_STATE.clear()


def get_or_create_state(user_id: str, profile: dict[str, Any] | None = None) -> UserState:
    """Return the existing UserState for *user_id* or create a new one."""
    if user_id not in _USER_STATE:
        _USER_STATE[user_id] = UserState(profile)
    return _USER_STATE[user_id]


# -------------------------------------------------------------------
# Core feature engineering function
# -------------------------------------------------------------------


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string. Forces UTC if no tzinfo is present."""
    dt = datetime.fromisoformat(ts_str)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def engineer_features(
    txn: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Compute the 7 model features for a single raw transaction.

    Features are computed *before* updating the user's rolling state so that
    the velocity and average values reflect history up to (but not including)
    the current transaction — consistent with how the model is evaluated in
    production where the current transaction hasn't "settled" yet.

    Args:
        txn:     Raw transaction dict (from Kafka or synthetic generator).
        profile: Optional pre-seeded user profile for bootstrapping state.

    Returns:
        Dict mapping feature name → float value.
    """
    user_id: str = txn["user_id"]
    amount: float = float(txn["amount"])
    ts: datetime = _parse_ts(txn["timestamp"])
    lat: float = float(txn["location"]["lat"])
    lng: float = float(txn["location"]["lng"])
    merchant: str = txn["merchant_category"]

    state = get_or_create_state(user_id, profile)

    # ---- Features computed from state BEFORE updating ---------------

    # 1. Raw transaction amount
    feature_amount = amount

    # 2. Hour of day (0–23)
    hour_of_day = float(ts.hour)

    # 3. Weekend indicator (Saturday=5, Sunday=6)
    is_weekend = float(ts.weekday() >= 5)

    # 4. Amount relative to user's rolling average — amplifies large deviations
    avg = state.rolling_avg_amount
    amount_vs_user_avg = amount / avg if avg > 0 else 1.0

    # 5. Transaction velocity: count of transactions in the last 5 minutes
    txns_last_5min = float(state.txns_in_window(ts, window_sec=300))

    # 6. Distance from user's home city in km (haversine)
    home_lat = state.home_lat if state.home_lat is not None else lat
    home_lng = state.home_lng if state.home_lng is not None else lng
    distance_from_home_km = haversine(lat, lng, home_lat, home_lng)

    # 7. Label-encoded merchant category
    merchant_category_encoded = float(encode_merchant(merchant))

    # ---- Update state AFTER reading features ------------------------
    state.update(amount, ts, lat, lng)

    return {
        "amount": feature_amount,
        "hour_of_day": hour_of_day,
        "is_weekend": is_weekend,
        "amount_vs_user_avg": amount_vs_user_avg,
        "txns_last_5min": txns_last_5min,
        "distance_from_home_km": distance_from_home_km,
        "merchant_category_encoded": merchant_category_encoded,
    }


def features_to_vector(features: dict[str, float]) -> list[float]:
    """Return features as an ordered list aligned with FEATURE_ORDER.

    This is what gets passed to the ONNX model as a 1-D input row.
    """
    return [features[k] for k in FEATURE_ORDER]
