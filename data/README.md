# Data

## Source

UCI Bank Marketing Dataset  
https://archive.ics.uci.edu/dataset/222/bank+marketing

**File:** `bank-additional-full.csv` — 41,188 rows × 21 columns  
**Task:** Predict whether a client subscribes to a term deposit (`y`).

## Acquisition

Raw data is gitignored. To fetch it:

```bash
make data
```

## Directory layout

- `raw/` — Original CSV, untouched after download.
- `processed/` — Cleaned and feature-engineered outputs from the Python pipeline.
