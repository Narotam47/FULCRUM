"""
Campaign budget allocator — greedy sequential fill.

WHY NOT LP OR INTEGER PROGRAMMING?
────────────────────────────────────────────────────────────────────────────────
A budget-constrained contact allocation across discrete tertile populations
looks like a bounded knapsack problem at first glance. The LP question is
worth answering explicitly before reaching for a solver:

    Does greedy sequential fill already produce the optimal allocation?

Answer: YES — and here is the proof.

The problem structure is:

    maximise   sum_i  MPPC_i × x_i
    subject to sum_i  c × x_i  ≤  B        (budget)
               0 ≤ x_i ≤ n_i               (capacity per tier)
               x_i integer

where MPPC_i is the marginal profit per contact for tier i, c is the
(constant) cost per contact, B is the budget, and n_i is the number of
contacts available in tier i.

Three facts collapse this to trivial greedy:

1.  Within-tier homogeneity.
    Every contact in tier i carries the same expected MPPC_i — the engine
    assigns a single response rate to the entire tier. There is no
    within-tier subpopulation to rank or select from. The only decision is
    how many contacts from each tier.

2.  The ranking is fixed and known before solving.
    MPPC_1 > MPPC_2 > MPPC_3 is established by the model and confirmed by
    the CI-gap analysis in engine.py. Because the cost per contact c is
    constant, the value-to-weight ratio MPPC_i / c is in the same order.
    This is exactly the fractional knapsack setting: greedy (fill in
    descending value-to-weight order until budget or capacity is exhausted)
    achieves the global optimum. Formal proof: any allocation that does not
    start by saturating the highest-MPPC tier first can be improved by
    swapping one lower-MPPC contact for one higher-MPPC contact, increasing
    total profit — contradicting optimality.

3.  Integer rounding error is negligible.
    The only scenario where LP relaxation beats greedy is when the optimal
    solution to the LP is non-integer and rounding it changes the objective.
    Here, rounding error ≤ (n_tiers − 1) × c = 2 × €2.50 = €5.00 maximum
    across all tier boundaries. Against a campaign profit of tens of
    thousands of euros, this is immaterial. An integer solver would return
    the same allocation or within ±1 contact per tier boundary.

Conclusion: greedy fill (T1 → T2 → T3) is optimal by construction. LP/IP
adds solver complexity, a dependency, and debugging surface area in exchange
for at most €5 in additional profit. The greedy approach is also the only
one a campaign manager can explain in a sentence: "Fill T1 completely, then
T2, then T3 with whatever remains."


WHAT "VALUE OF TARGETING" MEANS
────────────────────────────────────────────────────────────────────────────────
Given a fixed budget B, two strategies are compared at the same cost:

  Targeted  — greedy fill in MPPC order (T1 → T2 → T3 if budget remains)
  Naïve     — same budget, contacts selected at random from the full
              population (expected response rate = population base rate)

  Value of targeting = targeted gross profit − naïve gross profit (1-yr)

This is the headline metric for the deck. It answers the question every
stakeholder actually cares about: "What did we gain by building this model?"

The number is positive whenever the targeted selection has a higher blended
response rate than the population base rate — which it does whenever at
least some T1 or T2 contacts are being made (both are above the 38.4% base).
It reaches zero only when the budget is large enough to contact everyone,
at which point targeting adds no incremental value (you'd call them all
anyway).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from pnl.engine import Assumptions, TertileMetrics


# ── Per-tertile allocation output ─────────────────────────────────────────────

@dataclass(frozen=True)
class TertileAllocation:
    label: str
    contacts_available: int
    contacts_allocated: int
    contacts_fraction: float          # allocated / available (0–1)
    expected_responders: float        # contacts_allocated × response_rate
    expected_revenue_1yr_eur: float
    expected_gross_profit_1yr_eur: float
    contact_cost_eur: float
    marginal_profit_per_contact_eur: float  # inherited from TertileMetrics


# ── Full allocation result ────────────────────────────────────────────────────

@dataclass(frozen=True)
class AllocationResult:
    # ── inputs ──────────────────────────────────────────────────────────────
    budget_eur: float

    # ── per-tertile breakdown ────────────────────────────────────────────────
    allocations: tuple[TertileAllocation, ...]

    # ── aggregate campaign metrics ───────────────────────────────────────────
    budget_used_eur: float
    budget_unused_eur: float
    total_contacts: int
    total_expected_responders: float
    total_revenue_1yr_eur: float
    total_gross_profit_1yr_eur: float
    total_roi_1yr: float              # gross_profit / budget_used
    blended_cpa_eur: float            # budget_used / total_expected_responders

    # ── opportunity cost ─────────────────────────────────────────────────────
    # Profit achievable if budget were unlimited (all available contacts made)
    max_available_profit_1yr_eur: float
    # Profit left on the table by the budget constraint
    opportunity_cost_eur: float

    # ── value of targeting (THE HEADLINE) ────────────────────────────────────
    # Same budget, contacts selected at random → expected response = base_rate
    naive_base_rate: float
    naive_contacts: int               # floor(budget / cost), capped at total available
    naive_expected_responders: float
    naive_gross_profit_1yr_eur: float
    # Incremental profit from targeting vs random dialling at the same budget
    value_of_targeting_eur: float
    # Same figure as a % uplift over the naïve baseline
    value_of_targeting_pct: float


# ── Core allocation logic ─────────────────────────────────────────────────────

def allocate(
    budget_eur: float,
    tertiles: Sequence[TertileMetrics],
    assumptions: Assumptions,
    naive_base_rate: float = 0.384,
) -> AllocationResult:
    """Allocate a fixed campaign budget across tertiles using greedy sequential fill.

    Parameters
    ----------
    budget_eur:
        Total contact budget in EUR. Must be non-negative.
    tertiles:
        TertileMetrics in priority order — highest MPPC first (T1, T2, T3).
        Produced by engine.compute_tertile_metrics().
    assumptions:
        Loaded from config/pnl_assumptions.yml via engine.load_assumptions().
    naive_base_rate:
        Expected response rate for a randomly selected contact (population
        base rate). Used to compute the naïve no-targeting baseline.
        Default: 0.384 — the test-period base rate from this dataset.

    Returns
    -------
    AllocationResult with per-tertile breakdown, aggregate metrics,
    opportunity cost, and value-of-targeting headline.
    """
    if budget_eur < 0:
        raise ValueError(f"budget_eur must be non-negative; got {budget_eur}")

    c = assumptions.cost_per_contact_eur
    rev = assumptions.revenue_per_conversion_eur

    # ── greedy fill ───────────────────────────────────────────────────────────
    remaining = budget_eur
    alloc_list: list[TertileAllocation] = []

    for m in tertiles:
        max_affordable = math.floor(remaining / c) if c > 0 else 0
        contacts = min(m.contacts, max_affordable)
        cost = contacts * c
        exp_resp = contacts * m.response_rate
        exp_rev = exp_resp * rev
        exp_profit = exp_rev - cost

        alloc_list.append(TertileAllocation(
            label=m.label,
            contacts_available=m.contacts,
            contacts_allocated=contacts,
            contacts_fraction=contacts / m.contacts if m.contacts > 0 else 0.0,
            expected_responders=exp_resp,
            expected_revenue_1yr_eur=exp_rev,
            expected_gross_profit_1yr_eur=exp_profit,
            contact_cost_eur=cost,
            marginal_profit_per_contact_eur=m.marginal_profit_per_contact_eur,
        ))
        remaining -= cost

    # ── aggregate totals ──────────────────────────────────────────────────────
    budget_used = sum(a.contact_cost_eur for a in alloc_list)
    budget_unused = budget_eur - budget_used
    total_contacts = sum(a.contacts_allocated for a in alloc_list)
    total_resp = sum(a.expected_responders for a in alloc_list)
    total_rev = sum(a.expected_revenue_1yr_eur for a in alloc_list)
    total_profit = sum(a.expected_gross_profit_1yr_eur for a in alloc_list)
    roi = total_profit / budget_used if budget_used > 0 else float("nan")
    cpa = budget_used / total_resp if total_resp > 0 else float("inf")

    # ── opportunity cost (profit foregone by budget constraint) ───────────────
    max_profit = sum(m.gross_profit_1yr_eur for m in tertiles)
    opp_cost = max_profit - total_profit

    # ── naïve baseline (same budget, random contacts at base rate) ────────────
    total_available = sum(m.contacts for m in tertiles)
    naive_contacts = min(math.floor(budget_eur / c) if c > 0 else 0, total_available)
    naive_resp = naive_contacts * naive_base_rate
    naive_rev = naive_resp * rev
    naive_profit = naive_rev - naive_contacts * c

    # ── value of targeting ────────────────────────────────────────────────────
    vot = total_profit - naive_profit
    vot_pct = (vot / naive_profit * 100) if naive_profit != 0 else float("inf")

    return AllocationResult(
        budget_eur=budget_eur,
        allocations=tuple(alloc_list),
        budget_used_eur=budget_used,
        budget_unused_eur=budget_unused,
        total_contacts=total_contacts,
        total_expected_responders=total_resp,
        total_revenue_1yr_eur=total_rev,
        total_gross_profit_1yr_eur=total_profit,
        total_roi_1yr=roi,
        blended_cpa_eur=cpa,
        max_available_profit_1yr_eur=max_profit,
        opportunity_cost_eur=opp_cost,
        naive_base_rate=naive_base_rate,
        naive_contacts=naive_contacts,
        naive_expected_responders=naive_resp,
        naive_gross_profit_1yr_eur=naive_profit,
        value_of_targeting_eur=vot,
        value_of_targeting_pct=vot_pct,
    )


# ── Formatted output ──────────────────────────────────────────────────────────

def print_allocation_report(result: AllocationResult) -> None:
    """Print the full allocation report, with value-of-targeting as the headline."""
    r = result
    WIDTH = 64

    def bar(char="─", width=WIDTH):
        return char * width

    print()
    print(bar("═"))
    print("  FULCRUM — Campaign Budget Allocation Report")
    print(bar("═"))
    print(f"  Budget: €{r.budget_eur:,.0f}")
    print()

    # ── Per-tertile breakdown ─────────────────────────────────────────────────
    print("  Allocation (greedy fill — T1 → T2 → T3):")
    print()
    hdr = f"  {'Tertile':<14}  {'Avail':>6}  {'Alloc':>6}  {'Fill%':>5}  {'E[Resp]':>7}  {'Cost€':>8}  {'Profit€':>9}  {'MPPC€':>6}"
    print(hdr)
    print("  " + bar("─", len(hdr) - 2))
    for a in r.allocations:
        fill_pct = a.contacts_fraction * 100
        print(
            f"  {a.label:<14}  {a.contacts_available:>6,}  {a.contacts_allocated:>6,}  "
            f"{fill_pct:>5.1f}  {a.expected_responders:>7.1f}  "
            f"{a.contact_cost_eur:>8,.0f}  {a.expected_gross_profit_1yr_eur:>9,.0f}  "
            f"{a.marginal_profit_per_contact_eur:>6.2f}"
        )

    print()
    print(f"  {'TOTAL':<14}  {sum(a.contacts_available for a in r.allocations):>6,}  "
          f"{r.total_contacts:>6,}  "
          f"{r.total_contacts/sum(a.contacts_available for a in r.allocations)*100:>5.1f}  "
          f"{r.total_expected_responders:>7.1f}  "
          f"{r.budget_used_eur:>8,.0f}  {r.total_gross_profit_1yr_eur:>9,.0f}  "
          f"{'(blended)':>6}")
    print()
    print(f"  Budget used: €{r.budget_used_eur:,.0f}  |  "
          f"Unused: €{r.budget_unused_eur:,.0f}  |  "
          f"ROI: {r.total_roi_1yr:.1f}×  |  CPA: €{r.blended_cpa_eur:.2f}")

    # ── Opportunity cost ──────────────────────────────────────────────────────
    print()
    print("  Opportunity cost of budget constraint:")
    print(f"    Profit at full capacity (all {sum(a.contacts_available for a in r.allocations):,} contacts): "
          f"€{r.max_available_profit_1yr_eur:,.0f}")
    print(f"    Profit at budget (€{r.budget_eur:,.0f}): "
          f"€{r.total_gross_profit_1yr_eur:,.0f}")
    print(f"    Left on the table: €{r.opportunity_cost_eur:,.0f}")

    # ── VALUE OF TARGETING — HEADLINE ─────────────────────────────────────────
    print()
    print("  " + bar("═"))
    print("  ★  VALUE OF TARGETING")
    print("  " + bar("═"))
    print()
    print(f"  Naïve baseline (€{r.budget_eur:,.0f} spent, {r.naive_contacts:,} random contacts")
    print(f"    at {r.naive_base_rate*100:.1f}% population base rate):")
    print(f"    Expected responders: {r.naive_expected_responders:.1f}")
    print(f"    Expected gross profit: €{r.naive_gross_profit_1yr_eur:,.0f}")
    print()
    print(f"  Targeted allocation:")
    print(f"    Expected responders: {r.total_expected_responders:.1f}")
    print(f"    Expected gross profit: €{r.total_gross_profit_1yr_eur:,.0f}")
    print()

    vot_sign = "+" if r.value_of_targeting_eur >= 0 else ""
    print(f"  ┌─────────────────────────────────────────────────────┐")
    print(f"  │  Value of targeting:  "
          f"{vot_sign}€{r.value_of_targeting_eur:,.0f}  "
          f"({vot_sign}{r.value_of_targeting_pct:.1f}% vs naïve)  │")
    print(f"  └─────────────────────────────────────────────────────┘")
    print()
    print("  " + bar("═"))


def value_of_targeting_oneliner(result: AllocationResult) -> str:
    """One-sentence summary of the value-of-targeting figure for slides/exec summaries."""
    r = result
    sign = "+" if r.value_of_targeting_eur >= 0 else ""
    return (
        f"Targeting the top two tertiles (T1+T2) adds €{r.value_of_targeting_eur:,.0f} "
        f"({sign}{r.value_of_targeting_pct:.1f}%) in gross profit versus spending the same "
        f"€{r.budget_eur:,.0f} on {r.naive_contacts:,} randomly selected contacts."
    )
