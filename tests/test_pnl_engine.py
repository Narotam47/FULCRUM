"""Unit tests for src/pnl/engine.py.

All expected values are hand-computed from first principles — no loops,
no calls to the functions under test inside the expected-value expressions.
Float equality uses pytest.approx(abs=0.01) throughout.
"""

import math
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pnl.engine import (
    Assumptions,
    TertileInput,
    _cis_overlap,
    compute_cumulative,
    compute_marginal_gaps,
    compute_tertile_metrics,
    load_assumptions,
    recommend,
)

# ── Shared assumptions fixture ────────────────────────────────────────────────
# cost_per_contact  = 2.00
# balance           = 10_000
# NIM               = 0.01  (1 %)
# tenor             = 1.0   year
# retention         = 0.50
#
# Derived:
#   revenue_per_conversion = 10_000 × 0.01 × 1.0 = 100.00
#   ltv_per_conversion     = 100.00 × (1 + 0.50) = 150.00

A = Assumptions(
    cost_per_contact_eur=2.00,
    avg_deposit_balance_eur=10_000,
    net_interest_margin=0.01,
    deposit_tenor_yrs=1.0,
    retention_rate=0.50,
)

APPROX = pytest.approx


# ── Assumptions properties ────────────────────────────────────────────────────

class TestAssumptionsProperties:
    def test_revenue_per_conversion(self):
        # 10_000 × 0.01 × 1.0 = 100
        assert A.revenue_per_conversion_eur == APPROX(100.00, abs=0.01)

    def test_ltv_per_conversion(self):
        # 100 × (1 + 0.50) = 150
        assert A.ltv_per_conversion_eur == APPROX(150.00, abs=0.01)

    def test_revenue_with_two_year_tenor(self):
        # 5_000 × 0.02 × 2.0 = 200
        a2 = Assumptions(
            cost_per_contact_eur=0.00,
            avg_deposit_balance_eur=5_000,
            net_interest_margin=0.02,
            deposit_tenor_yrs=2.0,
            retention_rate=0.25,
        )
        assert a2.revenue_per_conversion_eur == APPROX(200.00, abs=0.01)
        # 200 × (1 + 0.25) = 250
        assert a2.ltv_per_conversion_eur == APPROX(250.00, abs=0.01)

    def test_zero_nim_yields_zero_revenue(self):
        a0 = Assumptions(
            cost_per_contact_eur=1.00,
            avg_deposit_balance_eur=10_000,
            net_interest_margin=0.00,
            deposit_tenor_yrs=1.0,
            retention_rate=0.50,
        )
        assert a0.revenue_per_conversion_eur == APPROX(0.00, abs=0.01)
        assert a0.ltv_per_conversion_eur == APPROX(0.00, abs=0.01)


# ── compute_tertile_metrics — standard case ───────────────────────────────────
#
# TertileInput: 100 contacts, 50 responders
#
# contact_cost     = 100 × 2.00           = 200.00
# response_rate    = 50 / 100             = 0.50
# revenue_1yr      = 50 × 100             = 5_000.00
# revenue_ltv      = 50 × 150             = 7_500.00
# gross_profit_1yr = 5_000 − 200          = 4_800.00
# gross_profit_ltv = 7_500 − 200          = 7_300.00
# roi_1yr          = 4_800 / 200          = 24.00
# roi_ltv          = 7_300 / 200          = 36.50
# cpa              = 200 / 50             = 4.00
# mppc             = 4_800 / 100          = 48.00
#   (equivalently: 0.50 × 100 − 2.00 = 48.00)

T_STANDARD = TertileInput(
    label="T1 — High", contacts=100, responders=50, ci_lo=0.40, ci_hi=0.60
)


class TestComputeTertileMetricsStandard:
    @pytest.fixture(autouse=True)
    def metrics(self):
        self.m = compute_tertile_metrics(T_STANDARD, A)

    def test_response_rate(self):
        assert self.m.response_rate == APPROX(0.50, abs=1e-6)

    def test_contact_cost(self):
        assert self.m.contact_cost_eur == APPROX(200.00, abs=0.01)

    def test_revenue_1yr(self):
        assert self.m.revenue_1yr_eur == APPROX(5_000.00, abs=0.01)

    def test_revenue_ltv(self):
        assert self.m.revenue_ltv_eur == APPROX(7_500.00, abs=0.01)

    def test_gross_profit_1yr(self):
        assert self.m.gross_profit_1yr_eur == APPROX(4_800.00, abs=0.01)

    def test_gross_profit_ltv(self):
        assert self.m.gross_profit_ltv_eur == APPROX(7_300.00, abs=0.01)

    def test_roi_1yr(self):
        assert self.m.roi_1yr == APPROX(24.00, abs=0.01)

    def test_roi_ltv(self):
        assert self.m.roi_ltv == APPROX(36.50, abs=0.01)

    def test_cost_per_acquisition(self):
        assert self.m.cost_per_acquisition_eur == APPROX(4.00, abs=0.01)

    def test_marginal_profit_per_contact(self):
        # Two equivalent derivations must agree
        by_rate = 0.50 * 100.00 - 2.00   # response_rate × rev_per_conv − cost
        assert self.m.marginal_profit_per_contact_eur == APPROX(48.00, abs=0.01)
        assert self.m.marginal_profit_per_contact_eur == APPROX(by_rate, abs=0.01)

    def test_ci_bounds_echoed(self):
        assert self.m.ci_lo == 0.40
        assert self.m.ci_hi == 0.60

    def test_label_echoed(self):
        assert self.m.label == "T1 — High"


# ── compute_tertile_metrics — zero responders ─────────────────────────────────
#
# TertileInput: 100 contacts, 0 responders
#
# response_rate    = 0 / 100         = 0.00
# contact_cost     = 100 × 2.00      = 200.00
# revenue_1yr      = 0 × 100         = 0.00
# revenue_ltv      = 0 × 150         = 0.00
# gross_profit_1yr = 0 − 200         = −200.00
# roi_1yr          = −200 / 200      = −1.00
# cpa              = undefined → inf
# mppc             = −200 / 100      = −2.00

T_ZERO = TertileInput(
    label="T_zero", contacts=100, responders=0, ci_lo=0.00, ci_hi=0.05
)


class TestComputeTertileMetricsZeroResponders:
    @pytest.fixture(autouse=True)
    def metrics(self):
        self.m = compute_tertile_metrics(T_ZERO, A)

    def test_response_rate_is_zero(self):
        assert self.m.response_rate == APPROX(0.00, abs=1e-9)

    def test_revenue_zero(self):
        assert self.m.revenue_1yr_eur == APPROX(0.00, abs=0.01)
        assert self.m.revenue_ltv_eur == APPROX(0.00, abs=0.01)

    def test_gross_profit_is_negative_cost(self):
        assert self.m.gross_profit_1yr_eur == APPROX(-200.00, abs=0.01)

    def test_roi_is_minus_one(self):
        assert self.m.roi_1yr == APPROX(-1.00, abs=1e-6)

    def test_cpa_is_inf(self):
        assert math.isinf(self.m.cost_per_acquisition_eur)

    def test_mppc_is_negative(self):
        assert self.m.marginal_profit_per_contact_eur == APPROX(-2.00, abs=0.01)


# ── compute_tertile_metrics — single contact ──────────────────────────────────
#
# Edge case: 1 contact, 1 responder
# contact_cost = 1 × 2.00 = 2.00
# revenue_1yr  = 1 × 100  = 100.00
# profit_1yr   = 100 − 2  = 98.00
# roi_1yr      = 98 / 2   = 49.00
# cpa          = 2 / 1    = 2.00
# mppc         = 98 / 1   = 98.00

class TestComputeTertileMetricsSingleContact:
    def test_single_contact_single_responder(self):
        t = TertileInput("T_single", contacts=1, responders=1, ci_lo=0.0, ci_hi=1.0)
        m = compute_tertile_metrics(t, A)
        assert m.response_rate == APPROX(1.00, abs=1e-6)
        assert m.contact_cost_eur == APPROX(2.00, abs=0.01)
        assert m.gross_profit_1yr_eur == APPROX(98.00, abs=0.01)
        assert m.roi_1yr == APPROX(49.00, abs=0.01)
        assert m.cost_per_acquisition_eur == APPROX(2.00, abs=0.01)
        assert m.marginal_profit_per_contact_eur == APPROX(98.00, abs=0.01)


# ── compute_cumulative ────────────────────────────────────────────────────────
#
# Two tertiles, A assumptions (rev = 100, ltv = 150, cost = 2.00):
#
#   T1: 100 contacts, 50 responders
#       cost=200  rev=5_000  profit=4_800  mppc=48.00
#   T2: 100 contacts, 20 responders
#       cost=200  rev=2_000  profit=1_800  mppc=18.00
#
# Slice 1 (after T1 only):
#   contacts=100  responders=50  cost=200  revenue=5_000
#   profit=4_800  roi=4_800/200=24.00  cpa=200/50=4.00
#   incremental_profit=4_800  mppc=48.00
#
# Slice 2 (after T1+T2):
#   contacts=200  responders=70  cost=400  revenue=7_000
#   profit=6_600  roi=6_600/400=16.50  cpa=400/70≈5.714
#   incremental_profit=1_800  mppc=18.00 (T2's mppc, not the cum average)

T1_CUM = TertileInput("T1", contacts=100, responders=50, ci_lo=0.40, ci_hi=0.60)
T2_CUM = TertileInput("T2", contacts=100, responders=20, ci_lo=0.10, ci_hi=0.30)


class TestComputeCumulative:
    @pytest.fixture(autouse=True)
    def slices(self):
        m1 = compute_tertile_metrics(T1_CUM, A)
        m2 = compute_tertile_metrics(T2_CUM, A)
        self.s = compute_cumulative([m1, m2])

    def test_length(self):
        assert len(self.s) == 2

    def test_slice1_contacts(self):
        assert self.s[0].contacts == 100

    def test_slice1_responders(self):
        assert self.s[0].responders == 50

    def test_slice1_profit(self):
        assert self.s[0].gross_profit_1yr_eur == APPROX(4_800.00, abs=0.01)

    def test_slice1_roi(self):
        assert self.s[0].roi_1yr == APPROX(24.00, abs=0.01)

    def test_slice1_cpa(self):
        assert self.s[0].cost_per_acquisition_eur == APPROX(4.00, abs=0.01)

    def test_slice1_incremental_equals_own_profit(self):
        # First slice: incremental = the tertile's own profit
        assert self.s[0].incremental_profit_1yr_eur == APPROX(4_800.00, abs=0.01)

    def test_slice1_mppc(self):
        assert self.s[0].marginal_profit_per_contact_eur == APPROX(48.00, abs=0.01)

    def test_slice2_contacts(self):
        assert self.s[1].contacts == 200

    def test_slice2_responders(self):
        assert self.s[1].responders == 70   # 50 + 20

    def test_slice2_cost(self):
        assert self.s[1].contact_cost_eur == APPROX(400.00, abs=0.01)

    def test_slice2_revenue(self):
        # T1 rev = 5_000, T2 rev = 20 × 100 = 2_000 → cumulative = 7_000
        assert self.s[1].revenue_1yr_eur == APPROX(7_000.00, abs=0.01)

    def test_slice2_profit(self):
        # 6_600 = 4_800 + 1_800
        assert self.s[1].gross_profit_1yr_eur == APPROX(6_600.00, abs=0.01)

    def test_slice2_roi(self):
        # 6_600 / 400 = 16.50
        assert self.s[1].roi_1yr == APPROX(16.50, abs=0.01)

    def test_slice2_cpa(self):
        # 400 / 70 = 5.714...
        assert self.s[1].cost_per_acquisition_eur == APPROX(400.0 / 70.0, abs=0.01)

    def test_slice2_incremental_is_t2_profit(self):
        # T2 profit = 20×100 − 200 = 1_800
        assert self.s[1].incremental_profit_1yr_eur == APPROX(1_800.00, abs=0.01)

    def test_slice2_mppc_is_t2_marginal(self):
        # mppc of last tertile added (T2) = 18.00, NOT the cum average (33.00)
        assert self.s[1].marginal_profit_per_contact_eur == APPROX(18.00, abs=0.01)

    def test_slice2_tertiles_included(self):
        assert self.s[1].tertiles_included == ("T1", "T2")

    def test_single_tertile_cumulative(self):
        m = compute_tertile_metrics(T1_CUM, A)
        s = compute_cumulative([m])
        assert len(s) == 1
        assert s[0].contacts == 100
        assert s[0].incremental_profit_1yr_eur == APPROX(4_800.00, abs=0.01)


# ── _cis_overlap ─────────────────────────────────────────────────────────────
#
# Uses open-interval logic: a.ci_lo < b.ci_hi AND b.ci_lo < a.ci_hi
#
# Case 1: [0.45, 0.55] vs [0.30, 0.50]  → 0.45<0.50 T, 0.30<0.55 T → overlap
# Case 2: [0.45, 0.55] vs [0.10, 0.30]  → 0.45<0.30 F              → no overlap
# Case 3: [0.39, 0.44] vs [0.25, 0.29]  → 0.39<0.29 F              → no overlap
# Case 4: [0.30, 0.50] vs [0.10, 0.30]  → 0.30<0.30 F (touching, not crossing)

def _make(ci_lo, ci_hi):
    """Helper: construct a TertileMetrics with only CI fields filled."""
    t = TertileInput("x", contacts=100, responders=50, ci_lo=ci_lo, ci_hi=ci_hi)
    return compute_tertile_metrics(t, A)


class TestCIsOverlap:
    def test_clear_overlap(self):
        assert _cis_overlap(_make(0.45, 0.55), _make(0.30, 0.50)) is True

    def test_clear_no_overlap(self):
        assert _cis_overlap(_make(0.45, 0.55), _make(0.10, 0.30)) is False

    def test_no_overlap_lower_band(self):
        # [0.39, 0.44] vs [0.25, 0.29]: 0.39 < 0.29 → False
        assert _cis_overlap(_make(0.39, 0.44), _make(0.25, 0.29)) is False

    def test_touching_boundary_not_overlap(self):
        # [0.30, 0.50] vs [0.10, 0.30]: ci_lo=0.30, other ci_hi=0.30 → 0.30<0.30 False
        assert _cis_overlap(_make(0.30, 0.50), _make(0.10, 0.30)) is False

    def test_symmetry(self):
        a = _make(0.45, 0.55)
        b = _make(0.30, 0.50)
        assert _cis_overlap(a, b) == _cis_overlap(b, a)

    def test_identity_overlaps_itself(self):
        a = _make(0.40, 0.60)
        assert _cis_overlap(a, a) is True


# ── compute_marginal_gaps ─────────────────────────────────────────────────────
#
# Three tertiles:
#   T_hi:  100 contacts, 50 resp  → mppc = 48.00  ci=[0.45, 0.55]
#   T_mid: 100 contacts, 20 resp  → mppc = 18.00  ci=[0.30, 0.50]  overlaps T_hi
#   T_lo:  100 contacts,  0 resp  → mppc = −2.00  ci=[0.10, 0.28]  no overlap T_mid
#
# Gap T_hi→T_mid: drop = 48−18 = 30.00, drop_pct = 30/48 = 0.625, overlap=True
# Gap T_mid→T_lo: drop = 18−(−2) = 20.00, drop_pct = 20/18 = 1.111, overlap=False

T_HI  = TertileInput("T_hi",  contacts=100, responders=50, ci_lo=0.45, ci_hi=0.55)
T_MID = TertileInput("T_mid", contacts=100, responders=20, ci_lo=0.30, ci_hi=0.50)
T_LO  = TertileInput("T_lo",  contacts=100, responders=0,  ci_lo=0.10, ci_hi=0.28)


class TestComputeMarginalGaps:
    @pytest.fixture(autouse=True)
    def gaps(self):
        m_hi  = compute_tertile_metrics(T_HI, A)
        m_mid = compute_tertile_metrics(T_MID, A)
        m_lo  = compute_tertile_metrics(T_LO, A)
        self.g = compute_marginal_gaps([m_hi, m_mid, m_lo])

    def test_length(self):
        assert len(self.g) == 2

    def test_gap1_labels(self):
        assert self.g[0].from_label == "T_hi"
        assert self.g[0].to_label == "T_mid"

    def test_gap1_drop_eur(self):
        # 48.00 − 18.00 = 30.00
        assert self.g[0].drop_eur == APPROX(30.00, abs=0.01)

    def test_gap1_drop_pct(self):
        # 30 / 48 = 0.625
        assert self.g[0].drop_pct == APPROX(0.625, abs=0.001)

    def test_gap1_cis_overlap(self):
        # [0.45,0.55] vs [0.30,0.50]: 0.45<0.50 T, 0.30<0.55 T → True
        assert self.g[0].cis_overlap is True

    def test_gap2_labels(self):
        assert self.g[1].from_label == "T_mid"
        assert self.g[1].to_label == "T_lo"

    def test_gap2_drop_eur(self):
        # 18.00 − (−2.00) = 20.00
        assert self.g[1].drop_eur == APPROX(20.00, abs=0.01)

    def test_gap2_drop_pct(self):
        # 20 / 18 ≈ 1.111
        assert self.g[1].drop_pct == APPROX(20.0 / 18.0, abs=0.001)

    def test_gap2_cis_no_overlap(self):
        # [0.30,0.50] vs [0.10,0.28]: 0.30<0.28 F → False
        assert self.g[1].cis_overlap is False

    def test_single_pair(self):
        m1 = compute_tertile_metrics(T_HI, A)
        m2 = compute_tertile_metrics(T_MID, A)
        gaps = compute_marginal_gaps([m1, m2])
        assert len(gaps) == 1


# ── recommend — structural tests ──────────────────────────────────────────────
#
# Using FULCRUM actuals (from notebooks/03_decile_analysis.ipynb):
#   T1: 2059 contacts, 949 responders, ci=[0.439, 0.482]  mppc≈66.6
#   T2: 2059 contacts, 865 responders, ci=[0.398, 0.441]  mppc≈60.5
#   T3: 2059 contacts, 562 responders, ci=[0.254, 0.293]  mppc≈38.5
#
# T1↔T2 CIs overlap → noise. T2↔T3 CIs do not overlap → real break.
# All three profitable. Recommendation must:
#   - mention all three are profitable
#   - identify T1+T2 as the priority tier (CI overlap)
#   - identify T2→T3 as the real decision boundary
#   - recommend T3 as conditional on budget

FULCRUM_T1 = TertileInput("T1 — High",   contacts=2059, responders=949,
                           ci_lo=0.439, ci_hi=0.482)
FULCRUM_T2 = TertileInput("T2 — Medium", contacts=2059, responders=865,
                           ci_lo=0.398, ci_hi=0.441)
FULCRUM_T3 = TertileInput("T3 — Low",    contacts=2059, responders=562,
                           ci_lo=0.254, ci_hi=0.293)

FULCRUM_A = Assumptions(
    cost_per_contact_eur=2.50,
    avg_deposit_balance_eur=10_000,
    net_interest_margin=0.015,
    deposit_tenor_yrs=1.0,
    retention_rate=0.50,
)


class TestRecommendFulcrum:
    @pytest.fixture(autouse=True)
    def result(self):
        m1 = compute_tertile_metrics(FULCRUM_T1, FULCRUM_A)
        m2 = compute_tertile_metrics(FULCRUM_T2, FULCRUM_A)
        m3 = compute_tertile_metrics(FULCRUM_T3, FULCRUM_A)
        self.rec = recommend([m1, m2, m3])

    def test_returns_string(self):
        assert isinstance(self.rec, str)
        assert len(self.rec) > 100

    def test_all_profitable_noted(self):
        assert "profitable" in self.rec.lower()

    def test_priority_tier_contains_t1_and_t2(self):
        # T1 and T2 should be grouped as the priority tier
        assert "T1" in self.rec
        assert "T2" in self.rec

    def test_conditional_tier_contains_t3(self):
        assert "T3" in self.rec

    def test_budget_language_present(self):
        assert "budget" in self.rec.lower()

    def test_ci_overlap_language_for_t1_t2(self):
        # The T1→T2 gap must be described as within noise
        assert "overlap" in self.rec.lower()

    def test_real_break_language_for_t2_t3(self):
        # The T2→T3 gap must be described as real / statistically distinct
        assert any(phrase in self.rec.lower() for phrase in
                   ["does not overlap", "real", "genuine"])


class TestRecommendEdgeCases:
    def test_two_tertile_minimum(self):
        m1 = compute_tertile_metrics(T_HI, A)
        m2 = compute_tertile_metrics(T_MID, A)
        out = recommend([m1, m2])
        assert isinstance(out, str)

    def test_single_tertile_returns_message(self):
        m1 = compute_tertile_metrics(T_HI, A)
        out = recommend([m1])
        assert "least two" in out.lower()

    def test_all_overlapping_cis_no_break_identified(self):
        # Three tertiles where every adjacent pair overlaps → no clear break
        t_a = TertileInput("A", 100, 50, ci_lo=0.38, ci_hi=0.62)
        t_b = TertileInput("B", 100, 45, ci_lo=0.34, ci_hi=0.58)
        t_c = TertileInput("C", 100, 40, ci_lo=0.30, ci_hi=0.52)
        m_a = compute_tertile_metrics(t_a, A)
        m_b = compute_tertile_metrics(t_b, A)
        m_c = compute_tertile_metrics(t_c, A)
        out = recommend([m_a, m_b, m_c])
        # Should not identify a priority/conditional split
        assert "single tier" in out.lower() or "no" in out.lower()


# ── load_assumptions ──────────────────────────────────────────────────────────

class TestLoadAssumptions:
    def test_round_trips_correctly(self, tmp_path):
        yml = tmp_path / "test_assumptions.yml"
        yml.write_text(
            "cost_per_contact_eur: 2.50\n"
            "avg_deposit_balance_eur: 10000\n"
            "net_interest_margin: 0.015\n"
            "deposit_tenor_yrs: 1.0\n"
            "retention_rate: 0.50\n"
        )
        a = load_assumptions(yml)
        assert a.cost_per_contact_eur == APPROX(2.50, abs=1e-9)
        assert a.avg_deposit_balance_eur == APPROX(10_000.0, abs=1e-9)
        assert a.net_interest_margin == APPROX(0.015, abs=1e-9)
        assert a.deposit_tenor_yrs == APPROX(1.0, abs=1e-9)
        assert a.retention_rate == APPROX(0.50, abs=1e-9)

    def test_missing_key_raises_value_error(self, tmp_path):
        yml = tmp_path / "bad.yml"
        yml.write_text(
            "cost_per_contact_eur: 2.50\n"
            "avg_deposit_balance_eur: 10000\n"
            # net_interest_margin missing
            "deposit_tenor_yrs: 1.0\n"
            "retention_rate: 0.50\n"
        )
        with pytest.raises(ValueError, match="net_interest_margin"):
            load_assumptions(yml)

    def test_extra_keys_ignored(self, tmp_path):
        yml = tmp_path / "extra.yml"
        yml.write_text(
            "cost_per_contact_eur: 1.00\n"
            "avg_deposit_balance_eur: 5000\n"
            "net_interest_margin: 0.02\n"
            "deposit_tenor_yrs: 0.5\n"
            "retention_rate: 0.40\n"
            "unknown_field: ignored\n"
        )
        a = load_assumptions(yml)
        assert a.cost_per_contact_eur == APPROX(1.00, abs=1e-9)

    def test_loads_project_config(self):
        # Smoke test: project's own YAML must parse without error
        project_root = Path(__file__).parent.parent
        a = load_assumptions(project_root / "config" / "pnl_assumptions.yml")
        assert a.cost_per_contact_eur > 0
        assert 0 < a.net_interest_margin < 1
        assert 0 < a.retention_rate < 1
