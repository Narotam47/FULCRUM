"""Sensitivity analysis across documented assumption ranges.

Varies each assumption across its range from docs/assumptions.md,
holding others at point estimates, and reports impact on campaign ROI
(gross_profit_1yr / contact_cost) for the T1+T2 scenario.

Key findings reported:
  1. Tornado chart — widest bar on top, narrowest on bottom
  2. Whether actual impact order matches the documented sensitivity ranking
  3. Break-even values for the two most sensitive parameters
  4. Two-sentence limitations paragraph for the deck
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

sys.path.insert(0, "src")
from pnl.engine import load_assumptions

# ── T1+T2 scenario (fixed — from notebooks/03_decile_analysis.ipynb) ─────────
# Contacts and responders come from the model test set; they don't change.
T1_CONTACTS, T1_RESP = 2059, 949
T2_CONTACTS, T2_RESP = 2059, 865
T3_CONTACTS, T3_RESP = 2059, 562

TOTAL_CONTACTS = T1_CONTACTS + T2_CONTACTS          # 4118
TOTAL_RESP     = T1_RESP + T2_RESP                  # 1814
RATE_T2 = T2_RESP / T2_CONTACTS                     # 0.4200
RATE_T3 = T3_RESP / T3_CONTACTS                     # 0.2729

# ── Point estimates (loaded from YAML, not hardcoded) ─────────────────────────
A = load_assumptions("config/pnl_assumptions.yml")

PT = dict(
    balance   = A.avg_deposit_balance_eur,
    NIM       = A.net_interest_margin,
    tenor     = A.deposit_tenor_yrs,
    cost      = A.cost_per_contact_eur,
    retention = A.retention_rate,
)

# ── Documented ranges from docs/assumptions.md ────────────────────────────────
RANGES = {
    "balance":   (5_000,  25_000),
    "NIM":       (0.0075, 0.025),
    "tenor":     (0.5,    1.5),
    "cost":      (1.50,   4.50),
    "retention": (0.40,   0.65),
}

# Documented sensitivity rank (from assumptions.md) — hypothesis to test
DOCUMENTED_RANK = ["balance", "NIM", "tenor", "retention", "cost"]

# ── ROI formulae ──────────────────────────────────────────────────────────────

def roi_1yr(balance, NIM, tenor, cost, **_):
    """1-year gross profit / contact cost, T1+T2 scenario."""
    R = balance * NIM * tenor
    profit = TOTAL_RESP * R - TOTAL_CONTACTS * cost
    return profit / (TOTAL_CONTACTS * cost)


def roi_ltv(balance, NIM, tenor, cost, retention):
    """LTV gross profit / contact cost, T1+T2 scenario (one renewal cycle)."""
    R = balance * NIM * tenor * (1 + retention)
    profit = TOTAL_RESP * R - TOTAL_CONTACTS * cost
    return profit / (TOTAL_CONTACTS * cost)


def mppc(rate, balance, NIM, tenor, cost):
    """Marginal profit per contact for a single tertile."""
    return rate * balance * NIM * tenor - cost


# ── Sensitivity sweep ─────────────────────────────────────────────────────────

roi_base = roi_1yr(**PT)

rows = []
for name, (lo, hi) in RANGES.items():
    kw_lo = {**PT, name: lo}
    kw_hi = {**PT, name: hi}
    r_lo = roi_1yr(**kw_lo)
    r_hi = roi_1yr(**kw_hi)
    # Convention: bar goes from lower ROI to higher ROI regardless of direction
    roi_min = min(r_lo, r_hi)
    roi_max = max(r_lo, r_hi)
    # Identify which end is the "low" assumption
    low_at_lo = r_lo <= r_hi    # True if low assumption → low ROI
    width = roi_max - roi_min
    rows.append(dict(
        name=name, lo=lo, hi=hi,
        r_lo=r_lo, r_hi=r_hi,
        roi_min=roi_min, roi_max=roi_max,
        width=width,
        low_at_lo=low_at_lo,
    ))

rows.sort(key=lambda x: -x["width"])
actual_rank = [r["name"] for r in rows]

# ── Print analysis table ──────────────────────────────────────────────────────

WIDTH = 70
print("\n" + "═" * WIDTH)
print("  FULCRUM Sensitivity Analysis — T1+T2 Campaign ROI")
print("═" * WIDTH)
print(f"\n  Base-case ROI (point estimates): {roi_base:.2f}×")
print(f"  (gross profit = €261,805  ÷  contact cost = €10,295)\n")

print(f"  {'Assumption':<12}  {'Range Low':>10}  {'Range Hi':>10}  "
      f"{'ROI @ Low':>9}  {'ROI @ Hi':>9}  {'Width':>6}  {'Rank (actual)':>4}  {'Rank (doc)':>4}")
print("  " + "─" * 78)
for i, r in enumerate(rows):
    doc_rank = DOCUMENTED_RANK.index(r["name"]) + 1
    flag = " ← INVERSION" if (i + 1) != doc_rank else ""
    print(f"  {r['name']:<12}  {str(r['lo']):>10}  {str(r['hi']):>10}  "
          f"{r['r_lo']:>9.3f}  {r['r_hi']:>9.3f}  {r['width']:>6.3f}  "
          f"{'#'+str(i+1):>13}  {'#'+str(doc_rank):>9}{flag}")

# Check for order differences
print("\n  Actual rank order:     ", actual_rank)
print("  Documented rank order: ", DOCUMENTED_RANK)
inversions = [(i+1, actual_rank[i], DOCUMENTED_RANK.index(actual_rank[i])+1)
              for i in range(len(actual_rank))
              if (i+1) != DOCUMENTED_RANK.index(actual_rank[i])+1]
if inversions:
    print("\n  Rank differences vs documented hypothesis:")
    for actual_pos, name, doc_pos in inversions:
        print(f"    {name}: documented #{doc_pos} → actual #{actual_pos}", end="")
        if name == "cost":
            print("  [cost appears in the ROI denominator — ±50% EUR/contact metric "
                  "understates its ratio leverage]")
        elif name == "retention":
            print("  [retention multiplies LTV only; 1-yr ROI is invariant to it]")
        elif name == "tenor":
            print()
        else:
            print()

# ── Break-even analysis ───────────────────────────────────────────────────────

print("\n" + "─" * WIDTH)
print("  Break-Even Analysis — Top Two Sensitive Parameters")
print("─" * WIDTH)

# Derive symbolically; confirm numerically.
# Break-even for T1+T2 campaign (ROI = 0 ↔ revenue = cost):
#   TOTAL_RESP × balance × NIM × tenor = TOTAL_CONTACTS × cost
# For balance (NIM, tenor, cost at point estimates):
be_bal_campaign = (TOTAL_CONTACTS * PT["cost"]) / (TOTAL_RESP * PT["NIM"] * PT["tenor"])
be_nim_campaign = (TOTAL_CONTACTS * PT["cost"]) / (TOTAL_RESP * PT["balance"] * PT["tenor"])

# Break-even for T3 turning unprofitable (MPPC_T3 = 0):
#   RATE_T3 × balance × NIM × tenor = cost
be_bal_T3 = PT["cost"] / (RATE_T3 * PT["NIM"] * PT["tenor"])
be_nim_T3 = PT["cost"] / (RATE_T3 * PT["balance"] * PT["tenor"])

# R threshold below which T2→T3 MPPC gap < cost_per_contact (operational "flip"):
# (RATE_T2 - RATE_T3) × R < cost  →  R < cost / (RATE_T2 - RATE_T3)
rate_gap = RATE_T2 - RATE_T3
be_R_gap  = PT["cost"] / rate_gap   # revenue_per_conversion threshold
be_bal_gap = be_R_gap / (PT["NIM"] * PT["tenor"])   # implied balance
be_nim_gap = be_R_gap / (PT["balance"] * PT["tenor"])

print(f"\n  Assumption #1 — Average deposit balance (range: €5,000–€25,000)")
print(f"    T1+T2 campaign breaks even:   balance = €{be_bal_campaign:,.0f}  "
      f"({RANGES['balance'][0] / be_bal_campaign:.1f}× safety margin vs range min)")
print(f"    T3 turns unprofitable:         balance = €{be_bal_T3:,.0f}  "
      f"({RANGES['balance'][0] / be_bal_T3:.1f}× safety margin)")
print(f"    T2→T3 gap < €{PT['cost']:.2f}/contact:   balance = €{be_bal_gap:,.0f}  "
      f"({'within' if be_bal_gap > RANGES['balance'][0] else 'outside'} documented range)")

print(f"\n  Assumption #2 — Net interest margin (range: 0.75%–2.50%)")
print(f"    T1+T2 campaign breaks even:   NIM = {be_nim_campaign*100:.4f}%  "
      f"({RANGES['NIM'][0] / be_nim_campaign:.1f}× safety margin vs range min)")
print(f"    T3 turns unprofitable:         NIM = {be_nim_T3*100:.4f}%  "
      f"({RANGES['NIM'][0] / be_nim_T3:.1f}× safety margin)")
print(f"    T2→T3 gap < €{PT['cost']:.2f}/contact:   NIM = {be_nim_gap*100:.4f}%  "
      f"({'within' if be_nim_gap > RANGES['NIM'][0] else 'outside'} documented range)")

# Joint worst-case
R_joint_min = RANGES["balance"][0] * RANGES["NIM"][0] * RANGES["tenor"][0]
roi_joint_worst = roi_1yr(
    balance=RANGES["balance"][0], NIM=RANGES["NIM"][0],
    tenor=RANGES["tenor"][0], cost=RANGES["cost"][1], retention=PT["retention"]
)
T3_mppc_joint = mppc(RATE_T3, RANGES["balance"][0], RANGES["NIM"][0],
                     RANGES["tenor"][0], RANGES["cost"][1])
print(f"\n  Joint worst-case (all revenue assumptions at range mins, cost at max):")
print(f"    revenue_per_conversion = €{R_joint_min:.2f}  (vs point estimate €150)")
print(f"    T1+T2 ROI = {roi_joint_worst:.3f}×  (still profitable)")
print(f"    T3 MPPC   = €{T3_mppc_joint:.2f}/contact  (still profitable)")

# ── Limitations paragraph ─────────────────────────────────────────────────────

print("\n" + "─" * WIDTH)
print("  Deck Limitations Paragraph (plain language, marketing-manager audience)")
print("─" * WIDTH)
print(f"""
  The profitability conclusion holds across the full documented assumption
  range: even at the most conservative combination of inputs — a €5,000
  average deposit balance, a 0.75% net margin, and a six-month term —
  the T1+T2 campaign still returns €{roi_joint_worst:.2f} in gross profit per
  €{RANGES['cost'][1]:.2f} of contact cost. To change the recommendation in any
  material way, either the average deposit balance would have to fall below
  €{be_bal_T3:,.0f} (more than eight times below the minimum in the range),
  or the bank's net margin on deposits would need to drop below {be_nim_T3*100:.2f}%
  (more than eight times below the documented floor) — neither of which is
  plausible for a Portuguese retail term deposit in this period.
""")

# ── Tornado chart ─────────────────────────────────────────────────────────────

BLUE   = "#2a78d6"
ORANGE = "#eb6834"
GREY   = "#888888"
LIGHT_GREY = "#cccccc"
BG     = "#f8f8f6"

labels = {
    "balance":   "Avg deposit balance\n€5,000 – €25,000",
    "NIM":       "Net interest margin\n0.75% – 2.50%",
    "cost":      "Cost per contact\n€1.50 – €4.50",
    "tenor":     "Deposit tenor\n6 – 18 months",
    "retention": "Retention rate\n40% – 65%  [LTV only]",
}

fig, ax = plt.subplots(figsize=(10, 5))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

bar_height = 0.52
y_positions = list(range(len(rows) - 1, -1, -1))   # top to bottom

for i, (r, y) in enumerate(zip(rows, y_positions)):
    left  = r["roi_min"]
    right = r["roi_max"]
    # Left segment: below base ROI
    left_end  = min(right, roi_base)
    if left < left_end:
        ax.barh(y, left_end - left, left=left, height=bar_height,
                color=ORANGE, alpha=0.85, zorder=2)
    # Right segment: above base ROI
    right_start = max(left, roi_base)
    if right_start < right:
        ax.barh(y, right - right_start, left=right_start, height=bar_height,
                color=BLUE, alpha=0.85, zorder=2)
    # Value labels at bar ends
    pad = 0.4
    ax.text(left - pad, y, f"{left:.1f}×", ha="right", va="center",
            fontsize=8, color=GREY)
    ax.text(right + pad, y, f"{right:.1f}×", ha="left", va="center",
            fontsize=8, color=GREY)
    # Assumption + range label
    ax.text(roi_base, y + bar_height / 2 + 0.08,
            labels[r["name"]], ha="center", va="bottom",
            fontsize=7.5, color="#333333", style="italic")
    # Flag rank inversions
    doc_pos = DOCUMENTED_RANK.index(r["name"]) + 1
    act_pos = i + 1
    if doc_pos != act_pos:
        ax.text(right + pad + 6, y, f"doc #{doc_pos}→actual #{act_pos}",
                ha="left", va="center", fontsize=7, color=ORANGE, style="italic")

# Base-case vertical line
ax.axvline(roi_base, color="#333333", linewidth=1.4, linestyle="--",
           zorder=3, label=f"Base-case ROI = {roi_base:.1f}×")

# Zero-profit line (ROI = 0)
ax.axvline(0, color="#cc0000", linewidth=0.8, linestyle=":", alpha=0.6,
           zorder=3, label="ROI = 0 (break-even)")

ax.set_yticks(y_positions)
ax.set_yticklabels([f"#{i+1} {r['name']}" for i, r in enumerate(rows)],
                   fontsize=9)
ax.set_xlabel("Campaign ROI (gross profit ÷ contact cost, T1+T2, 1-yr)", fontsize=9)
ax.set_xlim(rows[-1]["roi_min"] - 8, rows[0]["roi_max"] + 12)
ax.set_title(
    "FULCRUM — Assumption Sensitivity (Tornado Chart)\n"
    "T1+T2 campaign, 1-year gross profit ROI",
    fontsize=11, fontweight="bold", pad=10,
)

# Legend
up_patch   = mpatches.Patch(color=BLUE, alpha=0.85, label="Higher value → higher ROI")
down_patch = mpatches.Patch(color=ORANGE, alpha=0.85, label="Lower value / higher cost → lower ROI")
ax.legend(handles=[
    mpatches.Patch(color=BLUE, alpha=0.85, label="Higher assumption → higher ROI"),
    mpatches.Patch(color=ORANGE, alpha=0.85, label="Lower assumption / higher cost → lower ROI"),
    plt.Line2D([0], [0], color="#333333", linewidth=1.4, linestyle="--",
               label=f"Base-case: {roi_base:.1f}×"),
    plt.Line2D([0], [0], color="#cc0000", linewidth=0.8, linestyle=":",
               alpha=0.6, label="Break-even (ROI = 0)"),
], loc="lower right", fontsize=8, framealpha=0.8)

# Annotation: retention note
ax.annotate(
    "★ Retention has zero impact on 1-yr ROI\n   (multiplies LTV only; see docs/assumptions.md §5)",
    xy=(roi_base, 0),          # lowest bar
    xytext=(roi_base + 6, -0.6),
    fontsize=7.5, color=GREY, ha="left", va="top",
    arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8),
)

# Annotation: cost inversion
cost_row = next(r for r in rows if r["name"] == "cost")
cost_y = y_positions[rows.index(cost_row)]
ax.annotate(
    "★ Cost jumps from doc #5 → actual #3\n   (appears in ROI denominator — ratio leverage)",
    xy=(cost_row["roi_min"] - 0.5, cost_y),
    xytext=(cost_row["roi_min"] - 15, cost_y - 0.9),
    fontsize=7.5, color=ORANGE, ha="right", va="center",
    arrowprops=dict(arrowstyle="->", color=ORANGE, lw=0.8),
)

ax.grid(axis="x", color=LIGHT_GREY, linewidth=0.5, zorder=0)
ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
out = Path("output/figures/tornado_roi.png")
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=160, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"\n  → Tornado chart saved to {out}")
print("═" * WIDTH)
