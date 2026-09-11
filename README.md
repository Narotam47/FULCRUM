# fulcrum-campaign-pnl

A Portuguese retail bank ran 41,188 outbound calls over 30 months without ranking
prospects; this project builds a logistic regression scoring model and quantifies
what a ranked contact list is worth.

Targeting the model's top two thirds of prospects adds **€34,450 gross profit**
over calling the same contacts in random order.

[Tableau Public dashboard](https://public.tableau.com/app/profile/narotam.ojha/viz/FULCRUM/Dashboard1)

---

## Results

| | |
|---|---|
| Dataset | UCI Bank Marketing — 41,176 contacts after dedup |
| Test set | 6,177 contacts, time-ordered (May 2009–Nov 2010) |
| Model | Logistic regression · AUC 0.5979 |
| T1 response rate | 46.1% |
| T2 response rate | 42.0% |
| T3 response rate | 27.3% |
| Test-set base rate | 38.4% |
| T1 MPPC | €66.64 |
| T2 MPPC | €60.52 |
| T3 MPPC | €38.44 |
| T1+T2 value of targeting | €34,450 vs. naive equal-allocation |
| Gains at T1+T2 cut-off | 76.5% of conversions at 67.0% contact depth |

MPPC = margin per prospect contacted. P&L at €2.50/contact, €10,000 balance,
1.50% NIM, 12-month tenor.

---

## Reproduce

```bash
conda env create -f environment.yml && conda activate fulcrum
make pnl
```

Runs the full pipeline — download, dedup, feature engineering, train, score, P&L —
and writes `output/reports/pnl_summary.csv` and `data/tableau/*.csv`.
Raw data is fetched from the UCI repository; no manual download required.

---

## Stack

- **Split**: 70/15/15 time-ordered; no shuffle. Train ends row 28,823; test rows 35,000–41,176.
- **Model**: `sklearn.linear_model.LogisticRegression`, L2, C=1.0. `StandardScaler` fit on train only.
- **Features**: 52 after `get_dummies(drop_first=True)` on 16 raw columns. `duration` excluded (see Design Decisions).
- **Tertiles**: `floor((rank−1)×3/n)` — mirrors SAS PROC RANK GROUPS=3 TIES=MEAN.
- **SAS port**: `sas/01_prep.sas` – `sas/04_reconcile_export.sas`. `python/08_reconcile.py` finds 18/52 coefficients outside ±0.05 tolerance; no sign disagreements; business recommendation unchanged.

---

## Design Decisions

| Decision | Alternative considered | Reason chosen |
|---|---|---|
| Exclude `duration` | Include as a predictor | Call duration is only known after the call ends. A model using it cannot score a prospect before contact is made. |
| Time-ordered split | Random stratified split | The data is a chronological campaign log. Shuffling leaks future contacts into training and inflates AUC on a sequence with known temporal structure. |
| Logistic regression | Random forest, HistGradientBoosting | Tree models fit the 2008 call pattern closely but did not generalise to the 2010 rate environment. Logistic regression produced higher validation AUC on the held-out 2009–2010 segment. |
| Tertile (3 groups) | Decile (10 groups) | At n ≈ 618 per decile, Wilson confidence intervals on response rates overlap across adjacent groups. At n ≈ 2,059 per tertile the T2→T3 gap (14.7 pp) is unambiguous; tertile is the finest defensible cut. |

---

## Limitations

- **No control group.** The model estimates propensity, not incrementality. The €34,450 figure assumes model-selected T1+T2 contacts would have responded at the base rate if randomly drawn — this is untested without a holdout experiment.
- **Assumed P&L inputs.** Balance (€10,000), NIM (1.50%), and tenor (12 months) are calibrated to ECB MFI statistics and industry benchmarks. None is pinned to this bank's audited data.
- **Regime shift in the test set.** The test-period base rate (38.4%) is 3.4× the full-dataset rate (11.3%), reflecting a compressed 2010 campaign cadence. Performance figures should not be extrapolated to periods with different call frequency or economic conditions.
- **Not validated on a live campaign.** All performance figures are retrospective on a historical split.
