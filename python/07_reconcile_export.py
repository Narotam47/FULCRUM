"""Export Python model outputs for SAS reconciliation.

Writes four CSVs to data/reconciliation/python_outputs/ that mirror what
sas/04_reconcile_export.sas writes to data/reconciliation/sas_outputs/.
python/08_reconcile.py then reads both directories and produces the
comparison table.

Output files
------------
coef_table.csv       : feature_name, estimate, std_err  (intercept + 52 betas)
tertile_boundaries.csv: tertile, p_hat_min, p_hat_max, p_hat_mean
tertile_rates.csv    : tertile, contacts, responders, response_rate
tertile_pnl.csv      : tertile, mppc_eur, gross_profit_1yr_eur, roi_1yr, cpa_eur
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from data.split import time_ordered_split           # noqa: E402
from models.train import fit_logistic_regression    # noqa: E402
from pnl.engine import load_assumptions, compute_tertile_metrics, TertileInput  # noqa: E402

FEATURES_CSV  = Path("data/processed/features.csv")
PNL_CONFIG    = Path("config/pnl_assumptions.yml")
OUT_DIR       = Path("data/reconciliation/python_outputs")

TERTILE_ORDER = ["T1 High", "T2 Medium", "T3 Low"]


# ── Tertile assignment ────────────────────────────────────────────────────────

def proc_rank_groups(series: pd.Series, g: int = 3) -> pd.Series:
    """Mimic PROC RANK GROUPS=g TIES=MEAN exactly.

    SAS formula: group = floor((rank - 1) * g / n)
      rank: 1-based, with tied values receiving the average of their ranks
            (method='average' in pandas, equivalent to SAS TIES=MEAN).
      n:    number of non-missing observations.
      group: integer in [0, g-1]; 0 = lowest, g-1 = highest.

    This is the reference implementation for Python-side tertile assignment
    so that both pipelines use the same grouping rule before comparing
    response rates.  Any deviation from this formula is a reconciliation gap.
    """
    n = len(series)
    rank = series.rank(method="average")          # pandas average = SAS TIES=MEAN
    return np.floor((rank - 1) * g / n).astype(int).clip(0, g - 1)


def assign_tertile_labels(rank_series: pd.Series) -> pd.Series:
    return rank_series.map({2: "T1 High", 1: "T2 Medium", 0: "T3 Low"})


# ── Exporters ─────────────────────────────────────────────────────────────────

def export_coefficients(trained, out_dir: Path) -> None:
    """Export intercept + all beta coefficients with feature names.

    The feature names come from the one-hot-encoded design matrix after
    pd.get_dummies(drop_first=True).  These names use Python conventions
    (hyphens, dots preserved) — 08_reconcile.py normalizes them for matching
    with SAS ODS ParameterEstimates output (which uses the CLASS variable
    name + ClassVal0 level, similarly normalized).
    """
    feats = list(trained.X_train.columns)
    coef = pd.DataFrame({
        "feature_name": ["Intercept"] + feats,
        "estimate":     [float(trained.model.intercept_[0])] + list(trained.model.coef_[0]),
        "source":       "python_lr_l2_c1.0",   # L2 regularisation, C=1.0 (sklearn default)
    })
    out = out_dir / "coef_table.csv"
    coef.to_csv(out, index=False)
    print(f"  [{len(coef):>3} params] {out}")


def export_tertile_outputs(trained, out_dir: Path) -> None:
    """Export tertile boundaries, response rates, and P&L economics.

    Tertile assignment uses proc_rank_groups() — the Python mimic of
    PROC RANK GROUPS=3 TIES=MEAN — so that any disagreement in the
    comparison table is a real model-output difference, not a
    grouping-rule artefact.
    """
    p_hat = pd.Series(
        trained.model.predict_proba(trained.X_test)[:, 1],
        name="p_hat",
    )
    y = trained.y_test.reset_index(drop=True)

    tertile_rank  = proc_rank_groups(p_hat, g=3)
    tertile_label = assign_tertile_labels(tertile_rank)

    scored = pd.DataFrame({"p_hat": p_hat, "y": y, "tertile": tertile_label})

    # ── tertile_boundaries.csv ────────────────────────────────────────────────
    bounds = (
        scored.groupby("tertile", sort=False)["p_hat"]
        .agg(p_hat_min="min", p_hat_max="max", p_hat_mean="mean")
        .reindex(TERTILE_ORDER)
        .reset_index()
    )
    bounds.to_csv(out_dir / "tertile_boundaries.csv", index=False)
    print(f"  [boundaries]  {out_dir / 'tertile_boundaries.csv'}")

    # ── tertile_rates.csv ─────────────────────────────────────────────────────
    rates = (
        scored.groupby("tertile", sort=False)
        .agg(contacts=("y", "count"), responders=("y", "sum"))
        .reindex(TERTILE_ORDER)
        .reset_index()
    )
    rates["response_rate"] = rates["responders"] / rates["contacts"]
    rates.to_csv(out_dir / "tertile_rates.csv", index=False)
    print(f"  [rates]       {out_dir / 'tertile_rates.csv'}")

    # ── tertile_pnl.csv ───────────────────────────────────────────────────────
    assumptions = load_assumptions(PNL_CONFIG)
    rows: list[dict] = []
    for _, r in rates.iterrows():
        ci_half = 1.96 * np.sqrt(
            r["response_rate"] * (1 - r["response_rate"]) / r["contacts"]
        )
        m = compute_tertile_metrics(
            TertileInput(
                label=r["tertile"],
                contacts=int(r["contacts"]),
                responders=int(r["responders"]),
                ci_lo=max(0.0, r["response_rate"] - ci_half),
                ci_hi=min(1.0, r["response_rate"] + ci_half),
            ),
            assumptions,
        )
        rows.append({
            "tertile":              r["tertile"],
            "mppc_eur":             m.marginal_profit_per_contact_eur,
            "gross_profit_1yr_eur": m.gross_profit_1yr_eur,
            "roi_1yr":              m.roi_1yr,
            "cpa_eur":              m.cost_per_acquisition_eur,
            "response_rate":        m.response_rate,
        })
    pd.DataFrame(rows).to_csv(out_dir / "tertile_pnl.csv", index=False)
    print(f"  [pnl]         {out_dir / 'tertile_pnl.csv'}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[07_reconcile_export] Fitting Python model ...")
    df = pd.read_csv(FEATURES_CSV)
    trained = fit_logistic_regression(df)
    print(
        f"  Train: {len(trained.X_train):,} rows  "
        f"Test: {len(trained.X_test):,} rows  "
        f"Features: {len(trained.X_train.columns)}"
    )

    export_coefficients(trained, OUT_DIR)
    export_tertile_outputs(trained, OUT_DIR)

    print(f"[07_reconcile_export] Done. Outputs in {OUT_DIR}")


if __name__ == "__main__":
    main()
