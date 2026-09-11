"""Unit tests for src/pnl/allocate.py.

All expected values are hand-computed from first principles below each
test class. Floating-point comparisons use pytest.approx(abs=0.01).

SHARED ASSUMPTIONS (A2)
────────────────────────
  cost_per_contact  = 2.00
  balance           = 10_000
  NIM               = 0.01
  tenor             = 1.0
  retention         = 0.50

  revenue_per_conversion = 10_000 × 0.01 × 1.0  = 100.00
  ltv_per_conversion     = 100 × 1.50            = 150.00

SHARED TERTILE INPUTS
──────────────────────
  T1: 100 contacts, 60 responders → response_rate=0.60
      MPPC = 0.60×100 − 2.00 = 58.00  (>base_rate)
  T2: 100 contacts, 20 responders → response_rate=0.20
      MPPC = 0.20×100 − 2.00 = 18.00  (<base_rate)
  base_rate = 0.40

  Full-capacity profit (all 200 contacts):
    T1: 100 contacts → cost=200, rev=60×100=6000, profit=5800
    T2: 100 contacts → cost=200, rev=20×100=2000, profit=1800
    total profit = 7600
"""

import math
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pnl.engine import Assumptions, TertileInput, compute_tertile_metrics
from pnl.allocate import allocate, TertileAllocation, AllocationResult

APPROX = pytest.approx

# ── Shared fixtures ────────────────────────────────────────────────────────────

A2 = Assumptions(
    cost_per_contact_eur=2.00,
    avg_deposit_balance_eur=10_000,
    net_interest_margin=0.01,
    deposit_tenor_yrs=1.0,
    retention_rate=0.50,
)

M1 = compute_tertile_metrics(
    TertileInput("T1", contacts=100, responders=60, ci_lo=0.50, ci_hi=0.70), A2
)
M2 = compute_tertile_metrics(
    TertileInput("T2", contacts=100, responders=20, ci_lo=0.10, ci_hi=0.30), A2
)
BASE_RATE = 0.40   # population average used for naïve baseline
FULL_CAP_PROFIT = M1.gross_profit_1yr_eur + M2.gross_profit_1yr_eur  # 7600


# ══════════════════════════════════════════════════════════════════════════════
# Budget = €300 (exactly 150 contacts worth)
# ──────────────────────────────────────────────────────────────────────────────
# Greedy:
#   T1: min(100, floor(300/2))=min(100,150)=100 contacts → cost=200, remaining=100
#   T2: min(100, floor(100/2))=min(100,50)=50 contacts  → cost=100, remaining=0
#
# T1 allocation:
#   contacts=100, fraction=1.0, e_resp=60.0, revenue=6000, profit=5800
# T2 allocation:
#   contacts=50,  fraction=0.5, e_resp=10.0, revenue=1000, profit= 900
#
# Totals:
#   used=300, unused=0, contacts=150, e_resp=70.0
#   revenue=7000, profit=6700, roi=6700/300=22.333, cpa=300/70=4.286
#
# Opportunity cost:
#   max_profit=7600, opp_cost=7600−6700=900
#
# Naïve (150 contacts at 0.40):
#   e_resp=60.0, revenue=60×100=6000, profit=6000−300=5700
#
# Value of targeting:
#   vot=6700−5700=1000, vot_pct=1000/5700×100=17.54%
# ══════════════════════════════════════════════════════════════════════════════

class TestBudget300:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = allocate(300.00, [M1, M2], A2, naive_base_rate=BASE_RATE)

    # ── allocations ───────────────────────────────────────────────────────────
    def test_t1_contacts(self):
        assert self.r.allocations[0].contacts_allocated == 100

    def test_t1_fraction(self):
        assert self.r.allocations[0].contacts_fraction == APPROX(1.0, abs=1e-9)

    def test_t1_expected_responders(self):
        # 100 × 0.60 = 60.0
        assert self.r.allocations[0].expected_responders == APPROX(60.0, abs=0.01)

    def test_t1_cost(self):
        assert self.r.allocations[0].contact_cost_eur == APPROX(200.0, abs=0.01)

    def test_t1_profit(self):
        # 6000 − 200 = 5800
        assert self.r.allocations[0].expected_gross_profit_1yr_eur == APPROX(5800.0, abs=0.01)

    def test_t2_contacts(self):
        # floor(100 remaining / 2.00) = 50, capped at 100 available → 50
        assert self.r.allocations[1].contacts_allocated == 50

    def test_t2_fraction(self):
        assert self.r.allocations[1].contacts_fraction == APPROX(0.5, abs=1e-9)

    def test_t2_expected_responders(self):
        # 50 × 0.20 = 10.0
        assert self.r.allocations[1].expected_responders == APPROX(10.0, abs=0.01)

    def test_t2_profit(self):
        # 50 × 0.20 × 100 − 50 × 2.00 = 1000 − 100 = 900
        assert self.r.allocations[1].expected_gross_profit_1yr_eur == APPROX(900.0, abs=0.01)

    # ── aggregate ─────────────────────────────────────────────────────────────
    def test_budget_used(self):
        assert self.r.budget_used_eur == APPROX(300.0, abs=0.01)

    def test_budget_unused(self):
        assert self.r.budget_unused_eur == APPROX(0.0, abs=0.01)

    def test_total_contacts(self):
        assert self.r.total_contacts == 150

    def test_total_expected_responders(self):
        assert self.r.total_expected_responders == APPROX(70.0, abs=0.01)

    def test_total_revenue(self):
        # 60×100 + 10×100 = 7000
        assert self.r.total_revenue_1yr_eur == APPROX(7000.0, abs=0.01)

    def test_total_profit(self):
        # 5800 + 900 = 6700
        assert self.r.total_gross_profit_1yr_eur == APPROX(6700.0, abs=0.01)

    def test_roi(self):
        # 6700 / 300 = 22.333...
        assert self.r.total_roi_1yr == APPROX(6700.0 / 300.0, abs=0.01)

    def test_cpa(self):
        # 300 / 70 = 4.286
        assert self.r.blended_cpa_eur == APPROX(300.0 / 70.0, abs=0.01)

    # ── opportunity cost ──────────────────────────────────────────────────────
    def test_max_available_profit(self):
        # all 200 contacts: 5800 + 1800 = 7600
        assert self.r.max_available_profit_1yr_eur == APPROX(7600.0, abs=0.01)

    def test_opportunity_cost(self):
        # 7600 − 6700 = 900
        assert self.r.opportunity_cost_eur == APPROX(900.0, abs=0.01)

    # ── naïve baseline ────────────────────────────────────────────────────────
    def test_naive_contacts(self):
        # floor(300 / 2.00) = 150, capped at 200 available → 150
        assert self.r.naive_contacts == 150

    def test_naive_expected_responders(self):
        # 150 × 0.40 = 60.0
        assert self.r.naive_expected_responders == APPROX(60.0, abs=0.01)

    def test_naive_profit(self):
        # 60 × 100 − 300 = 6000 − 300 = 5700
        assert self.r.naive_gross_profit_1yr_eur == APPROX(5700.0, abs=0.01)

    # ── VALUE OF TARGETING ────────────────────────────────────────────────────
    def test_value_of_targeting_eur(self):
        # 6700 − 5700 = 1000
        assert self.r.value_of_targeting_eur == APPROX(1000.0, abs=0.01)

    def test_value_of_targeting_pct(self):
        # 1000 / 5700 × 100 = 17.54%
        assert self.r.value_of_targeting_pct == APPROX(1000.0 / 5700.0 * 100, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Budget = €150 (75 contacts — does not fully fill T1)
# ──────────────────────────────────────────────────────────────────────────────
# Greedy:
#   T1: min(100, floor(150/2))=min(100,75)=75 contacts → cost=150, remaining=0
#   T2: min(100, 0)=0 contacts
#
# T1 allocation:
#   contacts=75, fraction=0.75, e_resp=75×0.60=45.0, profit=45×100−150=4350
# T2 allocation:
#   contacts=0,  fraction=0.0, e_resp=0, profit=0
#
# Totals:
#   used=150, profit=4350, roi=4350/150=29.0, cpa=150/45=3.333
#
# Opportunity cost: 7600−4350=3250
#
# Naïve (75 contacts at 0.40):
#   e_resp=30.0, profit=30×100−150=2850
#
# Value of targeting: 4350−2850=1500, pct=1500/2850×100=52.63%
# ══════════════════════════════════════════════════════════════════════════════

class TestBudget150_PartialT1:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = allocate(150.00, [M1, M2], A2, naive_base_rate=BASE_RATE)

    def test_t1_contacts(self):
        assert self.r.allocations[0].contacts_allocated == 75

    def test_t2_contacts_zero(self):
        assert self.r.allocations[1].contacts_allocated == 0

    def test_t2_profit_zero(self):
        assert self.r.allocations[1].expected_gross_profit_1yr_eur == APPROX(0.0, abs=0.01)

    def test_total_contacts(self):
        assert self.r.total_contacts == 75

    def test_total_profit(self):
        # 45×100 − 150 = 4350
        assert self.r.total_gross_profit_1yr_eur == APPROX(4350.0, abs=0.01)

    def test_roi(self):
        # 4350 / 150 = 29.0
        assert self.r.total_roi_1yr == APPROX(29.0, abs=0.01)

    def test_cpa(self):
        # 150 / 45 = 3.333...
        assert self.r.blended_cpa_eur == APPROX(150.0 / 45.0, abs=0.001)

    def test_opportunity_cost(self):
        # 7600 − 4350 = 3250
        assert self.r.opportunity_cost_eur == APPROX(3250.0, abs=0.01)

    def test_naive_profit(self):
        # 75×0.40×100 − 150 = 3000 − 150 = 2850
        assert self.r.naive_gross_profit_1yr_eur == APPROX(2850.0, abs=0.01)

    def test_value_of_targeting_eur(self):
        # 4350 − 2850 = 1500
        assert self.r.value_of_targeting_eur == APPROX(1500.0, abs=0.01)

    def test_value_of_targeting_pct(self):
        # 1500 / 2850 × 100 = 52.63%
        assert self.r.value_of_targeting_pct == APPROX(1500.0 / 2850.0 * 100, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Budget = €10 000 (far more than needed for all 200 contacts = €400)
# ──────────────────────────────────────────────────────────────────────────────
# Greedy:
#   T1: 100 contacts (fully used), cost=200
#   T2: 100 contacts (fully used), cost=200
#   remaining=9600 → no more contacts available
#
# Totals:
#   used=400, unused=9600, contacts=200, profit=7600
#
# Opportunity cost: 7600−7600=0 (already at full capacity)
#
# Naïve: floor(10000/2)=5000, capped at 200 (total available) → 200 contacts
#   e_resp=200×0.40=80.0, profit=80×100−400=7600
#
# Value of targeting: 7600−7600=0
#   (targeting adds nothing when you'd contact everyone regardless)
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetExceedsCapacity:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = allocate(10_000.00, [M1, M2], A2, naive_base_rate=BASE_RATE)

    def test_t1_fully_allocated(self):
        assert self.r.allocations[0].contacts_allocated == 100

    def test_t2_fully_allocated(self):
        assert self.r.allocations[1].contacts_allocated == 100

    def test_budget_used(self):
        # 200 contacts × €2.00 = €400
        assert self.r.budget_used_eur == APPROX(400.0, abs=0.01)

    def test_budget_unused(self):
        assert self.r.budget_unused_eur == APPROX(9_600.0, abs=0.01)

    def test_total_profit(self):
        assert self.r.total_gross_profit_1yr_eur == APPROX(7600.0, abs=0.01)

    def test_opportunity_cost_zero(self):
        assert self.r.opportunity_cost_eur == APPROX(0.0, abs=0.01)

    def test_naive_contacts_capped(self):
        # floor(10000/2) = 5000, but only 200 available
        assert self.r.naive_contacts == 200

    def test_value_of_targeting_zero(self):
        # Both targeted and naïve contact all 200 people → same profit
        assert self.r.value_of_targeting_eur == APPROX(0.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Budget = €0
# ──────────────────────────────────────────────────────────────────────────────
# No contacts made in any tier. All outputs are zero.
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetZero:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = allocate(0.0, [M1, M2], A2, naive_base_rate=BASE_RATE)

    def test_all_allocations_zero(self):
        for a in self.r.allocations:
            assert a.contacts_allocated == 0

    def test_total_contacts_zero(self):
        assert self.r.total_contacts == 0

    def test_budget_used_zero(self):
        assert self.r.budget_used_eur == APPROX(0.0, abs=0.01)

    def test_budget_unused_zero(self):
        assert self.r.budget_unused_eur == APPROX(0.0, abs=0.01)

    def test_total_profit_zero(self):
        assert self.r.total_gross_profit_1yr_eur == APPROX(0.0, abs=0.01)

    def test_opportunity_cost_equals_full_capacity(self):
        # All 7600 in profit foregone
        assert self.r.opportunity_cost_eur == APPROX(FULL_CAP_PROFIT, abs=0.01)

    def test_naive_contacts_zero(self):
        assert self.r.naive_contacts == 0

    def test_value_of_targeting_zero_budget(self):
        # Both targeted and naïve make zero contacts → vot = 0
        assert self.r.value_of_targeting_eur == APPROX(0.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Budget = €200 (exactly T1 capacity — T2 gets nothing)
# ──────────────────────────────────────────────────────────────────────────────
# T1: 100 contacts, cost=200, remaining=0
# T2: 0 contacts
# profit = 5800, roi = 5800/200 = 29.0
#
# Naïve: floor(200/2)=100 contacts at 0.40 → e_resp=40, profit=4000−200=3800
# Value of targeting: 5800−3800=2000, pct=2000/3800×100=52.63%
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetExactlyT1:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = allocate(200.0, [M1, M2], A2, naive_base_rate=BASE_RATE)

    def test_t1_fully_allocated(self):
        assert self.r.allocations[0].contacts_allocated == 100

    def test_t2_zero(self):
        assert self.r.allocations[1].contacts_allocated == 0

    def test_total_profit(self):
        assert self.r.total_gross_profit_1yr_eur == APPROX(5800.0, abs=0.01)

    def test_roi(self):
        assert self.r.total_roi_1yr == APPROX(29.0, abs=0.01)

    def test_opportunity_cost(self):
        # T2 contribution foregone: 1800
        assert self.r.opportunity_cost_eur == APPROX(1800.0, abs=0.01)

    def test_naive_profit(self):
        # 100 × 0.40 × 100 − 200 = 4000 − 200 = 3800
        assert self.r.naive_gross_profit_1yr_eur == APPROX(3800.0, abs=0.01)

    def test_value_of_targeting(self):
        # 5800 − 3800 = 2000
        assert self.r.value_of_targeting_eur == APPROX(2000.0, abs=0.01)

    def test_value_of_targeting_pct(self):
        # 2000 / 3800 × 100 = 52.63%
        assert self.r.value_of_targeting_pct == APPROX(2000.0 / 3800.0 * 100, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Greedy order invariant — T1 must be filled before T2
# ──────────────────────────────────────────────────════════════════════════════
# Budget = €250 (125 contacts, T1 has 100 → 25 spill into T2)
#   T1: 100 contacts, cost=200, remaining=50
#   T2: 25 contacts, cost=50, remaining=0
# ══════════════════════════════════════════════════════════════════════════════

class TestGreedyOrderPreservation:
    def test_t1_saturated_before_t2_starts(self):
        r = allocate(250.0, [M1, M2], A2, naive_base_rate=BASE_RATE)
        assert r.allocations[0].contacts_allocated == 100   # T1 full
        assert r.allocations[1].contacts_allocated == 25    # T2 gets spill

    def test_t2_higher_mppc_than_t1_still_follows_input_order(self):
        # If caller passes them swapped, allocation respects caller's order.
        # This tests that allocate() is position-driven, not MPPC-sorting.
        r = allocate(250.0, [M2, M1], A2, naive_base_rate=BASE_RATE)
        # M2 is first in input → M2 gets saturated first
        assert r.allocations[0].contacts_allocated == 100   # M2 full
        assert r.allocations[1].contacts_allocated == 25    # M1 gets spill


# ══════════════════════════════════════════════════════════════════════════════
# Edge: budget not divisible by cost_per_contact
# ──────────────────────────────────────────────────────────────────────────────
# Budget = €201 (cost=2.00 → floor(201/2)=100 contacts)
# T1: min(100, 100) = 100, remaining=1.00
# T2: floor(1.00/2.00)=0 contacts
# ══════════════════════════════════════════════════════════════════════════════

class TestOddBudget:
    def test_fractional_budget_handled(self):
        r = allocate(201.0, [M1, M2], A2, naive_base_rate=BASE_RATE)
        assert r.allocations[0].contacts_allocated == 100
        assert r.allocations[1].contacts_allocated == 0
        assert r.budget_used_eur == APPROX(200.0, abs=0.01)
        assert r.budget_unused_eur == APPROX(1.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Single tertile edge case
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleTertile:
    def test_single_tertile_allocates_correctly(self):
        r = allocate(150.0, [M1], A2, naive_base_rate=BASE_RATE)
        assert r.allocations[0].contacts_allocated == 75
        # profit = 75 × 0.60 × 100 − 150 = 4500 − 150 = 4350
        assert r.total_gross_profit_1yr_eur == APPROX(4350.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# Input validation
# ══════════════════════════════════════════════════════════════════════════════

class TestInputValidation:
    def test_negative_budget_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            allocate(-1.0, [M1, M2], A2)


# ══════════════════════════════════════════════════════════════════════════════
# FULCRUM integration smoke test — confirm the live model numbers are consistent
# ──────────────────────────────────────────────────────────────────────────────
# Uses the FULCRUM actuals from notebooks/03_decile_analysis.ipynb:
#   T1: 2059 contacts, 949 resp, ci=[0.439, 0.482]  MPPC≈66.64
#   T2: 2059 contacts, 865 resp, ci=[0.398, 0.441]  MPPC≈60.52
#   T3: 2059 contacts, 562 resp, ci=[0.254, 0.293]  MPPC≈38.44
#   cost=2.50, balance=10_000, NIM=0.015, tenor=1.0, retention=0.50
#   base_rate=0.384
#
# Budget = €10,295 (enough for T1+T2 = 4118 contacts = €10,295)
#
# T1: 2059 contacts (all), cost=5148, e_resp=949, e_profit≈137,202
# T2: (10295−5148)/2.50 = floor(5147/2.50) = floor(2058.8)=2058 contacts
#     wait: 10295 = 4118×2.50 = 10295 exactly
#     so T1: 2059, remaining = 10295-5147.5=5147.5, floor(5147.5/2.50)=2059
#     T2: 2059 contacts (all), remaining=0
# T3: 0
#
# Verified: targeted budget = T1+T2 is exactly €10,295 = 4118×2.50
# ══════════════════════════════════════════════════════════════════════════════

from pnl.engine import TertileInput, compute_tertile_metrics

FULCRUM_A = Assumptions(
    cost_per_contact_eur=2.50,
    avg_deposit_balance_eur=10_000,
    net_interest_margin=0.015,
    deposit_tenor_yrs=1.0,
    retention_rate=0.50,
)

FM1 = compute_tertile_metrics(
    TertileInput("T1 — High",   contacts=2059, responders=949, ci_lo=0.439, ci_hi=0.482),
    FULCRUM_A,
)
FM2 = compute_tertile_metrics(
    TertileInput("T2 — Medium", contacts=2059, responders=865, ci_lo=0.398, ci_hi=0.441),
    FULCRUM_A,
)
FM3 = compute_tertile_metrics(
    TertileInput("T3 — Low",    contacts=2059, responders=562, ci_lo=0.254, ci_hi=0.293),
    FULCRUM_A,
)


class TestFulcrumIntegration:
    def test_t1_t2_budget_fills_exactly(self):
        # Budget = T1+T2 cost: 4118 × 2.50 = 10295
        budget = (FM1.contacts + FM2.contacts) * FULCRUM_A.cost_per_contact_eur
        r = allocate(budget, [FM1, FM2, FM3], FULCRUM_A, naive_base_rate=0.384)
        assert r.allocations[0].contacts_allocated == 2059
        assert r.allocations[1].contacts_allocated == 2059
        assert r.allocations[2].contacts_allocated == 0
        assert r.budget_unused_eur == APPROX(0.0, abs=0.01)

    def test_value_of_targeting_is_positive(self):
        budget = (FM1.contacts + FM2.contacts) * FULCRUM_A.cost_per_contact_eur
        r = allocate(budget, [FM1, FM2, FM3], FULCRUM_A, naive_base_rate=0.384)
        # T1+T2 have response rates 46.1% and 42.0% — both > 38.4% base
        # Targeting must add positive value
        assert r.value_of_targeting_eur > 0

    def test_opportunity_cost_is_t3_profit(self):
        # Stopping at T1+T2 forgoes T3's profit
        budget = (FM1.contacts + FM2.contacts) * FULCRUM_A.cost_per_contact_eur
        r = allocate(budget, [FM1, FM2, FM3], FULCRUM_A, naive_base_rate=0.384)
        assert r.opportunity_cost_eur == APPROX(FM3.gross_profit_1yr_eur, abs=0.01)

    def test_unlimited_budget_zero_vot(self):
        r = allocate(1_000_000.0, [FM1, FM2, FM3], FULCRUM_A, naive_base_rate=0.384)
        assert r.allocations[0].contacts_allocated == 2059
        assert r.allocations[1].contacts_allocated == 2059
        assert r.allocations[2].contacts_allocated == 2059
        assert r.opportunity_cost_eur == APPROX(0.0, abs=0.01)

        # When all contacts are made, VoT reduces to the difference between the
        # targeted blended response rate and naive_base_rate, scaled by contacts
        # and revenue. VoT is exactly zero only when naive_base_rate equals the
        # actual blended rate. Here 38.4% is a rounded figure; the exact blended
        # rate is (949+865+562) / (3×2059) = 2376/6177 ≈ 38.46%.
        # Test with the exact blended rate → VoT must be zero.
        total_resp = FM1.responders + FM2.responders + FM3.responders
        total_n    = FM1.contacts  + FM2.contacts  + FM3.contacts
        blended    = total_resp / total_n
        r_exact = allocate(1_000_000.0, [FM1, FM2, FM3], FULCRUM_A,
                           naive_base_rate=blended)
        assert r_exact.value_of_targeting_eur == APPROX(0.0, abs=0.01)

    def test_roi_decreases_as_budget_grows(self):
        # Adding T3 (lower MPPC) must reduce blended ROI
        b_t1t2 = (FM1.contacts + FM2.contacts) * FULCRUM_A.cost_per_contact_eur
        b_all  = b_t1t2 + FM3.contacts * FULCRUM_A.cost_per_contact_eur
        r_t1t2 = allocate(b_t1t2, [FM1, FM2, FM3], FULCRUM_A, naive_base_rate=0.384)
        r_all  = allocate(b_all,  [FM1, FM2, FM3], FULCRUM_A, naive_base_rate=0.384)
        assert r_all.total_roi_1yr < r_t1t2.total_roi_1yr
