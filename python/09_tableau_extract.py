"""
python/09_tableau_extract.py
Generate Tableau-ready extract CSVs for the FULCRUM campaign dashboard.

Privacy note
------------
The UCI Bank Marketing dataset is publicly available from the UCI Machine
Learning Repository, openly licensed for research and commercial use with no
access restrictions.  The dataset contains no individually identifiable
information (no names, account numbers, or government IDs).  Both extract
files contain only aggregated statistics (3-row tertile summaries or 100-row
percentile bins) — no individual-level attributes or model scores are exported.
Publishing to Tableau Public presents no privacy concern.

Outputs  (data/tableau/)
------------------------
fulcrum_campaign_pnl_by_tertile.csv   3 rows, one per scoring tertile
                                      Feeds Views 1 (campaign) and 3 (P&L)
fulcrum_gains_curve.csv               100 rows, one per percentile bin
                                      Feeds View 2 (gains / lift curve)

Granularity decision for the gains curve
-----------------------------------------
Pre-aggregated at percentile level (100 bins of ~62 contacts each) rather than
row-level (6,177 rows).  Rationale:
  - The gains curve saturates visually well below 100 points; row-level data
    adds no information.
  - Cumulative columns are pre-computed here so Tableau needs no Running SUM
    table calculations, which reset unexpectedly on Tableau Public.
  - Percentile-level data is smaller, faster to publish, and self-contained.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, "src")
from data.split import time_ordered_split          # noqa: E402
from models.train import fit_logistic_regression   # noqa: E402

FEATURES_CSV  = Path("data/processed/features.csv")
PNL_CONFIG    = Path("config/pnl_assumptions.yml")
OUT_DIR       = Path("data/tableau")
N_PERCENTILES = 100


# ── Tertile assignment (mirrors 07_reconcile_export.py) ──────────────────────

def proc_rank_groups(series: pd.Series, g: int = 3) -> pd.Series:
    """PROC RANK GROUPS=g TIES=MEAN: group = floor((rank-1)*g/n), clipped [0,g-1].

    Group 2 = highest propensity (T1 High), group 0 = lowest (T3 Low).
    Must match the formula in 07_reconcile_export.py and sas/03_pnl.sas.
    """
    n = len(series)
    rank = series.rank(method="average")
    return np.floor((rank - 1) * g / n).astype(int).clip(0, g - 1)


def _tertile_label(rank_series: pd.Series) -> pd.Series:
    return rank_series.map({2: "T1 High", 1: "T2 Medium", 0: "T3 Low"})


# ── Campaign + P&L summary (3 rows) ──────────────────────────────────────────

def build_tertile_summary(
    trained,
    full_df: pd.DataFrame,
    assumptions: dict,
) -> pd.DataFrame:
    """One row per scoring tertile with campaign metrics, P&L, and both base rates.

    Both base rates appear as constant columns so Tableau can draw the correct
    reference line in each view without the viewer computing either rate manually:
      - test_set_base_rate:       38.4%  overall rate in the time-ordered test set
      - full_dataset_base_rate:   11.3%  raw subscription rate across all 41,176 rows

    The test set rate is the correct denominator for View 1 (campaign performance).
    The full dataset rate provides context for stakeholders who know the raw campaign
    numbers and would be confused by the higher test-set figure.
    """
    # Score the test set
    p_hat = pd.Series(
        trained.model.predict_proba(trained.X_test)[:, 1], name="p_hat"
    )
    y = trained.y_test.reset_index(drop=True)

    tertile_rank  = proc_rank_groups(p_hat, g=3)
    tertile_label = _tertile_label(tertile_rank)

    scored = pd.DataFrame({"p_hat": p_hat, "y": y, "tertile_label": tertile_label})

    # Base rates — both computed directly from the data, not hardcoded
    test_base_rate        = round(float(y.mean()), 6)
    full_dataset_base_rate = round(float(full_df["y"].mean()), 6)

    # P&L parameters from config/pnl_assumptions.yml
    cost    = float(assumptions["cost_per_contact_eur"])
    balance = float(assumptions["avg_deposit_balance_eur"])
    nim     = float(assumptions["net_interest_margin"])
    tenor   = float(assumptions["deposit_tenor_yrs"])
    rev     = balance * nim * tenor   # revenue per conversion (€150 at point estimates)

    rows: list[dict] = []
    for group_val, label in zip([2, 1, 0], ["T1 High", "T2 Medium", "T3 Low"]):
        mask         = tertile_label == label
        sub          = scored[mask]
        n_contacts   = int(len(sub))
        n_responders = int(sub["y"].sum())
        rate         = n_responders / n_contacts

        contact_cost_total  = n_contacts   * cost
        revenue_1yr         = n_responders * rev
        gross_profit_1yr    = revenue_1yr  - contact_cost_total
        mppc                = rate * rev   - cost
        roi_1yr             = gross_profit_1yr / contact_cost_total
        cpa                 = contact_cost_total / n_responders if n_responders else float("nan")
        breakeven_cost      = rate * rev   # cost at which MPPC = 0 for this tertile

        # tertile_rank: 1 for T1 (sorts first), 2 for T2, 3 for T3
        tertile_rank_val = 3 - group_val

        rows.append({
            "tertile_label":                   label,
            "tertile_rank":                    tertile_rank_val,
            "contacts":                        n_contacts,
            "responders":                      n_responders,
            "response_rate":                   round(rate, 6),
            "test_set_base_rate":              test_base_rate,
            "full_dataset_base_rate":          full_dataset_base_rate,
            "revenue_per_conversion_eur":      round(rev, 2),
            "cost_per_contact_eur":            cost,
            "contact_cost_total_eur":          round(contact_cost_total, 2),
            "revenue_1yr_eur":                 round(revenue_1yr, 2),
            "gross_profit_1yr_eur":            round(gross_profit_1yr, 2),
            "mppc_eur":                        round(mppc, 2),
            "roi_1yr":                         round(roi_1yr, 6),
            "cost_per_acquisition_eur":        round(cpa, 2),
            "breakeven_cost_per_contact_eur":  round(breakeven_cost, 2),
            "is_recommended":                  label in ("T1 High", "T2 Medium"),
            # Marks T2 specifically — the last included tertile in the T1+T2 strategy.
            # Used in Tableau to annotate the cutoff point on bar charts.
            "is_t1t2_cutoff_row":             label == "T2 Medium",
        })

    return pd.DataFrame(rows)


# ── Gains / lift curve (100 rows) ────────────────────────────────────────────

def build_gains_curve(trained, full_df: pd.DataFrame) -> pd.DataFrame:
    """Percentile-level gains and lift curve with pre-computed cumulative columns.

    Cumulative columns are baked in here so Tableau needs no Running SUM table
    calculations, which are fragile on Tableau Public (they can reset across
    partition boundaries when filters are applied).

    Percentile 1 = the top-scoring 1% of the test set (highest p_hat);
    percentile 100 = the lowest-scoring 1%.  depth_pct runs 0.01 → 1.00 and
    is the X-axis for both the gains curve and the lift curve.

    The T1+T2 cutoff is marked at the percentile bin closest to depth_pct = 2/3,
    because each tertile holds exactly 1/3 of the test set by construction.
    """
    # Score the test set
    p_hat = pd.Series(
        trained.model.predict_proba(trained.X_test)[:, 1], name="p_hat"
    )
    y = trained.y_test.reset_index(drop=True)

    test_base_rate         = round(float(y.mean()), 6)
    full_dataset_base_rate = round(float(full_df["y"].mean()), 6)
    total_contacts         = len(y)
    total_responders       = int(y.sum())

    # Sort descending by model score (best-scoring contacts first)
    scored = (
        pd.DataFrame({"p_hat": p_hat, "y": y})
        .sort_values("p_hat", ascending=False)
        .reset_index(drop=True)
    )

    # Assign percentile bins: floor(i * 100 / n) + 1 for 0-based index i
    # This matches the intent of PROC RANK GROUPS=100 for equal-sized bins.
    n = len(scored)
    scored["percentile"] = (
        np.floor(np.arange(n) * N_PERCENTILES / n).astype(int) + 1
    ).clip(1, N_PERCENTILES)

    # Per-bin aggregation
    bins = (
        scored.groupby("percentile", sort=True)
        .agg(
            contacts_in_bin=("y", "count"),
            responders_in_bin=("y", "sum"),
            p_hat_min=("p_hat", "min"),
            p_hat_max=("p_hat", "max"),
            p_hat_mean=("p_hat", "mean"),
        )
        .reset_index()
    )

    # Cumulative columns — compute once here, not in Tableau
    bins["cumulative_contacts"]   = bins["contacts_in_bin"].cumsum()
    bins["cumulative_responders"] = bins["responders_in_bin"].cumsum()

    bins["response_rate_in_bin"]     = bins["responders_in_bin"] / bins["contacts_in_bin"]
    bins["cumulative_response_rate"] = bins["cumulative_responders"] / bins["cumulative_contacts"]

    bins["depth_pct"]                = bins["cumulative_contacts"]   / total_contacts
    bins["cumulative_responders_pct"] = bins["cumulative_responders"] / total_responders

    # Lift = cumulative response rate / base rate.  Values > 1 mean the model
    # outperforms a random contact strategy at this depth.
    bins["lift"] = bins["cumulative_response_rate"] / test_base_rate

    # Diagonal reference line for the random model (lift = 1 everywhere).
    # Providing it as a column avoids a Tableau calculated field.
    bins["random_model_pct"] = bins["depth_pct"]

    # Tertile label for colour encoding: T1 = top 33%, T2 = middle 33%, T3 = bottom
    # pd.cut bin edges: (0, 33], (33, 67], (67, 100]
    bins["tertile_label"] = pd.cut(
        bins["percentile"],
        bins=[0, 33, 67, 100],
        labels=["T1 High", "T2 Medium", "T3 Low"],
    ).astype(str)

    # Mark the bin whose depth_pct is closest to the T1+T2 boundary (2/3 ≈ 0.667)
    t1t2_boundary = 2.0 / 3.0
    diff          = (bins["depth_pct"] - t1t2_boundary).abs()
    bins["is_t1t2_cutoff"] = diff == diff.min()

    # Constant reference columns
    bins["test_set_base_rate"]        = test_base_rate
    bins["full_dataset_base_rate"]    = full_dataset_base_rate

    # Round floats for a clean CSV
    float_cols = [
        "p_hat_min", "p_hat_max", "p_hat_mean",
        "response_rate_in_bin", "cumulative_response_rate",
        "depth_pct", "cumulative_responders_pct", "lift", "random_model_pct",
    ]
    for col in float_cols:
        bins[col] = bins[col].round(6)

    # Canonical column order (identifier → volume → rates → cumulative → metadata)
    return bins[[
        "percentile", "depth_pct", "tertile_label",
        "p_hat_min", "p_hat_max", "p_hat_mean",
        "contacts_in_bin", "responders_in_bin", "response_rate_in_bin",
        "cumulative_contacts", "cumulative_responders", "cumulative_response_rate",
        "cumulative_responders_pct", "lift", "random_model_pct",
        "test_set_base_rate", "full_dataset_base_rate",
        "is_t1t2_cutoff",
    ]]


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[09_tableau_extract] Fitting model ...")
    df      = pd.read_csv(FEATURES_CSV)
    trained = fit_logistic_regression(df)
    print(
        f"  Train: {len(trained.X_train):,}  "
        f"Val: {len(trained.X_test):,}  "   # X_test here = the held-out test split
        f"Features: {len(trained.X_train.columns)}"
    )

    with open(PNL_CONFIG) as f:
        assumptions = yaml.safe_load(f)

    print("[09_tableau_extract] Building tertile summary ...")
    tertile_df = build_tertile_summary(trained, df, assumptions)
    tertile_path = OUT_DIR / "fulcrum_campaign_pnl_by_tertile.csv"
    tertile_df.to_csv(tertile_path, index=False)
    print(f"  → {tertile_path}  ({len(tertile_df)} rows × {len(tertile_df.columns)} cols)")

    print("[09_tableau_extract] Building gains / lift curve ...")
    gains_df = build_gains_curve(trained, df)
    gains_path = OUT_DIR / "fulcrum_gains_curve.csv"
    gains_df.to_csv(gains_path, index=False)
    print(f"  → {gains_path}  ({len(gains_df)} rows × {len(gains_df.columns)} cols)")

    # Sanity-check printout so the operator can spot base-rate confusion
    tsr = tertile_df["test_set_base_rate"].iloc[0]
    fdr = tertile_df["full_dataset_base_rate"].iloc[0]
    print("\n  Base rates baked into both extracts:")
    print(f"    test_set_base_rate      = {tsr:.1%}  (use for campaign reference line)")
    print(f"    full_dataset_base_rate  = {fdr:.1%}  (use for full-dataset context)")
    print(f"\n  T1+T2 cutoff bin: percentile {gains_df.loc[gains_df['is_t1t2_cutoff'], 'percentile'].values[0]}"
          f", depth = {gains_df.loc[gains_df['is_t1t2_cutoff'], 'depth_pct'].values[0]:.3f}")
    print("\n[09_tableau_extract] Done.")


if __name__ == "__main__":
    main()
