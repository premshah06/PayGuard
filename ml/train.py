"""
PayGuard model training, ONNX export, and evaluation.

Pipeline:
  1. Generate 10 000 synthetic transactions for training.
  2. Compute features (consumer/features.py).
  3. Train sklearn IsolationForest (unsupervised — no labels).
  4. Export to ONNX (target_opset 17 / ml:3).
  5. Sigmoid-calibrate raw scores to a [0, 1] anomaly probability.
  6. Save model artefacts and feature_map.json.
  7. Generate 2 000 held-out transactions WITH ground truth, evaluate,
     print confusion matrix, save ml/eval_results.json.

Usage:
    python -m ml.train [--seed SEED] [--train-size N] [--eval-size N]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
from scipy.special import expit  # sigmoid

# Allow running as `python ml/train.py` from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from consumer.features import (  # noqa: E402
    FEATURE_ORDER,
    MERCHANT_CATEGORIES,
    engineer_features,
    features_to_vector,
    reset_state,
)
from producer.generator import generate_batch, make_user_profiles  # noqa: E402

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------

ML_DIR = Path(__file__).resolve().parent
ONNX_PATH = ML_DIR / "model.onnx"
FEATURE_MAP_PATH = ML_DIR / "feature_map.json"
EVAL_PATH = ML_DIR / "eval_results.json"

# -------------------------------------------------------------------
# Thresholds (mirrored in inference/app.py)
# -------------------------------------------------------------------

THRESHOLD_FLAG = 0.85
THRESHOLD_REVIEW = 0.60


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def build_feature_matrix(
    transactions: list[dict],
    profiles: dict,
) -> np.ndarray:
    """Run feature engineering over *transactions* and return an (N, 7) float32
    matrix in FEATURE_ORDER column order."""
    rows: list[list[float]] = []
    for txn in transactions:
        uid = txn["user_id"]
        profile = profiles.get(uid)
        feats = engineer_features(txn, profile)
        rows.append(features_to_vector(feats))
    return np.array(rows, dtype=np.float32)


def sigmoid_calibrate(
    raw_scores: np.ndarray,
    loc: float,
    scale: float,
) -> np.ndarray:
    """Map IsolationForest decision_function scores to [0, 1] anomaly probability.

    IsolationForest decision_function: higher → more normal (inlier).
    We negate, shift by loc, scale by std to centre the sigmoid at the
    training-data median.  Anomalies (low raw score) → probability close to 1.
    """
    return expit(-(raw_scores - loc) / (scale + 1e-8))


# -------------------------------------------------------------------
# ONNX inference helper (shared with inference/app.py)
# -------------------------------------------------------------------


def extract_onnx_score(score_output: object) -> float:
    """Extract a scalar anomaly score from onnxruntime output[1].

    skl2onnx IsolationForest can emit either:
      - A numpy float array  → use directly.
      - A list of dicts {-1: score, 1: score}  → return the -1 (anomaly) value.
    """
    if isinstance(score_output, (list, tuple)) and len(score_output) > 0:
        item = score_output[0]
        if isinstance(item, dict):
            # Sequence-of-Maps format: pick the anomaly class key (-1).
            raw_value = item.get(-1, next(iter(item.values())))
            return float(cast(Any, raw_value))
        return float(cast(Any, item))
    return float(cast(Any, score_output))


# -------------------------------------------------------------------
# Training
# -------------------------------------------------------------------


def train(
    seed: int = 42,
    train_size: int = 10_000,
    eval_size: int = 2_000,
    n_users: int = 300,
) -> None:
    print("=" * 60)
    print("PayGuard — model training")
    print("=" * 60)

    import random

    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    from sklearn.ensemble import IsolationForest

    rng = random.Random(seed)
    # ------------------------------------------------------------------
    # 1. Generate training data
    # ------------------------------------------------------------------
    print(f"\n[1/7] Generating {train_size:,} training transactions …")
    base_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    profiles = make_user_profiles(n_users, rng)
    train_txns = generate_batch(profiles, rng, train_size, fraud_rate=0.05, base_ts=base_ts)

    # ------------------------------------------------------------------
    # 2. Feature engineering
    # ------------------------------------------------------------------
    print("[2/7] Engineering features …")
    reset_state()
    # Sort by timestamp so rolling state is computed chronologically.
    train_txns.sort(key=lambda t: t["timestamp"])
    X_train = build_feature_matrix(train_txns, profiles)
    print(f"      X_train shape: {X_train.shape}")

    # ------------------------------------------------------------------
    # 3. Train IsolationForest — unsupervised, contamination = 0.05
    # ------------------------------------------------------------------
    print("[3/7] Training IsolationForest (n_estimators=100, contamination=0.05) …")
    clf = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=seed,
        n_jobs=-1,
    )
    clf.fit(X_train)
    print(f"      offset_: {clf.offset_:.4f}")

    # ------------------------------------------------------------------
    # 4. Sigmoid calibration from training scores
    # ------------------------------------------------------------------
    print("[4/7] Computing sigmoid calibration parameters …")
    train_scores = clf.decision_function(X_train)  # higher → more normal
    calib_loc = float(np.mean(train_scores))
    calib_scale = float(np.std(train_scores))
    print(f"      score mean={calib_loc:.4f}  std={calib_scale:.4f}")

    # Sanity-check: anomaly probability for inliers should be < 0.5 on average.
    calib_probs = sigmoid_calibrate(train_scores, calib_loc, calib_scale)
    print(f"      calibrated prob mean={calib_probs.mean():.3f}  "
          f"max={calib_probs.max():.3f}")

    # ------------------------------------------------------------------
    # 5. Export to ONNX
    # ------------------------------------------------------------------
    print(f"[5/7] Exporting to ONNX → {ONNX_PATH} …")
    n_features = len(FEATURE_ORDER)
    initial_type = [("float_input", FloatTensorType([None, n_features]))]
    onnx_model = convert_sklearn(
        clf,
        initial_types=initial_type,
        target_opset={"": 17, "ai.onnx.ml": 3},
    )
    ONNX_PATH.write_bytes(onnx_model.SerializeToString())
    print(f"      ONNX model written ({ONNX_PATH.stat().st_size // 1024} KB)")

    # ------------------------------------------------------------------
    # 6. Save feature map
    # ------------------------------------------------------------------
    print(f"[6/7] Saving feature map → {FEATURE_MAP_PATH} …")
    feature_map = {
        "feature_order": FEATURE_ORDER,
        "merchant_categories": MERCHANT_CATEGORIES,
        "calibration": {
            "loc": calib_loc,
            "scale": calib_scale,
        },
        "thresholds": {
            "flag": THRESHOLD_FLAG,
            "review": THRESHOLD_REVIEW,
        },
        "model_version": "1.0.0",
        "trained_at": datetime.now(UTC).isoformat(),
    }
    FEATURE_MAP_PATH.write_text(json.dumps(feature_map, indent=2))

    # ------------------------------------------------------------------
    # 7. Evaluate on held-out data with ground truth
    # ------------------------------------------------------------------
    print(f"\n[7/7] Evaluating on {eval_size:,} held-out transactions …")
    import onnxruntime as rt

    eval_base_ts = datetime(2024, 2, 15, 12, 0, 0, tzinfo=UTC)
    eval_profiles = make_user_profiles(100, random.Random(seed + 1))
    eval_txns = generate_batch(
        eval_profiles, random.Random(seed + 1), eval_size,
        fraud_rate=0.05, base_ts=eval_base_ts,
    )
    eval_txns.sort(key=lambda t: t["timestamp"])

    reset_state()
    X_eval = build_feature_matrix(eval_txns, eval_profiles)

    # Load exported ONNX model for round-trip verification.
    sess = rt.InferenceSession(str(ONNX_PATH), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    onnx_outputs = sess.run(None, {input_name: X_eval})
    onnx_labels = np.asarray(onnx_outputs[0]).reshape(-1)  # int64: -1 (anomaly) / 1 (normal)

    # Also get calibrated probabilities via sklearn (ground truth for calibration).
    eval_raw = clf.decision_function(X_eval)
    anomaly_probs = sigmoid_calibrate(eval_raw, calib_loc, calib_scale)

    # Cross-check: ONNX labels should agree with sklearn predict.
    sklearn_labels = clf.predict(X_eval)
    label_agreement = np.mean(onnx_labels == sklearn_labels)
    print(f"      ONNX/sklearn label agreement: {label_agreement:.4f}")

    # Assign decisions using calibrated probabilities.
    def _decision(prob: float) -> str:
        if prob >= THRESHOLD_FLAG:
            return "flag"
        if prob >= THRESHOLD_REVIEW:
            return "review"
        return "clear"

    decisions = [_decision(float(p)) for p in anomaly_probs]
    true_labels = [txn["ground_truth_label"] for txn in eval_txns]
    fraud_types = [txn.get("fraud_type") for txn in eval_txns]

    # ------------------------------------------------------------------
    # Precision / recall / F1 — overall and per fraud type
    # ------------------------------------------------------------------
    def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

    # A "positive prediction" is flag or review (not clear).
    predicted_positive = [d != "clear" for d in decisions]

    tp = sum(1 for pp, tl in zip(predicted_positive, true_labels, strict=False) if pp and tl == 1)
    fp = sum(1 for pp, tl in zip(predicted_positive, true_labels, strict=False) if pp and tl == 0)
    fn = sum(1 for pp, tl in zip(predicted_positive, true_labels, strict=False) if not pp and tl == 1)
    tn = sum(1 for pp, tl in zip(predicted_positive, true_labels, strict=False) if not pp and tl == 0)

    overall = _prf(tp, fp, fn)

    per_type: dict[str, dict] = {}
    unique_fraud_types = {ft for ft in fraud_types if ft is not None}
    for ft in unique_fraud_types:
        ft_tp = sum(1 for pp, tl, ftype in zip(predicted_positive, true_labels, fraud_types, strict=False)
                    if pp and tl == 1 and ftype == ft)
        ft_fp = sum(1 for pp, tl, ftype in zip(predicted_positive, true_labels, fraud_types, strict=False)
                    if pp and tl == 0 and ftype == ft)  # not meaningful per type but included
        ft_fn = sum(1 for pp, tl, ftype in zip(predicted_positive, true_labels, fraud_types, strict=False)
                    if not pp and tl == 1 and ftype == ft)
        count = sum(1 for tl, ftype in zip(true_labels, fraud_types, strict=False) if tl == 1 and ftype == ft)
        per_type[ft] = {**_prf(ft_tp, ft_fp, ft_fn), "count": count}

    # Confusion matrix: [[TN, FP], [FN, TP]]
    confusion_matrix = [[tn, fp], [fn, tp]]

    print(f"\n{'─' * 50}")
    print(f"  Overall  — precision={overall['precision']:.3f}  "
          f"recall={overall['recall']:.3f}  F1={overall['f1']:.3f}")
    print(f"  Confusion matrix (TN FP / FN TP): {confusion_matrix}")
    print(f"{'─' * 50}")
    for ft, m in per_type.items():
        print(f"  {ft:<22} P={m['precision']:.3f}  R={m['recall']:.3f}  "
              f"F1={m['f1']:.3f}  n={m['count']}")
    print(f"{'─' * 50}\n")

    eval_results = {
        "overall": overall,
        "per_fraud_type": per_type,
        "confusion_matrix": confusion_matrix,
        "label_agreement_onnx_sklearn": round(float(label_agreement), 4),
        "threshold_flag": THRESHOLD_FLAG,
        "threshold_review": THRESHOLD_REVIEW,
        "train_size": train_size,
        "eval_size": eval_size,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    EVAL_PATH.write_text(json.dumps(eval_results, indent=2))
    print(f"Eval results saved → {EVAL_PATH}")
    print("Training complete ✓")


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train PayGuard fraud detection model")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-size", type=int, default=10_000)
    parser.add_argument("--eval-size", type=int, default=2_000)
    args = parser.parse_args()
    train(seed=args.seed, train_size=args.train_size, eval_size=args.eval_size)
