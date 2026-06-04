"""
ML round-trip tests: train → export → ONNX predict.

These tests actually train a tiny model to verify the full pipeline
works end-to-end without requiring pre-trained artefacts.
"""
from __future__ import annotations

import json
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from consumer.features import FEATURE_ORDER, engineer_features, features_to_vector, reset_state
from producer.generator import generate_batch, make_user_profiles


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture(scope="module")
def tiny_model():
    """Train a tiny IsolationForest and export to ONNX in a temp dir.
    Module-scoped so training runs once per test session."""
    from sklearn.ensemble import IsolationForest
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    from scipy.special import expit

    rng = random.Random(0)
    profiles = make_user_profiles(30, rng)
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    reset_state()
    txns = generate_batch(profiles, rng, 500, fraud_rate=0.05, base_ts=ts)
    txns.sort(key=lambda t: t["timestamp"])
    rows = []
    for txn in txns:
        f = engineer_features(txn, profiles.get(txn["user_id"]))
        rows.append(features_to_vector(f))
    X = np.array(rows, dtype=np.float32)

    clf = IsolationForest(n_estimators=20, contamination=0.05, random_state=0)
    clf.fit(X)

    train_scores = clf.decision_function(X)
    calib_loc = float(np.mean(train_scores))
    calib_scale = float(np.std(train_scores))

    tmpdir = tempfile.mkdtemp()
    onnx_path = Path(tmpdir) / "model.onnx"
    fmap_path = Path(tmpdir) / "feature_map.json"

    initial_type = [("float_input", FloatTensorType([None, len(FEATURE_ORDER)]))]
    onnx_model = convert_sklearn(clf, initial_types=initial_type,
                                 target_opset={"": 17, "ai.onnx.ml": 3})
    onnx_path.write_bytes(onnx_model.SerializeToString())

    fmap_path.write_text(json.dumps({
        "feature_order": FEATURE_ORDER,
        "calibration": {"loc": calib_loc, "scale": calib_scale},
        "thresholds": {"flag": 0.85, "review": 0.60},
        "model_version": "test",
    }))

    return {
        "clf": clf,
        "onnx_path": onnx_path,
        "fmap_path": fmap_path,
        "X": X,
        "calib_loc": calib_loc,
        "calib_scale": calib_scale,
    }


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

class TestONNXExport:
    def test_onnx_file_exists(self, tiny_model):
        assert tiny_model["onnx_path"].exists()

    def test_onnx_file_nonempty(self, tiny_model):
        assert tiny_model["onnx_path"].stat().st_size > 0

    def test_feature_map_has_required_keys(self, tiny_model):
        fm = json.loads(tiny_model["fmap_path"].read_text())
        assert "feature_order" in fm
        assert "calibration" in fm
        assert "thresholds" in fm

    def test_feature_order_matches(self, tiny_model):
        fm = json.loads(tiny_model["fmap_path"].read_text())
        assert fm["feature_order"] == FEATURE_ORDER


class TestONNXInference:
    def test_onnx_loads_and_runs(self, tiny_model):
        import onnxruntime as rt
        sess = rt.InferenceSession(str(tiny_model["onnx_path"]),
                                   providers=["CPUExecutionProvider"])
        input_name = sess.get_inputs()[0].name
        X = tiny_model["X"][:5]
        outputs = sess.run(None, {input_name: X})
        assert len(outputs) >= 1

    def test_onnx_labels_in_minus1_or_1(self, tiny_model):
        import onnxruntime as rt
        sess = rt.InferenceSession(str(tiny_model["onnx_path"]),
                                   providers=["CPUExecutionProvider"])
        input_name = sess.get_inputs()[0].name
        X = tiny_model["X"][:50]
        outputs = sess.run(None, {input_name: X})
        labels = outputs[0]
        unique = set(int(l) for l in labels)
        assert unique.issubset({-1, 1})

    def test_onnx_label_agreement_with_sklearn(self, tiny_model):
        """ONNX and sklearn predict must agree on ≥ 98 % of samples."""
        import onnxruntime as rt
        clf = tiny_model["clf"]
        X = tiny_model["X"]
        sklearn_labels = clf.predict(X)

        sess = rt.InferenceSession(str(tiny_model["onnx_path"]),
                                   providers=["CPUExecutionProvider"])
        input_name = sess.get_inputs()[0].name
        onnx_outputs = sess.run(None, {input_name: X})
        onnx_labels = onnx_outputs[0]

        agreement = np.mean(sklearn_labels == onnx_labels)
        assert agreement >= 0.98, f"ONNX/sklearn agreement too low: {agreement:.3f}"

    def test_calibrated_scores_in_0_1(self, tiny_model):
        """Sigmoid-calibrated anomaly probabilities must be in [0, 1]."""
        import onnxruntime as rt
        from scipy.special import expit

        clf = tiny_model["clf"]
        X = tiny_model["X"]
        raw = clf.decision_function(X)
        probs = expit(-(raw - tiny_model["calib_loc"]) / (tiny_model["calib_scale"] + 1e-8))
        assert np.all(probs >= 0.0) and np.all(probs <= 1.0)

    def test_anomalies_score_higher_than_normal(self, tiny_model):
        """Anomaly samples flagged by sklearn should have higher calibrated
        probability on average than inliers."""
        from scipy.special import expit
        clf = tiny_model["clf"]
        X = tiny_model["X"]
        labels = clf.predict(X)
        raw = clf.decision_function(X)
        probs = expit(-(raw - tiny_model["calib_loc"]) / (tiny_model["calib_scale"] + 1e-8))

        anomaly_mean = float(probs[labels == -1].mean()) if (labels == -1).any() else 0.0
        normal_mean = float(probs[labels == 1].mean()) if (labels == 1).any() else 1.0
        assert anomaly_mean > normal_mean, (
            f"Anomaly prob mean ({anomaly_mean:.3f}) should exceed "
            f"normal prob mean ({normal_mean:.3f})"
        )

    def test_output_shape_matches_input(self, tiny_model):
        import onnxruntime as rt
        sess = rt.InferenceSession(str(tiny_model["onnx_path"]),
                                   providers=["CPUExecutionProvider"])
        input_name = sess.get_inputs()[0].name
        n = 17
        X = tiny_model["X"][:n]
        outputs = sess.run(None, {input_name: X})
        assert len(outputs[0]) == n
