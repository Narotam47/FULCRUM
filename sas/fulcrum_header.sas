/* ============================================================================
   FULCRUM project-standard header block
   Copy this block verbatim to the top of every .sas file in this project.
   Replace the three tagged fields (FILE / PURPOSE / CREATED) per file.
   Everything else is project-wide boilerplate — do not paraphrase it.
   ============================================================================

   PROJECT   : FULCRUM — Campaign Performance & P&L Analyser
   FILE      : <filename.sas>                              /* REPLACE */
   PURPOSE   : <one-line description of what this file does> /* REPLACE */
   CREATED   : <YYYY-MM-DD>                                /* REPLACE */
   AUTHOR    : FULCRUM pipeline port — reconciliation against Python output

   ENVIRONMENT
   -----------
   Platform  : SAS OnDemand for Academics (browser SAS Studio)
   Modules   : Base SAS + SAS/STAT
   Session   : Times out after ~60 min inactivity; WORK is then wiped.
               All permanent output uses LIBNAME fulcrum (see below).

   LIBNAME REFERENCE
   -----------------
   Run this block once at the top of every session before any other code.
   %sysget(HOME) resolves to /home/u<your_userid>/ automatically — no
   hardcoded paths needed.

   options dlcreatedir;
   libname fulcrum "%sysget(HOME)/FULCRUM/sas";

   Verify with: %put NOTE- FULCRUM lib: %sysfunc(pathname(fulcrum));

   PYTHON DECISIONS BEING MATCHED — locked; do not re-derive
   -----------------------------------------------------------
   These decisions were made in the Python pipeline after analysis.
   The SAS code matches them exactly. Do not revisit them here.

   1. DURATION EXCLUDED (leakage)
      duration is the length of the call that produced this row's outcome.
      It does not exist before the call is placed, so it must not enter any
      pre-call propensity model.
      Python source : docs/data_dictionary.md (AFTER column, explicit warning)
                      python/02_feature_eng.py (column never selected)
      SAS action    : drop duration at first DATA step; never reference it again.

   2. UNKNOWN KEPT AS EXPLICIT CATEGORY (no mode imputation)
      "unknown" values in categorical columns are an informative signal —
      willingness to disclose correlates with subscription outcome.
      Imputing the mode would destroy this signal.
      Affected cols : job, marital, education, default, housing, loan,
                      contact, poutcome
                      (default is 20.87% unknown — highest missingness rate)
      Python source : notebooks/01_eda.ipynb data-quality decision #3
                      python/02_feature_eng.py (fillna("unknown"), not mode)
      SAS action    : keep "unknown" as a valid format level; do not replace.

   3. TIME-ORDERED TRAIN/VAL/TEST SPLIT — 70 / 15 / 15, no shuffle
      The dataset is chronologically sorted (May 2008 → November 2010).
      A random split leaks future macro-economic regime into training,
      overstating test AUC by ~0.20. Contiguous row-order slices are used.
      Row counts (after 12-row dedup):
        Total  : 41,176
        Train  : rows     1 – 28,823  (70%)  base rate ~5.6%
        Val    : rows 28,824 – 34,999  (15%)
        Test   : rows 35,000 – 41,176  (15%)  base rate ~38.4%  <- use this
      Python source : src/data/split.py (time_ordered_split)
                      notebooks/02_split_strategy.ipynb
      SAS action    : use _N_ or an explicit row-number variable to slice;
                      never use PROC SURVEYSELECT or random seeding for split.

   4. TERTILE GRANULARITY (not decile)
      Decile-level differentiation is not defensible: Wilson 95% CIs overlap
      for all four decile-to-decile reversals at n≈618/decile (±4-5 pp).
      Tertile is the minimum defensible resolution.
      Test-set tertile response rates (from model scoring):
        T1 High   : 46.1%  CI [43.9%, 48.2%]  n=2,059
        T2 Medium : 42.0%  CI [39.8%, 44.1%]  n=2,059
        T3 Low    : 27.3%  CI [25.4%, 29.3%]  n=2,059
      Python source : notebooks/03_decile_analysis.ipynb
                      src/pnl/engine.py
      SAS action    : score test set, compute tertile cutpoints on pred_prob,
                      verify response rates match Python output within rounding.

   5. PDAYS = 999 SENTINEL → was_contacted_before FLAG
      999 means "not previously contacted" (96.3% of rows). Using raw 999
      as a numeric predictor implies a false ordinal relationship.
      Python source : notebooks/01_eda.ipynb, python/02_feature_eng.py
      SAS action    : was_contacted_before = (pdays ne 999);
                      Do not include raw pdays as a numeric feature.

   6. DEDUPLICATION — 12 exact duplicate rows dropped at ingest
      Row count in source CSV  : 41,188
      Row count after dedup    : 41,176  <- use this denominator everywhere
      Python source : python/01_ingest.py (drop_duplicates)
      SAS action    : PROC SORT NODUPKEY on all 21 columns immediately after
                      import; confirm OUT= row count = 41,176.

   RUN LOG — append one line per execution
   ----------------------------------------
   Date       | Operator | Git ref / note
   -----------+----------+----------------------------------------------------
   &SYSDATE.  | <name>   | Initial port run

   ============================================================================ */

/* ── LIBNAME (paste this at the top of every session, before other code) ──── */
options dlcreatedir;
libname fulcrum "%sysget(HOME)/FULCRUM/sas";
%put NOTE- FULCRUM lib path: %sysfunc(pathname(fulcrum));

/* ── Verify expected row count after any ingest step ─────────────────────── */
%let expected_rows = 41176;   /* post-dedup */
%let test_base_rate = 0.384;  /* test-period, not overall 11.3% */
%let train_end  = 28823;
%let val_end    = 34999;
%let total_rows = 41176;
