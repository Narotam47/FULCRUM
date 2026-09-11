"""Shared model-fitting logic for the campaign propensity baseline.

Extracted out of python/04_model.py so that script and any downstream
analysis (e.g. notebooks/03_decile_analysis.ipynb) train on identical logic —
same split, same scaling, same hyperparameters — instead of two copies that
can silently drift apart.

Callers are expected to have `src` on `sys.path` already (as python/04_model.py
and the notebooks do), so this can import its sibling `data` package.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from data.split import Split, time_ordered_split

SEED = 42
TRAIN_FRAC = 0.7
VAL_FRAC = 0.15  # test is the remaining 0.15 — see src/data/split.py

# Original (pre-dummy) numeric columns from 02_feature_eng.py's BEFORE_COLUMNS.
# One-hot dummy columns are already 0/1 and are left unscaled.
NUMERIC = ["age", "campaign", "pdays", "previous", "emp_var_rate",
           "cons_price_idx", "cons_conf_idx", "euribor3m", "nr_employed"]


@dataclass
class TrainedModel:
    model: LogisticRegression
    scaler: StandardScaler
    split: Split           # the time-ordered Split of the raw (pre-scaling) frame
    X_train: pd.DataFrame  # scaled
    X_test: pd.DataFrame   # scaled
    y_train: pd.Series
    y_test: pd.Series


def fit_logistic_regression(
    features_df: pd.DataFrame,
    target_col: str = "y",
    train_frac: float = TRAIN_FRAC,
    val_frac: float = VAL_FRAC,
) -> TrainedModel:
    """Time-ordered split, scale numeric columns (fit on train only), fit LR.

    `features_df` must already be the one-hot-encoded 19-BEFORE-column matrix
    02_feature_eng.py produces (data/processed/features.csv) — this function
    only splits/scales/fits, it doesn't do feature engineering.
    """
    split = time_ordered_split(features_df, train_frac=train_frac, val_frac=val_frac)

    X_train, y_train = split.train.drop(columns=[target_col]), split.train[target_col]
    X_test, y_test = split.test.drop(columns=[target_col]), split.test[target_col]

    # Fit on train only — no test-set statistics leak into the scaler.
    scaler = StandardScaler().fit(X_train[NUMERIC])
    X_train, X_test = X_train.copy(), X_test.copy()
    X_train[NUMERIC] = scaler.transform(X_train[NUMERIC])
    X_test[NUMERIC] = scaler.transform(X_test[NUMERIC])

    model = LogisticRegression(max_iter=1000, random_state=SEED)
    model.fit(X_train, y_train)

    return TrainedModel(
        model=model, scaler=scaler, split=split,
        X_train=X_train, X_test=X_test, y_train=y_train, y_test=y_test,
    )
