"""
PayGuard synthetic transaction generator.

Produces realistic payment events and emits them to the Kafka topic
"transactions" via aiokafka.  95 % of events are normal; 5 % exercise
one of five labelled fraud patterns.

ground_truth_label / fraud_type are included in every event for
EVALUATION purposes only — they are never fed to the model as inputs.

Usage:
    python -m producer.generator [--seed SEED]

Environment variables:
    KAFKA_BOOTSTRAP_SERVERS   default: localhost:9092
    KAFKA_TOPIC               default: transactions
    EVENTS_PER_SEC            default: 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from aiokafka import AIOKafkaProducer

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions")
EVENTS_PER_SEC = float(os.getenv("EVENTS_PER_SEC", "10"))

# -------------------------------------------------------------------
# Static reference data
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

# Representative cities with lat/lng — spread across continents to
# make geo-impossible fraud patterns meaningful.
CITIES: list[dict[str, Any]] = [
    {"city": "New York", "country": "US", "lat": 40.7128, "lng": -74.0060},
    {"city": "Los Angeles", "country": "US", "lat": 34.0522, "lng": -118.2437},
    {"city": "Chicago", "country": "US", "lat": 41.8781, "lng": -87.6298},
    {"city": "London", "country": "GB", "lat": 51.5074, "lng": -0.1278},
    {"city": "Paris", "country": "FR", "lat": 48.8566, "lng": 2.3522},
    {"city": "Tokyo", "country": "JP", "lat": 35.6762, "lng": 139.6503},
    {"city": "Sydney", "country": "AU", "lat": -33.8688, "lng": 151.2093},
    {"city": "Toronto", "country": "CA", "lat": 43.6532, "lng": -79.3832},
    {"city": "Berlin", "country": "DE", "lat": 52.5200, "lng": 13.4050},
    {"city": "São Paulo", "country": "BR", "lat": -23.5505, "lng": -46.6333},
    {"city": "Singapore", "country": "SG", "lat": 1.3521, "lng": 103.8198},
    {"city": "Dubai", "country": "AE", "lat": 25.2048, "lng": 55.2708},
]

DEVICES: list[str] = ["mobile", "web", "pos"]

# -------------------------------------------------------------------
# Haversine (duplicated here so generator is self-contained)
# -------------------------------------------------------------------


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km."""
    R = 6_371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# -------------------------------------------------------------------
# User profiles
# -------------------------------------------------------------------


def make_user_profiles(n_users: int, rng: random.Random) -> dict[str, dict[str, Any]]:
    """Create *n_users* behavioural profiles keyed by UUID string.

    Each profile encodes where the user normally transacts, their typical
    spend level, and which merchant categories they frequent.
    """
    profiles: dict[str, dict[str, Any]] = {}
    for _ in range(n_users):
        uid = str(uuid.UUID(int=rng.getrandbits(128)))
        home = rng.choice(CITIES)
        profiles[uid] = {
            "home_location": {"lat": home["lat"], "lng": home["lng"]},
            "avg_amount": round(rng.uniform(20.0, 300.0), 2),
            "typical_merchants": rng.sample(MERCHANT_CATEGORIES, rng.randint(2, 5)),
            "account_age_days": rng.randint(30, 2000),
        }
    return profiles


# -------------------------------------------------------------------
# Base transaction builder
# -------------------------------------------------------------------


def _new_txn_id(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128)))


def _base_txn(
    user_id: str,
    profile: dict[str, Any],
    rng: random.Random,
    ts: datetime,
) -> dict[str, Any]:
    """Build a single normal (non-fraud) transaction for *user_id*."""
    location = rng.choice(CITIES)
    raw_amount = rng.gauss(profile["avg_amount"], profile["avg_amount"] * 0.3)
    amount = max(1.0, round(raw_amount, 2))  # ensure positive
    return {
        "transaction_id": _new_txn_id(rng),
        "user_id": user_id,
        "amount": amount,
        "merchant_category": rng.choice(profile["typical_merchants"]),
        "location": {
            "city": location["city"],
            "country": location["country"],
            "lat": location["lat"],
            "lng": location["lng"],
        },
        "timestamp": ts.isoformat(),
        "device": rng.choice(DEVICES),
        "card_present": rng.random() < 0.6,
        "ground_truth_label": 0,
        "fraud_type": None,
    }


# -------------------------------------------------------------------
# Fraud pattern generators
# Each returns a list[dict] (may be more than one transaction).
# -------------------------------------------------------------------


def gen_velocity_spike(
    user_id: str,
    profile: dict[str, Any],
    rng: random.Random,
    ts: datetime,
) -> list[dict[str, Any]]:
    """8 transactions within 2 minutes — card-testing / account takeover."""
    txns = []
    for _ in range(8):
        t = ts + timedelta(seconds=rng.uniform(0, 119))
        txn = _base_txn(user_id, profile, rng, t)
        txn["ground_truth_label"] = 1
        txn["fraud_type"] = "velocity_spike"
        txns.append(txn)
    return txns


def gen_geo_impossible(
    user_id: str,
    profile: dict[str, Any],
    rng: random.Random,
    ts: datetime,
) -> list[dict[str, Any]]:
    """Two transactions whose haversine distance / elapsed time implies
    travel speed > 900 km/h — simultaneous card clone usage."""
    city1, city2 = rng.sample(CITIES, 2)
    dist_km = _haversine(city1["lat"], city1["lng"], city2["lat"], city2["lng"])
    # Ensure speed = dist / elapsed > 900 km/h, so elapsed < dist/900 hours.
    # Clamp elapsed to [30, 300] seconds to keep timestamps realistic.
    max_elapsed_sec = max(30.0, (dist_km / 900.0) * 3600.0 * 0.05)
    elapsed_sec = rng.uniform(30, min(max_elapsed_sec, 300))
    t2 = ts + timedelta(seconds=elapsed_sec)

    def _at_city(city: dict[str, Any], t: datetime) -> dict[str, Any]:
        txn = _base_txn(user_id, profile, rng, t)
        txn["location"] = {
            "city": city["city"],
            "country": city["country"],
            "lat": city["lat"],
            "lng": city["lng"],
        }
        txn["ground_truth_label"] = 1
        txn["fraud_type"] = "geo_impossible"
        return txn

    return [_at_city(city1, ts), _at_city(city2, t2)]


def gen_amount_anomaly(
    user_id: str,
    profile: dict[str, Any],
    rng: random.Random,
    ts: datetime,
) -> list[dict[str, Any]]:
    """Single transaction > 10× the user's average — large fraud purchase."""
    txn = _base_txn(user_id, profile, rng, ts)
    txn["amount"] = round(profile["avg_amount"] * (10.0 + rng.uniform(0.0, 5.0)), 2)
    txn["ground_truth_label"] = 1
    txn["fraud_type"] = "amount_anomaly"
    return [txn]


def gen_odd_hours(
    user_id: str,
    profile: dict[str, Any],
    rng: random.Random,
    ts: datetime,
) -> list[dict[str, Any]]:
    """Transaction at 02:00–04:59 UTC at a non-typical merchant category.

    Mirrors night-time automated fraud transactions.
    """
    odd_ts = ts.replace(
        hour=rng.randint(2, 4),
        minute=rng.randint(0, 59),
        second=rng.randint(0, 59),
        microsecond=0,
    )
    atypical = [m for m in MERCHANT_CATEGORIES if m not in profile["typical_merchants"]]
    merchant = rng.choice(atypical) if atypical else rng.choice(MERCHANT_CATEGORIES)
    txn = _base_txn(user_id, profile, rng, odd_ts)
    txn["merchant_category"] = merchant
    txn["ground_truth_label"] = 1
    txn["fraud_type"] = "odd_hours"
    return [txn]


def gen_round_structuring(
    user_id: str,
    profile: dict[str, Any],
    rng: random.Random,
    ts: datetime,
) -> list[dict[str, Any]]:
    """3–5 exact round-dollar transactions within one hour — structuring to
    stay below reporting thresholds."""
    round_amounts = [250.00, 500.00, 750.00, 1000.00, 2000.00]
    n = rng.randint(3, 5)
    txns = []
    for _ in range(n):
        t = ts + timedelta(minutes=rng.uniform(0, 59))
        txn = _base_txn(user_id, profile, rng, t)
        txn["amount"] = rng.choice(round_amounts)
        txn["ground_truth_label"] = 1
        txn["fraud_type"] = "round_structuring"
        txns.append(txn)
    return txns


# Map used for sampling during batch generation
FRAUD_GENERATORS = [
    gen_velocity_spike,
    gen_geo_impossible,
    gen_amount_anomaly,
    gen_odd_hours,
    gen_round_structuring,
]


# -------------------------------------------------------------------
# Batch generation (used by ml/train.py and tests)
# -------------------------------------------------------------------


def generate_batch(
    profiles: dict[str, dict[str, Any]],
    rng: random.Random,
    n: int,
    fraud_rate: float = 0.05,
    base_ts: datetime | None = None,
) -> list[dict[str, Any]]:
    """Generate exactly *n* transactions with ~*fraud_rate* being fraudulent.

    Timestamps are spread ±12 h around *base_ts* so velocity windows
    are realistic.  Fraud pattern generators may emit more than one
    transaction per call; the result is trimmed to *n* rows.
    """
    if base_ts is None:
        base_ts = datetime.now(timezone.utc)

    user_ids = list(profiles.keys())
    transactions: list[dict[str, Any]] = []
    generated = 0

    while generated < n:
        user_id = rng.choice(user_ids)
        profile = profiles[user_id]
        # Spread transactions across a 24-hour window centred on base_ts.
        offset_sec = rng.uniform(-43_200, 43_200)
        ts = base_ts + timedelta(seconds=offset_sec)

        if rng.random() < fraud_rate:
            gen_fn = rng.choice(FRAUD_GENERATORS)
            batch = gen_fn(user_id, profile, rng, ts)
        else:
            batch = [_base_txn(user_id, profile, rng, ts)]

        transactions.extend(batch)
        generated += len(batch)

    return transactions[:n]


# -------------------------------------------------------------------
# Async Kafka producer
# -------------------------------------------------------------------


async def produce(seed: int | None = None) -> None:
    """Continuously emit synthetic transactions to Kafka."""
    rng = random.Random(seed)
    profiles = make_user_profiles(200, rng)
    interval = 1.0 / EVENTS_PER_SEC

    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    await producer.start()
    print(f"[generator] started → topic={KAFKA_TOPIC}  rate={EVENTS_PER_SEC} ev/s")

    try:
        while True:
            ts = datetime.now(timezone.utc)
            user_id = rng.choice(list(profiles.keys()))
            profile = profiles[user_id]

            if rng.random() < 0.05:
                gen_fn = rng.choice(FRAUD_GENERATORS)
                batch = gen_fn(user_id, profile, rng, ts)
            else:
                batch = [_base_txn(user_id, profile, rng, ts)]

            for txn in batch:
                await producer.send_and_wait(KAFKA_TOPIC, txn)

            await asyncio.sleep(interval)
    finally:
        await producer.stop()


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PayGuard synthetic transaction generator")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = parser.parse_args()
    asyncio.run(produce(seed=args.seed))
