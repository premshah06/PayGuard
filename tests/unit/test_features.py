"""
Unit tests for consumer/features.py.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from consumer.features import (
    FEATURE_ORDER,
    UserState,
    encode_merchant,
    engineer_features,
    features_to_vector,
    haversine,
)

# -------------------------------------------------------------------
# haversine
# -------------------------------------------------------------------

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine(40.7128, -74.006, 40.7128, -74.006) == pytest.approx(0.0)

    def test_new_york_to_london(self):
        # Known great-circle distance ≈ 5570 km.
        dist = haversine(40.7128, -74.006, 51.5074, -0.1278)
        assert 5500 < dist < 5700

    def test_new_york_to_los_angeles(self):
        # Approx 3940 km.
        dist = haversine(40.7128, -74.006, 34.0522, -118.2437)
        assert 3800 < dist < 4100

    def test_antipodal_points_near_max(self):
        # Antipodal points: ~20 015 km (half Earth circumference).
        dist = haversine(0, 0, 0, 180)
        assert dist == pytest.approx(20_015, abs=50)

    def test_symmetry(self):
        d1 = haversine(48.8566, 2.3522, 35.6762, 139.6503)
        d2 = haversine(35.6762, 139.6503, 48.8566, 2.3522)
        assert d1 == pytest.approx(d2, rel=1e-9)

    def test_known_short_distance(self):
        # Manhattan to Brooklyn Bridge ≈ 2 km.
        dist = haversine(40.7831, -73.9712, 40.7061, -73.9969)
        assert 8 < dist < 12  # ~10 km Manhattan to bridge

    def test_returns_float(self):
        result = haversine(0, 0, 1, 1)
        assert isinstance(result, float)


# -------------------------------------------------------------------
# encode_merchant
# -------------------------------------------------------------------

class TestEncodeMerchant:
    def test_known_categories_return_nonnegative(self):
        from consumer.features import MERCHANT_CATEGORIES
        for i, cat in enumerate(MERCHANT_CATEGORIES):
            assert encode_merchant(cat) == i

    def test_unknown_returns_minus_one(self):
        assert encode_merchant("unknown_merchant") == -1

    def test_empty_string(self):
        assert encode_merchant("") == -1


# -------------------------------------------------------------------
# UserState
# -------------------------------------------------------------------

class TestUserState:
    def test_default_avg_is_one(self):
        state = UserState()
        assert state.rolling_avg_amount == pytest.approx(1.0)

    def test_profile_seeds_avg(self):
        profile = {
            "home_location": {"lat": 40.0, "lng": -74.0},
            "avg_amount": 100.0,
            "typical_merchants": ["grocery"],
            "account_age_days": 365,
        }
        state = UserState(profile)
        assert state.rolling_avg_amount == pytest.approx(100.0)

    def test_rolling_avg_updates(self):
        state = UserState()
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        state.update(50.0, ts, 0.0, 0.0)
        state.update(100.0, ts, 0.0, 0.0)
        assert state.rolling_avg_amount == pytest.approx(75.0)

    def test_velocity_window(self):
        state = UserState()
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        from datetime import timedelta
        for i in range(5):
            t = base + timedelta(seconds=i * 30)
            state.update(10.0, t, 0.0, 0.0)
        # All 5 in last 5 min
        query_ts = base + timedelta(seconds=130)
        assert state.txns_in_window(query_ts, 300) == 5

    def test_velocity_excludes_old(self):
        state = UserState()
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        from datetime import timedelta
        old = base - timedelta(seconds=400)
        state.update(10.0, old, 0.0, 0.0)  # older than 5-min window
        state.update(10.0, base, 0.0, 0.0)  # within window
        assert state.txns_in_window(base, 300) == 1

    def test_home_latched_from_first_update(self):
        state = UserState()
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        state.update(10.0, ts, 40.0, -74.0)
        assert state.home_lat == pytest.approx(40.0)
        assert state.home_lng == pytest.approx(-74.0)
        # Second update should NOT change home.
        state.update(10.0, ts, 51.5, -0.1)
        assert state.home_lat == pytest.approx(40.0)


# -------------------------------------------------------------------
# engineer_features
# -------------------------------------------------------------------

class TestEngineerFeatures:
    def test_returns_all_feature_keys(self, normal_txn, profiles, sample_user_id):
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        assert set(feats.keys()) == set(FEATURE_ORDER)

    def test_amount_passthrough(self, normal_txn, profiles, sample_user_id):
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        assert feats["amount"] == pytest.approx(normal_txn["amount"])

    def test_hour_of_day_correct(self, normal_txn, profiles, sample_user_id):
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        assert feats["hour_of_day"] == pytest.approx(14.0)  # 14:30 UTC

    def test_is_weekend_weekday(self, normal_txn, profiles, sample_user_id):
        # 2024-06-10 is a Monday
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        assert feats["is_weekend"] == pytest.approx(0.0)

    def test_is_weekend_saturday(self, normal_txn, profiles, sample_user_id):
        import copy
        txn = copy.deepcopy(normal_txn)
        txn["timestamp"] = "2024-06-08T14:30:00+00:00"  # Saturday
        feats = engineer_features(txn, profiles[sample_user_id])
        assert feats["is_weekend"] == pytest.approx(1.0)

    def test_amount_vs_avg_near_one_for_normal(self, normal_txn, profiles, sample_user_id):
        # First transaction should have amount ≈ avg, so ratio ≈ 1.
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        assert 0.5 < feats["amount_vs_user_avg"] < 2.0

    def test_high_amount_anomaly_flag(self, normal_txn, profiles, sample_user_id):
        import copy
        profile = profiles[sample_user_id]
        txn = copy.deepcopy(normal_txn)
        txn["amount"] = profile["avg_amount"] * 15
        feats = engineer_features(txn, profile)
        assert feats["amount_vs_user_avg"] > 10

    def test_txns_last_5min_increments(self, normal_txn, profiles, sample_user_id):
        import copy
        from datetime import timedelta
        base = datetime(2024, 6, 10, 14, 30, 0, tzinfo=UTC)
        profile = profiles[sample_user_id]
        for i in range(3):
            txn = copy.deepcopy(normal_txn)
            txn["timestamp"] = (base + timedelta(seconds=i * 30)).isoformat()
            feats = engineer_features(txn, profile)
        # After 2 recorded transactions, third should see 2 in window.
        assert feats["txns_last_5min"] == pytest.approx(2.0)

    def test_distance_from_home_zero_when_at_home(self, normal_txn, profiles, sample_user_id):
        profile = profiles[sample_user_id]
        # txn location set to home location in conftest
        feats = engineer_features(normal_txn, profile)
        assert feats["distance_from_home_km"] == pytest.approx(0.0, abs=1.0)

    def test_merchant_encoded_correctly(self, normal_txn, profiles, sample_user_id):
        profile = profiles[sample_user_id]
        feats = engineer_features(normal_txn, profile)
        expected = encode_merchant(normal_txn["merchant_category"])
        assert feats["merchant_category_encoded"] == pytest.approx(float(expected))


# -------------------------------------------------------------------
# features_to_vector
# -------------------------------------------------------------------

class TestFeaturesToVector:
    def test_length_equals_feature_order(self, normal_txn, profiles, sample_user_id):
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        vec = features_to_vector(feats)
        assert len(vec) == len(FEATURE_ORDER)

    def test_order_matches_feature_order(self, normal_txn, profiles, sample_user_id):
        feats = engineer_features(normal_txn, profiles[sample_user_id])
        vec = features_to_vector(feats)
        for i, key in enumerate(FEATURE_ORDER):
            assert vec[i] == pytest.approx(feats[key])
