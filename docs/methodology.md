# Methodology

## Dataset

UCI Bank Marketing (Moro et al., 2014). 41,188 records of direct marketing
campaigns (phone calls) by a Portuguese bank. Target: term deposit subscription.

## Pipeline

1. **Ingest** — Load CSV, normalize column names, encode target, mark unknowns as NA.
2. **Feature engineering** — Impute missing categoricals (mode), one-hot encode, create
   campaign intensity ratio.
3. **EDA** — Target distribution, age histogram by outcome, top-variance correlation heatmap.
4. **Modeling** — Logistic regression and random forest with stratified 80/20 split. Primary
   metric: ROC AUC.
5. **P&L** — Unit-economics model: $5/contact cost, $500/conversion revenue. Segment by
   campaign intensity bucket.

## Assumptions

See [assumptions.md](assumptions.md).

## References

Moro, S., Cortez, P., & Rita, P. (2014). A data-driven approach to predict the
success of bank telemarketing. *Decision Support Systems*, 62, 22–31.
