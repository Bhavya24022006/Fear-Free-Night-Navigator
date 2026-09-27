"""
Trains one XGBoost safety model on the feature stores of every city.

Reads data/india/features/*_feature_store.csv, fits a gradient-boosted
regressor on the 32 model features, reports hold-out metrics, computes SHAP
importances and writes everything to ai/ml/artifacts/.

Run:
    python -m ai.ml.train_india
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from ai.ml.features import FEATURE_COLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("ml.train_india")

FEAT_DIR = Path("data/india/features")
ARTIFACTS = Path("ai/ml/artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)

TARGET_COL = "safety_score"
TEST_SHARE = 0.2
SEED = 42
SHAP_SAMPLE_ROWS = 500

MODEL_PARAMS = dict(
    n_estimators=1000,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=1.5,
    objective="reg:squarederror",
    random_state=SEED,
    n_jobs=-1,
    tree_method="hist",
    early_stopping_rounds=50,
)


def load_all_cities() -> pd.DataFrame:
    """Concatenates every city's feature store and tags rows with the city."""
    paths = sorted(FEAT_DIR.glob("*_feature_store.csv"))
    log.info("Found %d city feature stores", len(paths))

    frames = []
    for path in paths:
        city = path.stem.replace("_feature_store", "").replace("_", " ").title()
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            log.warning("  %s: could not be read (%s)", city, exc)
            continue
        frame["city"] = city
        frames.append(frame)
        log.info("  %-22s %s edges", city, f"{len(frame):,}")

    if not frames:
        raise FileNotFoundError(
            "No feature stores found.\n"
            "Build them first: python -m ingestion.build_india_features_synthetic"
        )

    combined = pd.concat(frames, ignore_index=True)
    log.info("Total: %s edges from %d cities", f"{len(combined):,}", len(frames))
    return combined


def _prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Selects model columns (missing ones become 0) and drops clipped targets."""
    for col in FEATURE_COLS:
        if col not in df.columns:
            log.warning("Column %s missing - filled with 0", col)
            df[col] = 0.0

    features = df[FEATURE_COLS].fillna(0)
    target = df[TARGET_COL].fillna(50)
    keep = (target > 0.5) & (target < 99.5)
    return features[keep], target[keep]


def run():
    log.info("Training the all-India safety model")

    df = load_all_cities()
    X, y = _prepare(df)
    log.info("Training samples: %s", f"{len(X):,}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SHARE, random_state=SEED
    )

    model = xgb.XGBRegressor(**MODEL_PARAMS)
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_test, y_test)],
        verbose=100,
    )

    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    rmse = float(np.sqrt(mean_squared_error(y_test, predictions)))
    r2 = r2_score(y_test, predictions)
    n_cities = int(df["city"].nunique())

    log.info("Hold-out results: MAE %.3f | RMSE %.3f | R2 %.4f", mae, rmse, r2)
    log.info("Cities: %d | train rows: %s | test rows: %s",
             n_cities, f"{len(X_train):,}", f"{len(X_test):,}")

    log.info("Computing SHAP importances ...")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test.iloc[:SHAP_SAMPLE_ROWS])
    importance = (
        pd.DataFrame({"feature": FEATURE_COLS, "importance": np.abs(shap_values).mean(0)})
        .sort_values("importance", ascending=False)
    )
    log.info("Most influential features:\n%s", importance.head(10).to_string(index=False))

    joblib.dump(model, ARTIFACTS / "india_safety_model.pkl")
    joblib.dump(explainer, ARTIFACTS / "india_shap_explainer.pkl")
    importance.to_csv(ARTIFACTS / "india_feature_importance.csv", index=False)

    metrics = {
        "mae": round(float(mae), 4),
        "rmse": round(float(rmse), 4),
        "r2": round(float(r2), 4),
        "n_cities": n_cities,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "n_features": len(FEATURE_COLS),
    }
    with open(ARTIFACTS / "india_eval_metrics.json", "w") as fh:
        json.dump(metrics, fh, indent=2)

    log.info("Artifacts written to %s", ARTIFACTS)
    return model, metrics


if __name__ == "__main__":
    run()
