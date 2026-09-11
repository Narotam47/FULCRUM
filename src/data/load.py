"""Strict loader for the UCI Bank Marketing dataset (bank-additional-full.csv).

The UCI archive ships two variants side by side:
  - bank-additional-full.csv  (41,188 rows, 21 cols incl. socio-economic indicators)
  - bank-full.csv             (45,211 rows, 17 cols, older/smaller feature set)

This loader accepts ONLY bank-additional-full.csv. It validates row count and
column schema (names, order, and dtypes) before doing anything else, and
raises rather than silently coercing or dropping bad rows. Schema drift is a
signal something upstream changed — silently adapting to it hides that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

EXPECTED_ROWS = 41_188

# Column name -> pandas dtype, in source-file order. Order is enforced.
SCHEMA: dict[str, str] = {
    "age": "int64",
    "job": "category",
    "marital": "category",
    "education": "category",
    "default": "category",
    "housing": "category",
    "loan": "category",
    "contact": "category",
    "month": "category",
    "day_of_week": "category",
    "duration": "int64",
    "campaign": "int64",
    "pdays": "int64",
    "previous": "int64",
    "poutcome": "category",
    "emp.var.rate": "float64",
    "cons.price.idx": "float64",
    "cons.conf.idx": "float64",
    "euribor3m": "float64",
    "nr.employed": "float64",
    "y": "category",
}

# bank-full.csv has 'balance' and 'day' instead of the economic indicators
# and day_of_week — a single distinguishing column is enough to catch it.
BANK_FULL_SIGNATURE_COLUMN = "balance"


class SchemaValidationError(RuntimeError):
    """Raised when the input file does not match the expected bank-additional schema."""


def load_bank_additional(path: str | Path) -> pd.DataFrame:
    """Load and validate bank-additional-full.csv. Raises on any schema drift."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")

    # Read everything as string first — dtype casting happens explicitly
    # below, not via pandas' type inference, so bad values raise instead
    # of silently becoming NaN or the wrong type.
    df = pd.read_csv(path, sep=";", dtype=str)

    _validate_columns(df, path)
    _validate_row_count(df, path)
    df = _cast_dtypes(df, path)

    return df


def _validate_columns(df: pd.DataFrame, path: Path) -> None:
    actual = list(df.columns)
    expected = list(SCHEMA.keys())

    if BANK_FULL_SIGNATURE_COLUMN in actual:
        raise SchemaValidationError(
            f"{path} looks like bank-full.csv (has a '{BANK_FULL_SIGNATURE_COLUMN}' "
            "column) — this loader only accepts bank-additional-full.csv."
        )

    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    if missing or extra:
        raise SchemaValidationError(
            f"Column mismatch in {path}.\n"
            f"  Missing:    {missing or 'none'}\n"
            f"  Unexpected: {extra or 'none'}"
        )

    if actual != expected:
        raise SchemaValidationError(
            f"Column order mismatch in {path}.\n"
            f"  Expected: {expected}\n"
            f"  Actual:   {actual}"
        )


def _validate_row_count(df: pd.DataFrame, path: Path) -> None:
    if len(df) != EXPECTED_ROWS:
        raise SchemaValidationError(
            f"Row count mismatch in {path}: expected {EXPECTED_ROWS:,}, got "
            f"{len(df):,}. Possible causes: truncated download, wrong dataset "
            "version, or an extra/missing header row."
        )


def _cast_dtypes(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    for col, dtype in SCHEMA.items():
        if dtype in ("int64", "float64"):
            numeric = pd.to_numeric(df[col], errors="coerce")
            bad = df[col][numeric.isna() & df[col].notna()]
            if not bad.empty:
                raise SchemaValidationError(
                    f"Column '{col}' in {path} expected dtype {dtype} but has "
                    f"non-numeric values, e.g. {bad.unique()[:5].tolist()}"
                )
            df[col] = numeric.astype(dtype)
        else:
            df[col] = df[col].astype(dtype)
    return df


if __name__ == "__main__":
    default_path = Path("data/raw/bank-additional-full.csv")
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    frame = load_bank_additional(src)
    print(f"Loaded {len(frame):,} rows x {len(frame.columns)} cols from {src}")
    print(frame.dtypes)
