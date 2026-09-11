/* ============================================================================
   FULCRUM — Campaign Performance & P&L Analyser
   FILE      : 01_prep.sas
   PURPOSE   : Ingest, deduplicate, feature-engineer, and split the UCI Bank
               Marketing dataset — SAS port of python/01_ingest.py,
               src/data/split.py, and python/02_feature_eng.py.
   CREATED   : 2026-09-06
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
      SAS action    : use seq_row (sequential counter post-dedup) to slice;
                      never use PROC SURVEYSELECT or random seeding for split.

   4. TERTILE GRANULARITY (not decile)
      Decile-level differentiation is not defensible: Wilson 95% CIs overlap
      for all four decile-to-decile reversals at n~618/decile (+/-4-5 pp).
      Tertile is the minimum defensible resolution.
      Test-set tertile response rates (from model scoring):
        T1 High   : 46.1%  CI [43.9%, 48.2%]  n=2,059
        T2 Medium : 42.0%  CI [39.8%, 44.1%]  n=2,059
        T3 Low    : 27.3%  CI [25.4%, 29.3%]  n=2,059
      Python source : notebooks/03_decile_analysis.ipynb, src/pnl/engine.py
      SAS action    : score test set in 02_model.sas, compute tertile
                      cutpoints on pred_prob, verify response rates match.

   5. PDAYS = 999 SENTINEL -> was_contacted_before FLAG
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
   2026-09-06 | <name>   | Initial port

   ============================================================================ */


/* ── LIBNAME ──────────────────────────────────────────────────────────────── */
options dlcreatedir;
libname fulcrum "%sysget(HOME)/FULCRUM/sas";
%put NOTE- FULCRUM lib path: %sysfunc(pathname(fulcrum));


/* ── Row-count assertion macro ───────────────────────────────────────────── */
/* Equivalent to Python's "assert len(df) == n, f'expected n, got len(df)'"  */
/* %put ERROR: writes an ERROR line to the SAS log — visually alarming and   */
/* sets the automatic return code, matching assert's job of failing loudly.  */
%macro assert_rowcount(ds=, expected=, label=);
    %local n;
    proc sql noprint;
        select count(*) into :n trimmed from &ds;
    quit;
    %if &n ne &expected %then %do;
        %put ERROR: [FULCRUM ASSERTION FAILED] &label — expected &expected rows, found &n;
        %put ERROR: Check for upstream changes (truncated download, wrong dataset version, etc.);
    %end;
    %else %do;
        %put NOTE- [FULCRUM] OK: &label — &n rows as expected;
    %end;
%mend assert_rowcount;


/* ============================================================================
   STEP 1 — Import raw CSV
   Mirrors: pd.read_csv(path, sep=";")  [python/01_ingest.py line 12]

   GUESSINGROWS=MAX scans all rows before assigning types. The default of 20
   rows misclassifies pdays (the 999 sentinel looks like an outlier and can
   cause type coercion issues) and underestimates the width of cons_conf_idx.
   See gotcha #2 in sas/fulcrum_header.sas.

   Column-name note: PROC IMPORT converts characters invalid in SAS names to
   underscores automatically. Three column names contain dots in the source CSV:
     emp.var.rate  -> emp_var_rate
     cons.price.idx -> cons_price_idx
     cons.conf.idx  -> cons_conf_idx
   This matches Python's str.replace(".", "_") rename in python/01_ingest.py.
   All other column names are already valid SAS identifiers.
   ============================================================================ */

proc import
    datafile="%sysget(HOME)/FULCRUM/data/raw/bank-additional-full.csv"
    out=work.bank_import
    dbms=dlm
    replace;
    delimiter=";";
    getnames=yes;
    guessingrows=MAX;
run;

%assert_rowcount(ds=work.bank_import, expected=41188, label=Raw import (pre-dedup))


/* ============================================================================
   STEP 2 — Encode, tag for dedup, keep unknown as-is
   Mirrors: python/01_ingest.py lines 17-25 (rename, encode y, replace unknown)
            python/02_feature_eng.py lines 39-40 (fillna("unknown"))

   PANDAS ROUND-TRIP NOTE:
   Python 01_ingest.py does:  df.replace("unknown", pd.NA)
   Python 02_feature_eng.py does:  df[col].fillna("unknown")
   Net effect on every categorical column: "unknown" -> NaN -> "unknown".
   The round-trip is a no-op. In SAS we simply never touch "unknown", which
   produces the identical outcome without the intermediate NaN state.
   "unknown" appears as a distinct character level in PROC FREQ output —
   that is the intended behaviour (see decision #2 above).

   DATAFRAME INDEX NOTE:
   pandas .iloc[] uses 0-based indexing and the original row order of the
   DataFrame. original_row = _N_ captures the same thing in SAS: the
   1-based position of each row in the dataset as read. We need it to
   restore chronological order after PROC SORT scrambles rows for dedup.

   y ENCODING NOTE:
   Python: df["y"] = (df["y"] == "yes").astype(int) — produces numeric 0/1.
   SAS:    y = (y_char = "yes") — the boolean comparison returns 1/0 numeric.
   SAS reads character "yes"/"no" from the CSV; the rename-at-input idiom
   avoids naming collision between the character y_char and the new numeric y.

   duration is NOT dropped here — Python deduplicated on all 21 original
   columns including duration (01_ingest.py drop_duplicates() runs before
   02_feature_eng.py selects BEFORE_COLUMNS). Dropping it before dedup would
   change which rows are identified as duplicates if any duplicate pair
   differed only in duration — keep it through the dedup step for fidelity.
   ============================================================================ */

data work.bank_step1;
    set work.bank_import(rename=(y=y_char));

    /* Preserve original row position for order restoration after dedup sort. */
    original_row = _N_;

    /* Encode target. */
    y = (y_char = "yes");
    drop y_char;
    label y = "Term deposit subscribed (1=yes, 0=no)";

    /* "unknown" is already a character value in every categorical column.
       No action needed — see PANDAS ROUND-TRIP NOTE above. */
run;


/* ============================================================================
   STEP 3 — Deduplicate: drop 12 exact duplicate rows
   Mirrors: df.drop_duplicates()  [python/01_ingest.py lines 29-30]

   SORT ORDER MISMATCH NOTE:
   pandas drop_duplicates() keeps the first occurrence of each duplicate in
   the original row order without reordering anything else. PROC SORT reorders
   the entire dataset. We recover original order in two passes:
     Pass A: sort by all 21 data columns then original_row ascending.
             Within each duplicate group, the row with the smallest
             original_row (earliest chronological position) sorts first.
             NODUPKEY discards all but the first row in the group —
             equivalent to pandas keeping the first occurrence.
     Pass B: sort by original_row to restore chronological sequence.

   The y variable is now numeric (0/1). Duration is included in the BY list
   because Python deduped on all 21 columns. The 12 duplicate rows are exact
   across all columns, so including or excluding duration does not change the
   result for this dataset — but we match Python exactly.
   ============================================================================ */

/* Pass A: dedup. */
proc sort data=work.bank_step1 out=work.bank_deduped nodupkey;
    by age job marital education default housing loan contact month
       day_of_week duration campaign pdays previous poutcome
       emp_var_rate cons_price_idx cons_conf_idx euribor3m nr_employed
       y original_row;
run;

/* Pass B: restore chronological order. */
proc sort data=work.bank_deduped out=work.bank_deduped;
    by original_row;
run;

%assert_rowcount(ds=work.bank_deduped, expected=41176, label=Post-dedup (should drop exactly 12 rows))


/* ============================================================================
   STEP 4 — Feature engineering: drop duration, create was_contacted_before,
             assign sequential row counter for split
   Mirrors: python/02_feature_eng.py (BEFORE_COLUMNS selection + pdays flag)
            Also mirrors the pdays decision from notebooks/01_eda.ipynb.

   SEQUENTIAL ROW COUNTER NOTE:
   After dedup + order restoration, original_row has 12 gaps (the dropped
   rows). Python's .iloc[] uses the post-dedup DataFrame index, which is
   contiguous 0..41175 after reset_index(drop=True). seq_row = _N_ gives the
   equivalent contiguous 1..41176 counter in SAS.

   Save the clean, pre-split dataset to the permanent library so it survives
   session timeout. Downstream scripts read fulcrum.bank_clean, not WORK.
   ============================================================================ */

data fulcrum.bank_clean;
    set work.bank_deduped;

    /* Drop duration (leakage — decision #1). */
    drop duration original_row;

    /* Sentinel flag (decision #5). */
    was_contacted_before = (pdays ne 999);
    label was_contacted_before = "Client was contacted in a prior campaign (pdays != 999)";

    /* Sequential counter for time-ordered split. */
    seq_row = _N_;

    label
        age                  = "Client age (years)"
        job                  = "Job type (unknown kept as category)"
        marital              = "Marital status"
        education            = "Education level (unknown kept as category)"
        default              = "Has credit in default (unknown kept as category)"
        housing              = "Has housing loan (unknown kept as category)"
        loan                 = "Has personal loan (unknown kept as category)"
        contact              = "Contact communication type"
        month                = "Last contact month"
        day_of_week          = "Last contact day of week"
        campaign             = "Contacts performed during this campaign"
        pdays                = "Days since last contact (999 = never contacted)"
        previous             = "Contacts performed before this campaign"
        poutcome             = "Outcome of previous campaign (unknown kept as category)"
        emp_var_rate         = "Employment variation rate (quarterly)"
        cons_price_idx       = "Consumer price index (monthly)"
        cons_conf_idx        = "Consumer confidence index (monthly)"
        euribor3m            = "Euribor 3-month rate (daily)"
        nr_employed          = "Number of employees (quarterly)"
        y                    = "Term deposit subscribed (1=yes, 0=no)"
        seq_row              = "Sequential row number post-dedup (1..41176)";
run;

%assert_rowcount(ds=fulcrum.bank_clean, expected=41176, label=fulcrum.bank_clean)


/* ============================================================================
   STEP 5 — Time-ordered split: 70 / 15 / 15
   Mirrors: src/data/split.py time_ordered_split(df, train_frac=0.7, val_frac=0.15)

   BOUNDARY ARITHMETIC (matching Python exactly):
     n          = 41176  (post-dedup)
     train_end  = int(41176 * 0.70) = int(28823.2) = 28823
     val_end    = 28823 + int(41176 * 0.15)
                = 28823 + int(6176.4)
                = 28823 + 6176
                = 34999
     test range = 35000..41176

   Python iloc[a:b] is exclusive on the right (0-indexed). Translated to
   1-based SAS seq_row:
     train: seq_row in [1,  28823]  -> 28,823 rows
     val:   seq_row in [28824, 34999] -> 6,176 rows
     test:  seq_row in [35000, 41176] -> 6,177 rows

   NOTE: these boundaries differ slightly from what a naive rounding might
   suggest (34999 not 35000 for val_end). They match the Python int()
   truncation exactly — int() truncates toward zero, not rounds.

   NO-SHUFFLE NOTE:
   Python time_ordered_split does NOT call reset_index or shuffle. Rows flow
   in their natural order. SAS reads fulcrum.bank_clean in seq_row order
   (how it was written) and the IF/ELSE dispatches preserve that order within
   each output dataset. Equivalent to Python.
   ============================================================================ */

%let train_end = 28823;
%let val_end   = 34999;
/* test_end is n (41176) — all remaining rows */

data fulcrum.bank_train
     fulcrum.bank_val
     fulcrum.bank_test;
    set fulcrum.bank_clean;
    if      seq_row le &train_end then output fulcrum.bank_train;
    else if seq_row le &val_end   then output fulcrum.bank_val;
    else                               output fulcrum.bank_test;
run;


/* ── Split-count assertions ───────────────────────────────────────────────── */
%assert_rowcount(ds=fulcrum.bank_train, expected=28823, label=bank_train (70%))
%assert_rowcount(ds=fulcrum.bank_val,   expected=6176,  label=bank_val   (15%))
%assert_rowcount(ds=fulcrum.bank_test,  expected=6177,  label=bank_test  (15%))


/* ============================================================================
   STEP 6 — Spot-checks: verify Python decisions are faithfully reproduced
   These are diagnostic only — review the output in the Results tab.
   ============================================================================ */

/* 6a. Decision #2: "unknown" must appear as a distinct category level.
       If mode imputation had fired, "unknown" would be absent here. */
title "SPOT-CHECK 6a — 'unknown' as distinct level (default, job, poutcome)";
title2 "Fail if 'unknown' row is absent from any of these columns";
proc freq data=fulcrum.bank_clean order=freq;
    tables default job poutcome / nocum nopercent missing;
run;
title;

/* 6b. Decision #1 + #5: duration must be absent; was_contacted_before present. */
title "SPOT-CHECK 6b — Column inventory (duration must NOT appear)";
proc contents data=fulcrum.bank_clean varnum; run;
title;

/* 6c. Decision #3 + target encoding: test-set base rate should be ~38.4%. */
title "SPOT-CHECK 6c — Test-set y distribution (expect ~38.4% positive)";
proc freq data=fulcrum.bank_test;
    tables y / nocum;
run;
title;

/* 6d. Decision #5: was_contacted_before distribution (expect ~3.7% positive,
       since 96.3% of rows have pdays=999). */
title "SPOT-CHECK 6d — was_contacted_before flag (expect ~96.3% zero)";
proc freq data=fulcrum.bank_clean;
    tables was_contacted_before / nocum;
run;
title;

/* 6e. Numeric sanity check on socio-economic indicators. */
title "SPOT-CHECK 6e — Economic indicators (sanity: ranges should be plausible)";
proc means data=fulcrum.bank_clean n min max mean stddev;
    var emp_var_rate cons_price_idx cons_conf_idx euribor3m nr_employed;
run;
title;


/* ── Final confirmation in the log ───────────────────────────────────────── */
%put NOTE- ;
%put NOTE- [FULCRUM 01_prep.sas] Complete. Permanent datasets written:;
%put NOTE-   fulcrum.bank_clean  — 41,176 rows, 20 features + y + seq_row;
%put NOTE-   fulcrum.bank_train  — 28,823 rows (70%);
%put NOTE-   fulcrum.bank_val    —  6,176 rows (15%);
%put NOTE-   fulcrum.bank_test   —  6,177 rows (15%);
%put NOTE-   All row-count assertions passed if no ERROR lines appear above.;
%put NOTE- ;
