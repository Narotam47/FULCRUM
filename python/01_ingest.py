"""Load raw UCI data, validate schema, write clean CSV."""

from pathlib import Path

import pandas as pd

RAW = Path("data/raw/bank-additional-full.csv")
OUT = Path("data/processed/clean.csv")


def main() -> None:
    df = pd.read_csv(RAW, sep=";")

    expected_cols = 21
    assert df.shape[1] == expected_cols, f"Expected {expected_cols} cols, got {df.shape[1]}"

    df.columns = df.columns.str.strip().str.lower().str.replace(".", "_", regex=False)

    # Encode target as binary
    df["y"] = (df["y"] == "yes").astype(int)

    # Replace "unknown" with NaN for downstream imputation
    df.replace("unknown", pd.NA, inplace=True)

    # 12 exact duplicate rows — see notebooks/01_eda.ipynb data-quality
    # decision #4. Dropping here (not just in the notebooks) keeps every
    # downstream consumer of clean.csv on the same row count.
    n_before = len(df)
    df = df.drop_duplicates()
    if n_before != len(df):
        print(f"[01_ingest] Dropped {n_before - len(df)} exact duplicate rows")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[01_ingest] {len(df):,} rows → {OUT}")


if __name__ == "__main__":
    main()
