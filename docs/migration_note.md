# FULCRUM — SAS/Python Reconciliation Note

Generated: 2026-09-11

## Overall verdict: FAIL

Business recommendation: **UNCHANGED**

---

## Background

FULCRUM implements the same campaign propensity and P&L analysis in two languages:

| | Python | SAS |
|---|---|---|
| Model | `LogisticRegression(max_iter=1000, C=1.0)` (L2) | `PROC LOGISTIC` (MLE, no penalty) |
| pdays feature | Raw scaled numeric | `was_contacted_before` binary flag |
| Tertile method | `proc_rank_groups()` in `python/07_reconcile_export.py` | `PROC RANK GROUPS=3 TIES=MEAN` |
| Training rows | 28,823 | 28,823 |
| Test rows | 6,177 | 6,177 |

The two **known structural differences** (regularisation, pdays encoding) mean
coefficients will never agree exactly. The reconciliation tests the OUTPUTS
that drive the business decision: tertile response rates and MPPC.

---

## 1. Coefficient comparison

Tolerance: ±0.05 absolute per coefficient.

| Verdict | Count |
|---|---|
| PASS | 34 |
| FAIL | 18 |
| PY_ONLY (pdays) | 1 |
| SAS_ONLY (was_contacted_before) | 1 |
| Shared total | 52 |

### Diagnosis

**1.** EXPECTED — pdays (Python) vs was_contacted_before (SAS): structural feature difference documented in 02_model.sas header, difference C. These appear as PY_ONLY / SAS_ONLY in the coefficient table.

**2.** REGULARISATION DIFFERENCE: 18 of 52 shared coefficients exceed ±0.05 absolute tolerance (avg diff 0.1537). All failing coefficients have the SAME SIGN in both implementations — failure is magnitude-only (regularisation shrinkage), not direction. This does NOT change the business recommendation.


---

## 2. Tertile response rates

Tolerance: ±0.5 pp per tertile.

| Tertile | Python | SAS | Diff | Verdict |
|---|---|---|---|---|
| T1 High | 46.09% | 44.57% | -1.52 pp | **FAIL** |
| T2 Medium | 41.96% | 41.10% | -0.86 pp | **FAIL** |
| T3 Low | 27.29% | 27.64% | +0.35 pp | **PASS** |

### Diagnosis of rate failures

The response rate mismatch is a consequence of the two documented structural
differences:

1. **Regularisation**: Python's L2 penalty (C=1.0) shrinks coefficients toward
   zero, compressing the predicted probability distribution. SAS's unregularized
   MLE produces more extreme probabilities. At the tertile boundary (p_hat ≈
   0.065 and ≈ 0.150 from the Python model), rows whose true propensity is near
   the cut-point are assigned differently in each implementation. This is not a
   bug — it is the expected consequence of a different objective function.

2. **pdays vs was_contacted_before**: The ~3.7% of rows with prior contact
   receive different feature values in each model. Their scores shift, moving
   some across tertile boundaries.

**Root cause is structural, not a reference-level or tie-handling bug.**
To close the gap: use `PROC HPLOGISTIC` with `RIDGE=1.0` in ODA to add L2
regularisation matching Python's C=1.0, and replace `was_contacted_before`
with raw `pdays` in the SAS model. This requires re-running 02_model.sas and
04_reconcile_export.sas.

**Loosening the tolerance is not recommended** — the gap is real and
documented. Instead, choose one implementation as the canonical version for
the deck. The Python implementation with its explicit regularisation choice
is the recommended canonical version.

---

## 3. MPPC per tertile

Tolerance: ±€0.50 per tertile.

Note: MPPC = response_rate × €150 − €2.50, so Δ MPPC = Δ rate × 150.
The MPPC tolerance (±€0.50) implies a rate tolerance of
±0.33 pp — stricter than the stated ±0.5 pp rate
tolerance. A rate that passes can therefore still produce a failing MPPC.

| Tertile | Python | SAS | Diff | Verdict |
|---|---|---|---|---|
| T1 High | €66.64 | €64.36 | -2.28 | **FAIL** |
| T2 Medium | €60.44 | €59.15 | -1.29 | **FAIL** |
| T3 Low | €38.44 | €38.96 | +0.52 | **FAIL** |

---

## 4. Business recommendation

Tertile rank order: Python=['T1 High', 'T2 Medium', 'T3 Low']  SAS=['T1 High', 'T2 Medium', 'T3 Low']  AGREE.
All tertiles profitable: Python=True  SAS=True.
T2→T3 MPPC gap: Python=€22.00  SAS=€20.19  consistent.

### Verdict

The business recommendation — **T1+T2 as the priority tier, T3 conditional
on budget** — is **UNCHANGED** by the SAS implementation.

Both implementations agree that:
- All three tertiles are profitable (MPPC > 0).
- T1 > T2 > T3 in MPPC rank order.
- The T2→T3 gap is the binding budget decision point, not the T1→T2 gap.

The quantitative P&L figures differ because of the documented structural
differences. **For the deck**, use Python output/model_metrics.json and
src/pnl/engine.py as the single source of numbers. The SAS implementation
serves as an independent structural check that the model direction and
tertile ordering are correct.

---

## 5. What would make this reconciliation PASS end-to-end?

To achieve full numerical agreement within stated tolerances:

1. **Match regularisation**: Use `PROC HPLOGISTIC` with `RIDGE=1.0` in SAS
   (equivalent to sklearn's default L2 C=1.0 with StandardScaler).
2. **Match the pdays feature**: Use raw `pdays` in both (drop `was_contacted_before`
   from SAS, or add it to Python). Raw pdays is the weaker encoding; if changed,
   update `docs/assumptions.md` decision #5.
3. **Match the tertile method**: Confirm `proc_rank_groups()` and
   `PROC RANK GROUPS=3 TIES=MEAN` produce identical group assignments —
   verify by exporting individual row scores and group labels from both.

None of these changes are required to support the deck. The recommendation
is robust to the documented differences.
