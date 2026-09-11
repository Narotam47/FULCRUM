# Data Dictionary — bank-additional-full.csv

Source: [UCI Bank Marketing Dataset](https://archive.ics.uci.edu/dataset/222/bank+marketing)
File: `bank-additional-full.csv` — 41,188 rows × 21 columns, semicolon-delimited.

> The UCI archive also ships `bank-full.csv`, an older 17-column variant
> without the socio-economic indicators and with `day`/`balance` in place of
> `day_of_week`/the economic columns below. [`src/data/load.py`](../src/data/load.py)
> rejects it explicitly — this project uses `bank-additional-full.csv` only.

## ⚠ Data leakage warning: `duration`

`duration` is the length of the call that this row's outcome was decided on.
**It does not exist until the call has ended.** A model trained with
`duration` included is not predicting whether a call will succeed — it is
using the fact that long calls tend to end in a sale, which you cannot know
in advance for a call you haven't placed yet. `duration` is useful only as a
benchmark ceiling (how well could a model do with hindsight) or for *in-call*
next-best-action decisions, never for a pre-call propensity model.

**Any model scoring leads before a call is placed must drop `duration`.**

## Columns

| # | Column | Type | Meaning | Known |
|---|--------|------|---------|-------|
| 1 | `age` | int | Client's age in years | **BEFORE** |
| 2 | `job` | categorical | Job type (admin., blue-collar, entrepreneur, housemaid, management, retired, self-employed, services, student, technician, unemployed, unknown) | **BEFORE** |
| 3 | `marital` | categorical | Marital status (divorced, married, single, unknown) | **BEFORE** |
| 4 | `education` | categorical | Education level (basic.4y, basic.6y, basic.9y, high.school, illiterate, professional.course, university.degree, unknown) | **BEFORE** |
| 5 | `default` | categorical | Has credit in default? (yes, no, unknown) | **BEFORE** |
| 6 | `housing` | categorical | Has a housing loan? (yes, no, unknown) | **BEFORE** |
| 7 | `loan` | categorical | Has a personal loan? (yes, no, unknown) | **BEFORE** |
| 8 | `contact` | categorical | Contact communication type (cellular, telephone) | **BEFORE** — this is chosen, not observed |
| 9 | `month` | categorical | Last contact month of year | **BEFORE** — scheduled, not observed |
| 10 | `day_of_week` | categorical | Last contact day of week (mon–fri) | **BEFORE** — scheduled, not observed |
| 11 | `duration` | int (seconds) | Duration of the last call | **AFTER** — see leakage warning above |
| 12 | `campaign` | int | Number of contacts made to this client during this campaign, **including the current one** | **BEFORE**, with a caveat¹ |
| 13 | `pdays` | int | Days since client was last contacted in a *previous* campaign (999 = never contacted before) | **BEFORE** |
| 14 | `previous` | int | Number of contacts made to this client *before* this campaign | **BEFORE** |
| 15 | `poutcome` | categorical | Outcome of the previous campaign (failure, nonexistent, success) | **BEFORE** |
| 16 | `emp.var.rate` | float | Employment variation rate — quarterly macro indicator | **BEFORE** — published independently of this call |
| 17 | `cons.price.idx` | float | Consumer price index — monthly macro indicator | **BEFORE** |
| 18 | `cons.conf.idx` | float | Consumer confidence index — monthly macro indicator | **BEFORE** |
| 19 | `euribor3m` | float | Euribor 3-month rate — daily macro indicator | **BEFORE** |
| 20 | `nr.employed` | float | Number of employees — quarterly macro indicator | **BEFORE** |
| 21 | `y` | categorical (yes/no) | **Target.** Did the client subscribe to a term deposit? | **AFTER** — this is the outcome |

¹ `campaign`'s definition ("includes last contact") means its *final* value
for a row is only fixed once that row's call has happened. Operationally,
though, you always know this count going into the call — it's "this is
contact attempt N," not something the call outcome determines. Treat it as
BEFORE for scoring purposes, but be aware it is entangled with the row's own
call event, unlike a pure pre-existing client attribute.

## Summary

- **Usable for pre-call scoring (propensity models):** all columns except `duration` and `y`.
- **Target:** `y`.
- **Benchmark-only / leaky:** `duration` — include only to measure an upper
  bound on model performance, and say so explicitly wherever it's used.
