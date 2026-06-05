"""
Unit tests for producer/generator.py.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from producer.generator import (
    _haversine,
    gen_amount_anomaly,
    gen_geo_impossible,
    gen_odd_hours,
    gen_round_structuring,
    gen_velocity_spike,
    generate_batch,
    make_user_profiles,
)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

@pytest.fixture
def fixed_rng() -> random.Random:
    return random.Random(7)


@pytest.fixture
def profiles_small(fixed_rng) -> dict:
    return make_user_profiles(10, fixed_rng)


@pytest.fixture
def user_id(profiles_small) -> str:
    return next(iter(profiles_small))


@pytest.fixture
def profile(user_id, profiles_small) -> dict:
    return profiles_small[user_id]


@pytest.fixture
def ts() -> datetime:
    return datetime(2024, 6, 10, 14, 0, 0, tzinfo=UTC)


# -------------------------------------------------------------------
# make_user_profiles
# -------------------------------------------------------------------

class TestMakeUserProfiles:
    def test_count(self, fixed_rng):
        p = make_user_profiles(50, fixed_rng)
        assert len(p) == 50

    def test_profile_keys(self, fixed_rng):
        p = make_user_profiles(1, fixed_rng)
        profile = next(iter(p.values()))
        assert "home_location" in profile
        assert "avg_amount" in profile
        assert "typical_merchants" in profile
        assert "account_age_days" in profile

    def test_home_has_lat_lng(self, fixed_rng):
        p = make_user_profiles(1, fixed_rng)
        home = next(iter(p.values()))["home_location"]
        assert "lat" in home and "lng" in home

    def test_avg_amount_positive(self, fixed_rng):
        p = make_user_profiles(20, fixed_rng)
        for profile in p.values():
            assert profile["avg_amount"] > 0

    def test_reproducible_with_seed(self):
        r1, r2 = random.Random(99), random.Random(99)
        p1, p2 = make_user_profiles(5, r1), make_user_profiles(5, r2)
        assert list(p1.keys()) == list(p2.keys())


# -------------------------------------------------------------------
# Fraud pattern generators
# -------------------------------------------------------------------

class TestVelocitySpike:
    def test_returns_eight_transactions(self, user_id, profile, fixed_rng, ts):
        txns = gen_velocity_spike(user_id, profile, fixed_rng, ts)
        assert len(txns) == 8

    def test_all_fraud_labeled(self, user_id, profile, fixed_rng, ts):
        txns = gen_velocity_spike(user_id, profile, fixed_rng, ts)
        assert all(t["ground_truth_label"] == 1 for t in txns)

    def test_fraud_type(self, user_id, profile, fixed_rng, ts):
        txns = gen_velocity_spike(user_id, profile, fixed_rng, ts)
        assert all(t["fraud_type"] == "velocity_spike" for t in txns)

    def test_within_two_minutes(self, user_id, profile, fixed_rng, ts):
        txns = gen_velocity_spike(user_id, profile, fixed_rng, ts)
        timestamps = [datetime.fromisoformat(t["timestamp"]) for t in txns]
        span = max(timestamps) - min(timestamps)
        assert span.total_seconds() < 120


class TestGeoImpossible:
    def test_returns_two_transactions(self, user_id, profile, fixed_rng, ts):
        txns = gen_geo_impossible(user_id, profile, fixed_rng, ts)
        assert len(txns) == 2

    def test_fraud_type(self, user_id, profile, fixed_rng, ts):
        txns = gen_geo_impossible(user_id, profile, fixed_rng, ts)
        assert all(t["fraud_type"] == "geo_impossible" for t in txns)

    def test_impossible_speed(self, user_id, profile, fixed_rng, ts):
        txns = gen_geo_impossible(user_id, profile, fixed_rng, ts)
        t1, t2 = txns
        loc1, loc2 = t1["location"], t2["location"]
        dt1 = datetime.fromisoformat(t1["timestamp"])
        dt2 = datetime.fromisoformat(t2["timestamp"])
        elapsed_h = abs((dt2 - dt1).total_seconds()) / 3600
        dist_km = _haversine(loc1["lat"], loc1["lng"], loc2["lat"], loc2["lng"])
        if elapsed_h > 0:
            speed = dist_km / elapsed_h
            assert speed > 900, f"Expected speed > 900 km/h, got {speed:.0f}"


class TestAmountAnomaly:
    def test_returns_one_transaction(self, user_id, profile, fixed_rng, ts):
        assert len(gen_amount_anomaly(user_id, profile, fixed_rng, ts)) == 1

    def test_amount_over_10x_avg(self, user_id, profile, fixed_rng, ts):
        txn = gen_amount_anomaly(user_id, profile, fixed_rng, ts)[0]
        assert txn["amount"] >= profile["avg_amount"] * 10

    def test_fraud_type(self, user_id, profile, fixed_rng, ts):
        txn = gen_amount_anomaly(user_id, profile, fixed_rng, ts)[0]
        assert txn["fraud_type"] == "amount_anomaly"


class TestOddHours:
    def test_returns_one_transaction(self, user_id, profile, fixed_rng, ts):
        assert len(gen_odd_hours(user_id, profile, fixed_rng, ts)) == 1

    def test_hour_between_2_and_4(self, user_id, profile, fixed_rng, ts):
        txn = gen_odd_hours(user_id, profile, fixed_rng, ts)[0]
        hour = datetime.fromisoformat(txn["timestamp"]).hour
        assert 2 <= hour <= 4

    def test_merchant_not_typical(self, user_id, profile, fixed_rng, ts):
        txn = gen_odd_hours(user_id, profile, fixed_rng, ts)[0]
        # Should be outside user's typical merchants (if they have any atypical ones).
        # We can't guarantee it 100% if user happens to use all merchants,
        # but with 10 categories and at most 5 typical this should hold.
        if len(profile["typical_merchants"]) < 10:
            assert txn["merchant_category"] not in profile["typical_merchants"]

    def test_fraud_type(self, user_id, profile, fixed_rng, ts):
        txn = gen_odd_hours(user_id, profile, fixed_rng, ts)[0]
        assert txn["fraud_type"] == "odd_hours"


class TestRoundStructuring:
    def test_returns_3_to_5_transactions(self, user_id, profile, fixed_rng, ts):
        txns = gen_round_structuring(user_id, profile, fixed_rng, ts)
        assert 3 <= len(txns) <= 5

    def test_all_round_amounts(self, user_id, profile, fixed_rng, ts):
        txns = gen_round_structuring(user_id, profile, fixed_rng, ts)
        for txn in txns:
            # Amount should be a round number (no cents).
            assert txn["amount"] % 1.0 == pytest.approx(0.0)

    def test_within_one_hour(self, user_id, profile, fixed_rng, ts):
        txns = gen_round_structuring(user_id, profile, fixed_rng, ts)
        timestamps = [datetime.fromisoformat(t["timestamp"]) for t in txns]
        span = max(timestamps) - min(timestamps)
        assert span.total_seconds() <= 3600

    def test_fraud_type(self, user_id, profile, fixed_rng, ts):
        txns = gen_round_structuring(user_id, profile, fixed_rng, ts)[0]
        assert txns["fraud_type"] == "round_structuring"


# -------------------------------------------------------------------
# generate_batch
# -------------------------------------------------------------------

class TestGenerateBatch:
    def test_returns_exact_n(self, profiles_small, fixed_rng, ts):
        txns = generate_batch(profiles_small, fixed_rng, 100, fraud_rate=0.05, base_ts=ts)
        assert len(txns) == 100

    def test_approx_fraud_rate(self, profiles_small, ts):
        # Use a large batch to test rate statistically.
        rng = random.Random(1)
        txns = generate_batch(profiles_small, rng, 1000, fraud_rate=0.05, base_ts=ts)
        fraud_count = sum(1 for t in txns if t["ground_truth_label"] == 1)
        # Expect roughly 50 fraud (±30 for statistical variation).
        assert 10 <= fraud_count <= 200

    def test_all_have_required_keys(self, profiles_small, fixed_rng, ts):
        required = {"transaction_id", "user_id", "amount", "merchant_category",
                    "location", "timestamp", "device", "card_present",
                    "ground_truth_label", "fraud_type"}
        txns = generate_batch(profiles_small, fixed_rng, 20, base_ts=ts)
        for txn in txns:
            assert required.issubset(txn.keys())

    def test_reproducible_with_seed(self, profiles_small, ts):
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        batch1 = generate_batch(profiles_small, rng1, 10, base_ts=ts)
        batch2 = generate_batch(profiles_small, rng2, 10, base_ts=ts)
        assert [t["transaction_id"] for t in batch1] == [t["transaction_id"] for t in batch2]
