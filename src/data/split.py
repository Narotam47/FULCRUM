"""Train/val/test split strategies for the campaign propensity model.

Two strategies, same shape in and out:

  - time_ordered_split      contiguous slices in row order. Valid because the
    EDA confirmed row order is a reliable time proxy for this dataset:
    emp.var.rate changes value at only 11 points across all 41,188 rows, in
    contiguous blocks — consistent with a chronologically sorted file.

  - random_stratified_split sklearn train_test_split, stratified on the
    target. The conventional baseline this project's split strategy is
    argued against — see notebooks/02_split_strategy.ipynb for why the
    time-ordered split, not this one, is used to evaluate the model.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.model_selection import train_test_split


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


def _test_frac(train_frac: float, val_frac: float) -> float:
    if not (0 < train_frac < 1) or not (0 < val_frac < 1):
        raise ValueError("train_frac and val_frac must each be in (0, 1)")
    test_frac = round(1 - train_frac - val_frac, 10)
    if test_frac <= 0:
        raise ValueError(f"train_frac + val_frac must be < 1, got {train_frac + val_frac}")
    return test_frac


def time_ordered_split(df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15) -> Split:
    """Contiguous chronological slices: train = earliest rows, test = latest.

    Assumes `df` is already in chronological row order and does NOT shuffle —
    shuffling would defeat the point of a time-ordered split.
    """
    _test_frac(train_frac, val_frac)
    n = len(df)
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)

    return Split(
        train=df.iloc[:train_end].reset_index(drop=True),
        val=df.iloc[train_end:val_end].reset_index(drop=True),
        test=df.iloc[val_end:].reset_index(drop=True),
    )


def random_stratified_split(
    df: pd.DataFrame,
    target_col: str = "y",
    train_frac: float = 0.7,
    val_frac: float = 0.15,
    random_state: int = 42,
) -> Split:
    """Random split, stratified on `target_col` in every partition."""
    test_frac = _test_frac(train_frac, val_frac)

    train_val, test = train_test_split(
        df, test_size=test_frac, stratify=df[target_col], random_state=random_state
    )
    val_of_train_val = val_frac / (train_frac + val_frac)
    train, val = train_test_split(
        train_val, test_size=val_of_train_val, stratify=train_val[target_col],
        random_state=random_state,
    )

    return Split(
        train=train.reset_index(drop=True),
        val=val.reset_index(drop=True),
        test=test.reset_index(drop=True),
    )
