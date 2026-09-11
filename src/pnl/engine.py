"""Campaign P&L engine — tertile-level economics, driven by a YAML config.

Design principles
-----------------
- Pure functions for all arithmetic; load_assumptions() is the only function
  that touches disk. This keeps unit tests fast and I/O-free.
- All economic constants come from the caller-supplied Assumptions object —
  nothing is hardcoded. Update config/pnl_assumptions.yml to change numbers.
- Granularity is tertile (High / Medium / Low propensity). Decile-level
  differentiation is statistically indefensible at this model's discrimination
  (AUC 0.598, n ≈ 618/decile with ±4-5 pp Wilson CI widths).

Key output: marginal_profit_per_contact_eur
  = (tertile gross profit 1-yr) / (tertile contacts)
  = response_rate × revenue_per_conversion − cost_per_contact
  This is the efficiency metric for the budget-sequencing recommendation:
  at what per-contact profit does adding the next tertile operate?

Revenue formulas
----------------
  revenue_per_conversion (1-yr) = balance × NIM × tenor
  ltv_per_conversion             = balance × NIM × tenor × (1 + retention)
  LTV assumes one additional renewal cycle. For a geometric perpetuity use
  balance × NIM × tenor / (1 − retention).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml


# ── Assumptions ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Assumptions:
    cost_per_contact_eur: float
    avg_deposit_balance_eur: float
    net_interest_margin: float
    deposit_tenor_yrs: float
    retention_rate: float

    @property
    def revenue_per_conversion_eur(self) -> float:
        """First-year revenue from one acquired term deposit."""
        return (
            self.avg_deposit_balance_eur
            * self.net_interest_margin
            * self.deposit_tenor_yrs
        )

    @property
    def ltv_per_conversion_eur(self) -> float:
        """Lifetime value: first year + one renewal cycle."""
        return self.revenue_per_conversion_eur * (1.0 + self.retention_rate)


_REQUIRED_KEYS = frozenset({
    "cost_per_contact_eur",
    "avg_deposit_balance_eur",
    "net_interest_margin",
    "deposit_tenor_yrs",
    "retention_rate",
})


def load_assumptions(path: str | Path) -> Assumptions:
    """Load Assumptions from a YAML file.

    Raises ValueError if any required key is absent.
    """
    raw = yaml.safe_load(Path(path).read_text())
    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise ValueError(f"pnl_assumptions.yml missing keys: {sorted(missing)}")
    return Assumptions(
        cost_per_contact_eur=float(raw["cost_per_contact_eur"]),
        avg_deposit_balance_eur=float(raw["avg_deposit_balance_eur"]),
        net_interest_margin=float(raw["net_interest_margin"]),
        deposit_tenor_yrs=float(raw["deposit_tenor_yrs"]),
        retention_rate=float(raw["retention_rate"]),
    )


# ── Per-tertile metrics ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class TertileInput:
    label: str
    contacts: int
    responders: int   # actual observed in the test set
    ci_lo: float      # Wilson 95% lower bound on response rate
    ci_hi: float      # Wilson 95% upper bound on response rate


@dataclass(frozen=True)
class TertileMetrics:
    # --- inputs echoed ---
    label: str
    contacts: int
    responders: int
    response_rate: float   # responders / contacts
    ci_lo: float
    ci_hi: float

    # --- costs ---
    contact_cost_eur: float          # contacts × cost_per_contact

    # --- revenue (1-yr and LTV) ---
    revenue_1yr_eur: float           # responders × revenue_per_conversion
    revenue_ltv_eur: float           # responders × ltv_per_conversion

    # --- profit ---
    gross_profit_1yr_eur: float      # revenue_1yr − contact_cost
    gross_profit_ltv_eur: float      # revenue_ltv − contact_cost

    # --- efficiency ratios ---
    roi_1yr: float                   # gross_profit_1yr / contact_cost
    roi_ltv: float
    cost_per_acquisition_eur: float  # contact_cost / responders; inf if 0 responders

    # --- THE KEY METRIC ---
    # Marginal profit per contact: at what per-contact rate does this tertile
    # operate? Drives the budget-sequencing recommendation.
    # = gross_profit_1yr / contacts = response_rate × rev_per_conv − cost_per_contact
    marginal_profit_per_contact_eur: float


def compute_tertile_metrics(t: TertileInput, a: Assumptions) -> TertileMetrics:
    """Derive all P&L metrics for a single tertile from inputs + assumptions."""
    response_rate = t.responders / t.contacts if t.contacts > 0 else 0.0
    contact_cost  = t.contacts * a.cost_per_contact_eur
    revenue_1yr   = t.responders * a.revenue_per_conversion_eur
    revenue_ltv   = t.responders * a.ltv_per_conversion_eur
    profit_1yr    = revenue_1yr - contact_cost
    profit_ltv    = revenue_ltv - contact_cost
    roi_1yr       = profit_1yr / contact_cost if contact_cost > 0 else float("nan")
    roi_ltv       = profit_ltv / contact_cost if contact_cost > 0 else float("nan")
    cpa           = contact_cost / t.responders if t.responders > 0 else float("inf")
    mppc          = profit_1yr / t.contacts if t.contacts > 0 else 0.0

    return TertileMetrics(
        label=t.label,
        contacts=t.contacts,
        responders=t.responders,
        response_rate=response_rate,
        ci_lo=t.ci_lo,
        ci_hi=t.ci_hi,
        contact_cost_eur=contact_cost,
        revenue_1yr_eur=revenue_1yr,
        revenue_ltv_eur=revenue_ltv,
        gross_profit_1yr_eur=profit_1yr,
        gross_profit_ltv_eur=profit_ltv,
        roi_1yr=roi_1yr,
        roi_ltv=roi_ltv,
        cost_per_acquisition_eur=cpa,
        marginal_profit_per_contact_eur=mppc,
    )


# ── Cumulative budget analysis ────────────────────────────────────────────────

@dataclass(frozen=True)
class CumulativeSlice:
    """Snapshot after committing to all tertiles up to and including this one."""
    tertiles_included: tuple[str, ...]
    contacts: int
    responders: int
    contact_cost_eur: float
    revenue_1yr_eur: float
    gross_profit_1yr_eur: float
    roi_1yr: float
    cost_per_acquisition_eur: float
    # Incremental metrics — the last tertile's contribution on top of the prior slice
    incremental_contacts: int
    incremental_responders: int
    incremental_profit_1yr_eur: float
    # Marginal profit per contact OF THE LAST TERTILE added (not the cumulative average)
    marginal_profit_per_contact_eur: float


def compute_cumulative(metrics: Sequence[TertileMetrics]) -> list[CumulativeSlice]:
    """Build cumulative slices as tertiles are added in the supplied order.

    Pass metrics in priority order (T1 first, T3 last). Each slice shows what
    the campaign looks like if you stop after that tertile: total contacts,
    total profit, and — critically — the marginal profit per contact of the
    tertile just added versus stopping at the previous one.
    """
    slices: list[CumulativeSlice] = []
    cum_contacts    = 0
    cum_responders  = 0
    cum_cost        = 0.0
    cum_revenue     = 0.0
    cum_profit      = 0.0

    for m in metrics:
        cum_contacts   += m.contacts
        cum_responders += m.responders
        cum_cost       += m.contact_cost_eur
        cum_revenue    += m.revenue_1yr_eur
        cum_profit     += m.gross_profit_1yr_eur

        roi     = cum_profit / cum_cost if cum_cost > 0 else float("nan")
        cum_cpa = cum_cost / cum_responders if cum_responders > 0 else float("inf")

        slices.append(CumulativeSlice(
            tertiles_included=tuple(x.label for x in metrics[: len(slices) + 1]),
            contacts=cum_contacts,
            responders=cum_responders,
            contact_cost_eur=cum_cost,
            revenue_1yr_eur=cum_revenue,
            gross_profit_1yr_eur=cum_profit,
            roi_1yr=roi,
            cost_per_acquisition_eur=cum_cpa,
            incremental_contacts=m.contacts,
            incremental_responders=m.responders,
            incremental_profit_1yr_eur=m.gross_profit_1yr_eur,
            marginal_profit_per_contact_eur=m.marginal_profit_per_contact_eur,
        ))

    return slices


# ── Efficiency-gap analysis ───────────────────────────────────────────────────

@dataclass(frozen=True)
class MarginalGap:
    """Efficiency drop from tertile `from_label` to tertile `to_label`."""
    from_label: str
    to_label: str
    drop_eur: float          # marginal_ppc[i] − marginal_ppc[i+1]; positive = drop
    drop_pct: float          # drop_eur / marginal_ppc[i], as a fraction (not %)
    cis_overlap: bool        # True → gap is within sampling noise
    verdict: str             # human-readable decision guidance


def _cis_overlap(a: TertileMetrics, b: TertileMetrics) -> bool:
    """True if the Wilson CI of a overlaps with that of b (open-interval test)."""
    return a.ci_lo < b.ci_hi and b.ci_lo < a.ci_hi


def compute_marginal_gaps(metrics: Sequence[TertileMetrics]) -> list[MarginalGap]:
    """Return one MarginalGap per adjacent tertile pair, in supplied order."""
    gaps: list[MarginalGap] = []
    for i in range(len(metrics) - 1):
        hi, lo = metrics[i], metrics[i + 1]
        drop_eur = hi.marginal_profit_per_contact_eur - lo.marginal_profit_per_contact_eur
        drop_pct = (
            drop_eur / hi.marginal_profit_per_contact_eur
            if hi.marginal_profit_per_contact_eur != 0
            else float("nan")
        )
        overlap = _cis_overlap(hi, lo)
        if overlap:
            verdict = (
                f"CIs overlap ({hi.ci_lo*100:.1f}–{hi.ci_hi*100:.1f}% "
                f"vs {lo.ci_lo*100:.1f}–{lo.ci_hi*100:.1f}%) — "
                f"€{drop_eur:.2f}/contact ({drop_pct*100:.1f}%) efficiency gap "
                f"is within sampling noise. Treat as a single priority tier."
            )
        else:
            verdict = (
                f"CIs do not overlap ({hi.ci_lo*100:.1f}–{hi.ci_hi*100:.1f}% "
                f"vs {lo.ci_lo*100:.1f}–{lo.ci_hi*100:.1f}%) — "
                f"€{drop_eur:.2f}/contact ({drop_pct*100:.1f}%) efficiency gap "
                f"is statistically real. This is the genuine budget decision point."
            )
        gaps.append(MarginalGap(
            from_label=hi.label,
            to_label=lo.label,
            drop_eur=drop_eur,
            drop_pct=drop_pct,
            cis_overlap=overlap,
            verdict=verdict,
        ))
    return gaps


# ── Recommendation ────────────────────────────────────────────────────────────

def recommend(metrics: Sequence[TertileMetrics]) -> str:
    """Generate a budget-sequencing recommendation as a plain-text string.

    Identifies:
    - Whether all tertiles are profitable (decision is sequencing, not stop/go)
    - Where the first CI-non-overlapping gap appears (the real break point)
    - Which tertiles should be treated as a single priority tier vs. optional
    """
    if len(metrics) < 2:
        return "Need at least two tertiles to produce a recommendation."

    gaps = compute_marginal_gaps(metrics)
    all_profitable = all(m.marginal_profit_per_contact_eur > 0 for m in metrics)

    lines: list[str] = []
    lines.append("═" * 70)
    lines.append("  FULCRUM — Campaign budget sequencing recommendation")
    lines.append("═" * 70)
    lines.append("")
    lines.append("Marginal profit per contact by tertile (1-yr):")
    lines.append("")

    for m in metrics:
        profitable = "profitable" if m.marginal_profit_per_contact_eur > 0 else "LOSS"
        lines.append(
            f"  {m.label:<14}  "
            f"response {m.response_rate*100:.1f}%  "
            f"[{m.ci_lo*100:.1f}%–{m.ci_hi*100:.1f}% CI]  "
            f"€{m.marginal_profit_per_contact_eur:.2f}/contact  "
            f"CPA €{m.cost_per_acquisition_eur:.2f}  "
            f"({profitable})"
        )

    lines.append("")
    lines.append("Efficiency gaps between adjacent tertiles:")
    lines.append("")
    for g in gaps:
        lines.append(f"  {g.from_label} → {g.to_label}:  {g.verdict}")

    lines.append("")

    if all_profitable:
        min_m = min(metrics, key=lambda m: m.marginal_profit_per_contact_eur)
        lines.append(
            f"All tertiles are profitable (floor: €{min_m.marginal_profit_per_contact_eur:.2f}/contact "
            f"in {min_m.label}). The question is not stop/go — it is sequencing "
            f"under a contact budget."
        )
    else:
        loss_labels = [
            m.label for m in metrics if m.marginal_profit_per_contact_eur <= 0
        ]
        lines.append(
            f"Note: {', '.join(loss_labels)} operate at a loss per contact — "
            f"exclude from campaign unless cross-sell or brand objectives apply."
        )

    lines.append("")

    # Find the first adjacent pair whose CIs do NOT overlap — the real break point
    first_real_break = next(
        (i + 1 for i, g in enumerate(gaps) if not g.cis_overlap),
        None,
    )

    lines.append("Recommended sequencing:")
    lines.append("")

    if first_real_break is None:
        lines.append(
            "  All adjacent CI pairs overlap — no statistically clear priority break "
            "exists. Contact all tertiles as a single tier, ordered by contact capacity."
        )
    else:
        priority_tier = [m.label for m in metrics[:first_real_break]]
        optional_tier = [m.label for m in metrics[first_real_break:]]
        break_gap = gaps[first_real_break - 1]

        lines.append(
            f"  Priority tier (commit budget here first): {' + '.join(priority_tier)}"
        )
        lines.append(
            f"    Response rate CIs overlap across this tier — "
            f"the efficiency difference is within sampling noise. "
            f"No within-tier sequencing distinction is defensible."
        )
        lines.append("")
        if optional_tier:
            lines.append(
                f"  Conditional tier (add if budget allows): {' + '.join(optional_tier)}"
            )
            lines.append(
                f"    Efficiency drops €{break_gap.drop_eur:.2f}/contact "
                f"({break_gap.drop_pct*100:.1f}%) at this boundary. "
                f"CIs do not overlap — the gap is real and reproducible, "
                f"not sampling noise. This is where a budget cap should fall "
                f"if one is needed."
            )

    lines.append("")
    lines.append("═" * 70)
    return "\n".join(lines)


# ── Formatted output helpers ──────────────────────────────────────────────────

def print_tertile_table(metrics: Sequence[TertileMetrics]) -> None:
    """Print a compact P&L table for all tertiles."""
    header = (
        f"{'Tertile':<14}  {'Contacts':>8}  {'Resp':>6}  {'Rate%':>6}  "
        f"{'CI Lo%':>7}  {'CI Hi%':>7}  {'Cost€':>9}  "
        f"{'Rev1yr€':>9}  {'Profit1yr€':>11}  {'ROI1yr':>7}  "
        f"{'RevLTV€':>9}  {'ProfitLTV€':>11}  {'ROI LTV':>8}  "
        f"{'CPA€':>7}  {'MPPC€':>7}"
    )
    print(header)
    print("─" * len(header))
    for m in metrics:
        print(
            f"{m.label:<14}  {m.contacts:>8,}  {m.responders:>6,}  "
            f"{m.response_rate*100:>6.1f}  "
            f"{m.ci_lo*100:>7.1f}  {m.ci_hi*100:>7.1f}  "
            f"{m.contact_cost_eur:>9,.0f}  "
            f"{m.revenue_1yr_eur:>9,.0f}  {m.gross_profit_1yr_eur:>11,.0f}  "
            f"{m.roi_1yr:>7.2f}  "
            f"{m.revenue_ltv_eur:>9,.0f}  {m.gross_profit_ltv_eur:>11,.0f}  "
            f"{m.roi_ltv:>8.2f}  "
            f"{m.cost_per_acquisition_eur:>7.2f}  "
            f"{m.marginal_profit_per_contact_eur:>7.2f}"
        )


def print_cumulative_table(slices: list[CumulativeSlice]) -> None:
    """Print the budget-sequencing cumulative table."""
    header = (
        f"{'Scope':<20}  {'Contacts':>8}  {'Resp':>6}  "
        f"{'Cost€':>9}  {'Profit1yr€':>11}  {'ROI1yr':>7}  {'CPA€':>7}  "
        f"{'IncrProfit€':>12}  {'MPPC€':>7}"
    )
    print(header)
    print("─" * len(header))
    for s in slices:
        scope = " + ".join(s.tertiles_included)
        print(
            f"{scope:<20}  {s.contacts:>8,}  {s.responders:>6,}  "
            f"{s.contact_cost_eur:>9,.0f}  {s.gross_profit_1yr_eur:>11,.0f}  "
            f"{s.roi_1yr:>7.2f}  {s.cost_per_acquisition_eur:>7.2f}  "
            f"{s.incremental_profit_1yr_eur:>12,.0f}  "
            f"{s.marginal_profit_per_contact_eur:>7.2f}"
        )
