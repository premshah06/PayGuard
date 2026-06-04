"""
PayGuard inference sidecar.

Loads an ONNX IsolationForest model at startup and serves real-time
anomaly scoring over HTTP.

Endpoints:
    POST /score   — takes a raw transaction, engineers features, returns
                    {anomaly_score, decision, features_used}
    GET  /health  — liveness probe; no auth required
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from scipy.special import expit

# Allow sibling-package imports when running from repo root or in Docker.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from consumer.features import engineer_features, features_to_vector  # noqa: E402

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

MODEL_PATH = Path(os.getenv("MODEL_PATH", "ml/model.onnx"))
FEATURE_MAP_PATH = Path(os.getenv("FEATURE_MAP_PATH", "ml/feature_map.json"))

THRESHOLD_FLAG = float(os.getenv("THRESHOLD_FLAG", "0.85"))
THRESHOLD_REVIEW = float(os.getenv("THRESHOLD_REVIEW", "0.60"))

# -------------------------------------------------------------------
# Global model state (loaded once at startup)
# -------------------------------------------------------------------

_ort_session: Any = None
_ort_input_name: str = ""
_calib_loc: float = 0.0
_calib_scale: float = 1.0
_model_version: str = "unknown"

app = FastAPI(title="PayGuard Inference Sidecar", version="1.0.0")


# -------------------------------------------------------------------
# Startup / shutdown
# -------------------------------------------------------------------


@app.on_event("startup")
async def load_model() -> None:
    global _ort_session, _ort_input_name, _calib_loc, _calib_scale, _model_version

    if not MODEL_PATH.exists():
        print(f"[inference] WARNING: model not found at {MODEL_PATH}. "
              "Scoring will return 503 until the model is trained.")
        return

    import onnxruntime as rt

    _ort_session = rt.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    _ort_input_name = _ort_session.get_inputs()[0].name

    feature_map = json.loads(FEATURE_MAP_PATH.read_text())
    calib = feature_map["calibration"]
    _calib_loc = float(calib["loc"])
    _calib_scale = float(calib["scale"])
    _model_version = feature_map.get("model_version", "1.0.0")

    print(f"[inference] model loaded  version={_model_version}  "
          f"calib_loc={_calib_loc:.4f}  calib_scale={_calib_scale:.4f}")


# -------------------------------------------------------------------
# Score extraction helpers
# -------------------------------------------------------------------


def _extract_raw_score(score_output: object) -> float:
    """Robustly extract a scalar score from onnxruntime output[1].

    skl2onnx IsolationForest may emit a numpy float array *or* a
    Sequence-of-Maps [{-1: score, 1: score}] depending on version.
    """
    if isinstance(score_output, np.ndarray):
        return float(score_output.flat[0])
    if isinstance(score_output, (list, tuple)) and len(score_output) > 0:
        item = score_output[0]
        if isinstance(item, dict):
            # Anomaly-class key is -1; fall back to the first value.
            return float(item.get(-1, next(iter(item.values()))))
        return float(item)
    return float(score_output)


def _calibrated_score(raw: float) -> float:
    """Convert IsolationForest decision_function score to [0, 1] anomaly prob."""
    return float(expit(-(raw - _calib_loc) / (_calib_scale + 1e-8)))


def _decision(prob: float) -> str:
    if prob >= THRESHOLD_FLAG:
        return "flag"
    if prob >= THRESHOLD_REVIEW:
        return "review"
    return "clear"


# -------------------------------------------------------------------
# Request / response models
# -------------------------------------------------------------------


class Transaction(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    merchant_category: str
    location: dict[str, Any]
    timestamp: str
    device: str
    card_present: bool
    # Ground-truth fields are forwarded transparently but never used in scoring.
    ground_truth_label: int | None = None
    fraud_type: str | None = None


class ScoreResponse(BaseModel):
    transaction_id: str
    anomaly_score: float
    decision: str
    features_used: dict[str, float]


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model_loaded": _ort_session is not None,
        "version": _model_version,
    }


@app.post("/score", response_model=ScoreResponse)
async def score(txn: Transaction) -> ScoreResponse:
    if _ort_session is None:
        raise HTTPException(status_code=503, detail="Model not loaded — run ml/train.py first")

    # Feature engineering uses per-user rolling state in-memory.
    txn_dict = txn.model_dump()
    features = engineer_features(txn_dict)
    feature_vec = np.array([features_to_vector(features)], dtype=np.float32)

    # ONNX inference
    outputs = _ort_session.run(None, {_ort_input_name: feature_vec})
    raw_score = _extract_raw_score(outputs[1])

    anomaly_score = _calibrated_score(raw_score)
    decision = _decision(anomaly_score)

    return ScoreResponse(
        transaction_id=txn.transaction_id,
        anomaly_score=round(anomaly_score, 4),
        decision=decision,
        features_used=features,
    )
