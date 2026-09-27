"""
SHAP-based attribution for the safety model.

Turns a prediction into per-feature contributions (in safety points) and
into a short text brief that the LLM explainer can work from.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap

log = logging.getLogger("ml.shap")

ARTIFACTS = Path("ai/ml/artifacts")

# Contributions smaller than this (in points) are left out of the text brief.
MIN_REPORTED_IMPACT = 0.5
MAX_FACTORS_PER_SIDE = 4


@lru_cache(maxsize=1)
def load_explainer() -> shap.TreeExplainer:
    """Reads the TreeExplainer saved during training (cached)."""
    path = ARTIFACTS / "shap_explainer.pkl"
    if not path.exists():
        raise FileNotFoundError(
            f"SHAP explainer not found: {path}\n"
            "Train the model first: python -m ai.ml.train_india"
        )
    explainer = joblib.load(path)
    log.info("SHAP explainer loaded from %s", path)
    return explainer


def get_shap_values(feat_df: pd.DataFrame) -> np.ndarray:
    """SHAP matrix of shape (rows, features) for a feature frame."""
    return load_explainer().shap_values(feat_df)


def get_feature_contributions(feat_df: pd.DataFrame, feature_cols: list) -> dict:
    """Feature -> contribution for the first row (positive raises the score)."""
    values = get_shap_values(feat_df)
    row = values if values.ndim == 1 else values[0]
    return {col: round(float(row[i]), 4) for i, col in enumerate(feature_cols)}


def build_explanation_context(
    contributions: dict,
    safety_score: float,
    hour: int = 22,
) -> str:
    """Formats the strongest contributions as a readable summary."""
    from ai.ml.features import get_feature_description

    ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
    helping = [(k, v) for k, v in ranked if v > MIN_REPORTED_IMPACT][:MAX_FACTORS_PER_SIDE]
    hurting = [(k, v) for k, v in ranked if v < -MIN_REPORTED_IMPACT][:MAX_FACTORS_PER_SIDE]

    period = "night" if (hour >= 20 or hour <= 5) else "day"
    lines = [
        f"Road segment safety analysis at {hour:02d}:00 ({period})",
        f"Safety score: {safety_score:.1f}/100",
        "",
        "Positive factors (increasing safety):",
    ]
    if helping:
        lines += [f"  + {get_feature_description(k)}: +{v:.1f} pts" for k, v in helping]
    else:
        lines.append("  None significant")

    lines += ["", "Negative factors (decreasing safety):"]
    if hurting:
        lines += [f"  - {get_feature_description(k)}: {v:.1f} pts" for k, v in hurting]
    else:
        lines.append("  None significant")

    return "\n".join(lines)


def test_explainer():
    """Runs the explainer on a row of default values and logs the brief."""
    from ai.ml.features import FEATURE_COLS, FEATURE_DEFAULTS

    log.info("Running SHAP explainer check ...")
    sample = pd.DataFrame([FEATURE_DEFAULTS])[FEATURE_COLS].fillna(0)
    contributions = get_feature_contributions(sample, FEATURE_COLS)
    log.info(build_explanation_context(contributions, safety_score=55.0, hour=22))
    log.info("SHAP explainer check passed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_explainer()
