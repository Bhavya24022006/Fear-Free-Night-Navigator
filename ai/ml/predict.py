"""
Inference helpers for the road-safety model.

Loads the trained regressor once per process and scores road segments,
optionally with a SHAP breakdown. Also owns the score -> grade / label /
colour bands used across the API and the router.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from ai.ml.features import (
    FEATURE_COLS,
    build_feature_vector,
    build_feature_vectors_batch,
)

log = logging.getLogger("ml.predict")

ARTIFACTS = Path("ai/ml/artifacts")
FALLBACK_SCORE = 40.0

# (lower bound, grade, label, colour), checked from the top down.
SCORE_BANDS = [
    (80, "A", "Very Safe", "#22c55e"),
    (60, "B", "Safe",      "#84cc16"),
    (40, "C", "Moderate",  "#f59e0b"),
    (20, "D", "Unsafe",    "#ef4444"),
]
LOWEST_BAND = ("E", "Avoid", "#7f1d1d")


def _band(score: float) -> tuple[str, str, str]:
    for lower, grade, label, colour in SCORE_BANDS:
        if score >= lower:
            return grade, label, colour
    return LOWEST_BAND


def score_to_grade(score: float) -> str:
    """Letter grade A (safest) to E."""
    return _band(score)[0]


def score_to_label(score: float) -> str:
    """Short wording for a score, e.g. 'Moderate'."""
    return _band(score)[1]


def score_to_color(score: float) -> str:
    """Hex colour for drawing a score on the map."""
    return _band(score)[2]


@lru_cache(maxsize=1)
def load_model():
    """Reads safety_model.pkl from the artifacts folder (cached)."""
    model_path = ARTIFACTS / "safety_model.pkl"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found: {model_path}\n"
            "Train it first: python -m ai.ml.train_india"
        )
    model = joblib.load(model_path)
    log.info("Model loaded from %s", model_path)
    return model


@lru_cache(maxsize=1)
def load_feature_cols() -> list:
    """Column list saved at training time, or the current definition."""
    path = ARTIFACTS / "feature_cols.json"
    if path.exists():
        with open(path) as fh:
            return json.load(fh)
    return FEATURE_COLS


def predict_safety_score(edge_data: dict, hour: int = 22) -> float:
    """Safety score in [0, 100] for one edge; 40 if prediction fails."""
    try:
        prediction = load_model().predict(build_feature_vector(edge_data, hour))[0]
        return float(np.clip(prediction, 0, 100))
    except Exception as exc:
        log.warning("Prediction failed (%s); returning %.0f", exc, FALLBACK_SCORE)
        return FALLBACK_SCORE


def predict_safety_scores_batch(edges: list[dict], hour: int = 22) -> list[float]:
    """Vectorised version of predict_safety_score."""
    if not edges:
        return []
    try:
        predictions = load_model().predict(build_feature_vectors_batch(edges, hour))
        return [float(np.clip(p, 0, 100)) for p in predictions]
    except Exception as exc:
        log.warning("Batch prediction failed (%s); using defaults", exc)
        return [FALLBACK_SCORE] * len(edges)


def predict_with_explanation(edge_data: dict, hour: int = 22) -> dict:
    """Score plus the SHAP contribution of every feature.

    Returns a dict with safety_score, feature_contributions (feature -> points),
    the three strongest positive and negative features, and the hour.
    """
    try:
        from ai.ml.shap_explainer import get_shap_values

        features = build_feature_vector(edge_data, hour)
        score = float(np.clip(load_model().predict(features)[0], 0, 100))
        shap_row = get_shap_values(features)[0]

        contributions = {
            col: round(float(shap_row[i]), 3) for i, col in enumerate(FEATURE_COLS)
        }
        ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)

        return {
            "safety_score": round(score, 2),
            "feature_contributions": contributions,
            "top_positive": [name for name, value in ranked if value > 0][:3],
            "top_negative": [name for name, value in ranked if value < 0][:3],
            "hour": hour,
        }
    except Exception as exc:
        log.warning("Explanation failed: %s", exc)
        return {
            "safety_score": predict_safety_score(edge_data, hour),
            "feature_contributions": {},
            "top_positive": [],
            "top_negative": [],
            "hour": hour,
        }
