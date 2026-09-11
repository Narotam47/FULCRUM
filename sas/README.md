# SAS Implementation

Runs on **SAS OnDemand for Academics** (SAS Studio).

## Setup

1. Upload `data/raw/bank-additional-full.csv` to your SAS home directory.
2. Open each `.sas` file in SAS Studio and run in order.

## Files

| File | Purpose |
|------|---------|
| `01_ingest.sas` | Import CSV, validate, create SAS dataset |
| `02_eda.sas` | PROC FREQ, PROC MEANS, PROC SGPLOT |
| `03_model.sas` | PROC LOGISTIC with ROC |
