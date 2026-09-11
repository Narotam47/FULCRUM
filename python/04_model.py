"""Train logistic regression + random forest, evaluate, write metrics.

Trains on data/processed/features.csv, which 02_feature_eng.py builds from
only the 19 BEFORE columns in docs/data_dictionary.md — `duration` is not in
that file, so it is not in X here either.

Split: time-ordered, not random-stratified. notebooks/02_split_strategy.ipynb
found random-stratified evaluation overstates test AUC by ~0.20 (0.80 vs
0.60) versus time-ordered on this dataset, because the file's macro-economic
regime shifts across row order — a model validated on a random blend of
history looks far better than it will in production, where it only ever
scores rows that come after its training window. time_ordered_split is the
default here for that reason; see src/data/split.py.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import brier_score_loss, classification_report, roc_auc_score

sys.path.insert(0, "src")
from models.train import SEED, fit_logistic_regression  # noqa: E402

IN  = Path("data/processed/features.csv")
OUT = Path("output/model_metrics.json")


def expected_calibration_error(y_true, y_prob, n_bins=10):
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(y_prob, bins) - 1, 0, n_bins - 1)
    n = len(y_true)
    e = 0.0
    for b in range(n_bins):
        mask = idx == b
        if mask.sum() == 0:
            continue
        e += (mask.sum() / n) * abs(y_prob[mask].mean() - y_true[mask].mean())
    return e


def main() -> None:
    df = pd.read_csv(IN)

    trained = fit_logistic_regression(df)
    X_train, y_train = trained.X_train, trained.y_train
    X_test, y_test = trained.X_test, trained.y_test

    results = {}

    # Logistic regression
    lr_proba = trained.model.predict_proba(X_test)[:, 1]
    results["logistic_regression"] = {
        "roc_auc": round(roc_auc_score(y_test, lr_proba), 4),
        "brier_score": round(brier_score_loss(y_test, lr_proba), 4),
        "ece_10bin": round(expected_calibration_error(y_test.values, lr_proba), 4),
        "report": classification_report(y_test, trained.model.predict(X_test), output_dict=True),
    }

    # Random forest — scaling doesn't affect trees, but reusing the same
    # scaled frame (trained.X_train/X_test) keeps both models trained on an
    # identical matrix.
    rf = RandomForestClassifier(n_estimators=200, random_state=SEED, n_jobs=-1)
    rf.fit(X_train, y_train)
    rf_proba = rf.predict_proba(X_test)[:, 1]
    results["random_forest"] = {
        "roc_auc": round(roc_auc_score(y_test, rf_proba), 4),
        "brier_score": round(brier_score_loss(y_test, rf_proba), 4),
        "ece_10bin": round(expected_calibration_error(y_test.values, rf_proba), 4),
        "report": classification_report(y_test, rf.predict(X_test), output_dict=True),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2))
    print(f"[04_model] LR AUC={results['logistic_regression']['roc_auc']}  "
          f"RF AUC={results['random_forest']['roc_auc']}  → {OUT}")


if __name__ == "__main__":
    main()
