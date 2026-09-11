"""Feature engineering: select the 19 BEFORE columns, encode categoricals.

Feature set is exactly the 19 columns docs/data_dictionary.md marks as known
BEFORE a call is placed (`campaign` carries a documented caveat there but is
included per that decision). `duration` is excluded: it only exists after a
call ends, making it leakage for a model meant to score leads before they're
called. `y` is the target, passed through unchanged for 04_model.py to split
off — it is not part of the feature set.
"""

from pathlib import Path

import pandas as pd

IN  = Path("data/processed/clean.csv")
OUT = Path("data/processed/features.csv")

# The 19 BEFORE columns from docs/data_dictionary.md. `duration` (AFTER —
# leakage) is deliberately not here.
BEFORE_COLUMNS = [
    "age", "job", "marital", "education", "default", "housing", "loan",
    "contact", "month", "day_of_week", "campaign", "pdays", "previous",
    "poutcome", "emp_var_rate", "cons_price_idx", "cons_conf_idx",
    "euribor3m", "nr_employed",
]

CATEGORICAL = ["job", "marital", "education", "default", "housing", "loan",
               "contact", "month", "day_of_week", "poutcome"]


def main() -> None:
    df = pd.read_csv(IN)
    df = df[BEFORE_COLUMNS + ["y"]]

    # 01_ingest.py replaced "unknown" with NaN; restore it as its own
    # category instead of imputing — see notebooks/01_eda.ipynb data-quality
    # decisions #1-#2 (default alone is 20.9% unknown; imputing manufactures
    # an answer the data doesn't actually give us).
    for col in CATEGORICAL:
        df[col] = df[col].fillna("unknown")

    df = pd.get_dummies(df, columns=CATEGORICAL, drop_first=True, dtype=int)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[02_feature_eng] {df.shape[1] - 1} features (+ y) → {OUT}")


if __name__ == "__main__":
    main()
