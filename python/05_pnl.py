"""Campaign P&L analysis — tertile-level cost, revenue, and net profit.

Granularity: tertile (High / Medium / Low propensity), not decile.
notebooks/03_decile_analysis.ipynb found decile-to-decile differences are
within Wilson CI noise at n ≈ 618/decile; tertile is the minimum resolution
where adjacent-bucket gaps are statistically distinguishable.

Unit economics: EUR, calibrated to a Portuguese retail bank 2008–2010.
See docs/assumptions.md for full sourcing and sensitivity analysis.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from models.train import fit_logistic_regression  # noqa: E402

FEATURES = Path("data/processed/features.csv")
OUT_DIR  = Path("output/reports")

# ── Unit economics (EUR) ──────────────────────────────────────────────────────
# All figures are point estimates; see docs/assumptions.md for defensible
# ranges and sensitivity rankings.
COST_PER_CONTACT   = 2.50     # EUR per outbound call (rank-5 sensitivity)
AVG_DEPOSIT_BALANCE = 10_000  # EUR average term deposit (rank-1 sensitivity)
NET_INTEREST_MARGIN =  0.015  # 1.50% annual net margin on deposit (rank 2)
DEPOSIT_TENOR_YRS  =  1.0    # years (12-month term; rank 3)
RETENTION_RATE     =  0.50   # fraction rolling over at maturity (rank 4)

# First-year revenue per acquired customer
#   = balance × NIM × tenor
REVENUE_PER_CONVERSION = AVG_DEPOSIT_BALANCE * NET_INTEREST_MARGIN * DEPOSIT_TENOR_YRS

# Lifetime-value multiplier: 1 + retention (one renewal cycle)
# For a fuller LTV, extend to: 1 / (1 - retention) for perpetuity.
LTV_MULTIPLIER = 1 + RETENTION_RATE


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half   = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def build_pnl(
    group_label: str,
    n: int,
    actual_resp: int,
    pred_resp_rate: float,
) -> dict:
    actual_rate = actual_resp / n if n > 0 else 0.0
    ci_lo, ci_hi = wilson_ci(actual_resp, n)

    cost        = n * COST_PER_CONTACT
    revenue_1yr = actual_resp * REVENUE_PER_CONVERSION
    revenue_ltv = actual_resp * REVENUE_PER_CONVERSION * LTV_MULTIPLIER
    profit_1yr  = revenue_1yr - cost
    profit_ltv  = revenue_ltv - cost
    roi_1yr     = profit_1yr / cost if cost > 0 else float("nan")
    roi_ltv     = profit_ltv / cost if cost > 0 else float("nan")
    lift        = actual_rate / 0.384  # test-period base rate

    return {
        "Tertile":               group_label,
        "Contacts":              n,
        "Actual Responders":     actual_resp,
        "Response Rate (%)":     round(actual_rate * 100, 1),
        "CI 95% Lo (%)":         round(ci_lo * 100, 1),
        "CI 95% Hi (%)":         round(ci_hi * 100, 1),
        "Lift vs Base Rate":     round(lift, 3),
        "Predicted Rate (%)":    round(pred_resp_rate * 100, 1),
        "Cost (EUR)":            round(cost, 0),
        "Revenue 1-yr (EUR)":    round(revenue_1yr, 0),
        "Net Profit 1-yr (EUR)": round(profit_1yr, 0),
        "ROI 1-yr":              round(roi_1yr, 3),
        "Revenue LTV (EUR)":     round(revenue_ltv, 0),
        "Net Profit LTV (EUR)":  round(profit_ltv, 0),
        "ROI LTV":               round(roi_ltv, 3),
    }


def main() -> None:
    df = pd.read_csv(FEATURES)

    trained = fit_logistic_regression(df)
    test_df = trained.split.test.copy()

    # Score test set
    X_test = trained.X_test
    test_df = test_df.reset_index(drop=True)
    test_df["pred_proba"] = trained.model.predict_proba(X_test)[:, 1]

    # Rank into tertiles (T1 = highest propensity)
    test_df["tertile_rank"] = pd.qcut(
        test_df["pred_proba"], q=3, labels=False, duplicates="drop"
    )
    # qcut labels 0,1,2 low-to-high; flip so T1 = highest
    test_df["tertile"] = test_df["tertile_rank"].apply(lambda x: 3 - x)

    # Tertile boundaries (for documentation)
    boundaries = test_df.groupby("tertile")["pred_proba"].agg(["min", "max"])

    rows = []
    for t in [1, 2, 3]:
        g = test_df[test_df["tertile"] == t]
        n           = len(g)
        actual_resp = int(g["y"].sum())
        # mean predicted probability for this tertile
        pred_rate   = float(g["pred_proba"].mean())
        label       = {1: "T1 — High", 2: "T2 — Medium", 3: "T3 — Low"}[t]
        rows.append(build_pnl(label, n, actual_resp, pred_rate))

    # Roll-up row: whole test set treated as contacted
    n_total   = len(test_df)
    r_total   = int(test_df["y"].sum())
    ci_lo_all, ci_hi_all = wilson_ci(r_total, n_total)
    all_rate  = r_total / n_total
    rows.append({
        "Tertile":               "ALL (unselected)",
        "Contacts":              n_total,
        "Actual Responders":     r_total,
        "Response Rate (%)":     round(all_rate * 100, 1),
        "CI 95% Lo (%)":         round(ci_lo_all * 100, 1),
        "CI 95% Hi (%)":         round(ci_hi_all * 100, 1),
        "Lift vs Base Rate":     1.000,
        "Predicted Rate (%)":    round(float(test_df["pred_proba"].mean()) * 100, 1),
        "Cost (EUR)":            round(n_total * COST_PER_CONTACT, 0),
        "Revenue 1-yr (EUR)":    round(r_total * REVENUE_PER_CONVERSION, 0),
        "Net Profit 1-yr (EUR)": round(r_total * REVENUE_PER_CONVERSION - n_total * COST_PER_CONTACT, 0),
        "ROI 1-yr":              round((r_total * REVENUE_PER_CONVERSION - n_total * COST_PER_CONTACT)
                                       / (n_total * COST_PER_CONTACT), 3),
        "Revenue LTV (EUR)":     round(r_total * REVENUE_PER_CONVERSION * LTV_MULTIPLIER, 0),
        "Net Profit LTV (EUR)":  round(r_total * REVENUE_PER_CONVERSION * LTV_MULTIPLIER - n_total * COST_PER_CONTACT, 0),
        "ROI LTV":               round((r_total * REVENUE_PER_CONVERSION * LTV_MULTIPLIER - n_total * COST_PER_CONTACT)
                                       / (n_total * COST_PER_CONTACT), 3),
    })

    pnl = pd.DataFrame(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "pnl_tertile_summary.csv"
    pnl.to_csv(out_path, index=False)

    # Print readable summary
    print("\n── FULCRUM Campaign P&L — Tertile Summary ──────────────────────────────")
    print(f"   Unit economics: €{COST_PER_CONTACT:.2f}/contact | €{AVG_DEPOSIT_BALANCE:,.0f} avg balance |"
          f" {NET_INTEREST_MARGIN*100:.2f}% NIM | {DEPOSIT_TENOR_YRS:.0f}-yr tenor | {RETENTION_RATE*100:.0f}% rollover")
    print(f"   Revenue per conversion (1-yr): €{REVENUE_PER_CONVERSION:.0f}"
          f"  |  LTV (1 renewal): €{REVENUE_PER_CONVERSION * LTV_MULTIPLIER:.0f}")
    print(f"   Test-period base rate: 38.4%  |  Test set: {n_total:,} contacts\n")

    display_cols = [
        "Tertile", "Contacts", "Response Rate (%)", "CI 95% Lo (%)", "CI 95% Hi (%)",
        "Lift vs Base Rate", "Cost (EUR)", "Net Profit 1-yr (EUR)", "ROI 1-yr",
        "Net Profit LTV (EUR)", "ROI LTV",
    ]
    print(pnl[display_cols].to_string(index=False))
    print(f"\n   → {out_path}")

    # Score-band boundaries
    print("\n── Tertile Probability Bands ──────────────────────────────────────────")
    for t in [1, 2, 3]:
        lo = boundaries.loc[t, "min"]
        hi = boundaries.loc[t, "max"]
        label = {1: "T1 High  ", 2: "T2 Medium", 3: "T3 Low   "}[t]
        print(f"   {label}  pred_proba ∈ [{lo:.4f}, {hi:.4f}]")

    # Break-even contact cost
    avg_conv_rate = r_total / n_total
    breakeven_cost = avg_conv_rate * REVENUE_PER_CONVERSION
    print(f"\n   Break-even cost per contact (at overall conv rate {avg_conv_rate*100:.1f}%): "
          f"€{breakeven_cost:.2f}  (current: €{COST_PER_CONTACT:.2f})")


if __name__ == "__main__":
    main()
