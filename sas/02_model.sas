/* ============================================================================
   FULCRUM — Campaign Performance & P&L Analyser
   FILE      : 02_model.sas
   PURPOSE   : Fit logistic regression propensity model on fulcrum.bank_train,
               score fulcrum.bank_test, write fulcrum.bank_test_scored with
               predicted probability column p_hat. SAS port of
               src/models/train.py + python/04_model.py.
   CREATED   : 2026-09-07
   AUTHOR    : FULCRUM pipeline port — reconciliation against Python output

   ENVIRONMENT
   -----------
   Platform  : SAS OnDemand for Academics (browser SAS Studio)
   Modules   : Base SAS + SAS/STAT
   Prerequisite: Run sas/01_prep.sas first.

   PYTHON DECISIONS BEING MATCHED
   ---------------------------------------------------------------
   1. DURATION EXCLUDED — not in BEFORE_COLUMNS; see 01_prep.sas.
   2. UNKNOWN AS EXPLICIT CATEGORY — kept in CLASS statement.
   3. TIME-ORDERED SPLIT — fulcrum.bank_train is rows 1–28,823.
   4. TERTILE GRANULARITY — applied in 03_pnl.sas after scoring.
   5. was_contacted_before REPLACES raw pdays — see note below.

   KNOWN DIFFERENCES FROM PYTHON (read before reconciling coefficients)
   ---------------------------------------------------------------
   A. REGULARISATION — MOST IMPORTANT MISMATCH SOURCE
      Python: LogisticRegression(max_iter=1000, random_state=42)
        uses L2 regularisation with C=1.0 (the sklearn default).
        C=1.0 means the regularisation strength equals 1/C = 1.0 applied to
        the scaled coefficients.  This shrinks coefficients toward zero.
      SAS:    PROC LOGISTIC is pure maximum-likelihood — no regularisation.
        SAS can be given L2 penalty via PROC HPLOGISTIC (RIDGE=) or via
        PROC GLMSELECT, but both are overkill for a reconciliation exercise.
      Impact: predicted probabilities WILL differ between Python and SAS.
        The tertile ORDERING (rank order of p_hat) should be highly
        consistent; the exact probability VALUES will not match.  Check
        Spearman rank correlation between the two scored files — if >0.95
        the models agree on who is high/low propensity even if the numbers
        differ.  This is the right reconciliation diagnostic for P&L tertiles.

   B. STANDARD SCALING — does NOT affect unregularised predictions
      Python: StandardScaler().fit(X_train[NUMERIC]) — scales 9 numeric
        columns so regularisation is applied equitably across features.
      SAS:    No PROC STDIZE step.  For a pure-MLE logistic regression with
        no regularisation penalty, scaling the inputs does not change the
        predicted probabilities — the optimisation finds an equivalent
        solution.  Adding PROC STDIZE before PROC LOGISTIC would produce
        different COEFFICIENTS (interpretable as standardised betas) but
        identical p_hat values.  Omitted for clarity.

   C. pdays vs was_contacted_before — deliberate improvement
      Python: raw pdays (scaled) enters the model as a continuous numeric.
        pdays=999 (96.3% of rows) becomes a large positive value after
        StandardScaler, which the model must learn to interpret as "no
        prior contact".  This is a messy encoding.
      SAS:    was_contacted_before = (pdays ne 999) enters as a clean binary
        flag.  The 01_prep.sas DATA step creates this column.  This is a
        cleaner encoding of the same information (see header decision #5).
        The models are not numerically identical on this feature.

   D. REFERENCE LEVELS — the second most likely coefficient mismatch source
      Python pd.get_dummies(drop_first=True) sorts category levels
      alphabetically and drops the first (= makes it the reference).
      PROC LOGISTIC default is REF=LAST (last alphabetical level).
      We override to REF=FIRST ORDER=FORMATTED to match Python exactly.

      Reference level table (verify these match your data):
      ┌──────────────┬──────────────────────────────────────────┐
      │ Variable     │ Reference level (alphabetically first)   │
      ├──────────────┼──────────────────────────────────────────┤
      │ job          │ admin.                                   │
      │ marital      │ divorced                                 │
      │ education    │ basic.4y                                 │
      │ default      │ no                                       │
      │ housing      │ no                                       │
      │ loan         │ no                                       │
      │ contact      │ cellular                                 │
      │ month        │ apr                                      │
      │ day_of_week  │ fri                                      │
      │ poutcome     │ failure                                  │
      └──────────────┴──────────────────────────────────────────┘
      "unknown" is never the alphabetically-first level for any variable,
      so it retains its own coefficient in both Python and SAS (decision #2).

   RUN LOG — append one line per execution
   ----------------------------------------
   Date       | Operator | Git ref / note
   -----------+----------+----------------------------------------------------
   2026-09-07 | <name>   | Initial port

   ============================================================================ */


/* ── LIBNAME ──────────────────────────────────────────────────────────────── */
options dlcreatedir;
libname fulcrum "%sysget(HOME)/FULCRUM/sas";
%put NOTE- FULCRUM lib path: %sysfunc(pathname(fulcrum));

/* Enable ODS Graphics for the calibration and ROC plots. */
ods graphics on;


/* ── Verify prerequisites ─────────────────────────────────────────────────── */
%macro check_prereq(ds=, step=);
    %if not %sysfunc(exist(&ds)) %then %do;
        %put ERROR: [FULCRUM] &ds does not exist — run &step first;
        %abort cancel;
    %end;
%mend check_prereq;

%check_prereq(ds=fulcrum.bank_train, step=01_prep.sas)
%check_prereq(ds=fulcrum.bank_test,  step=01_prep.sas)


/* ============================================================================
   STEP 1 — Fit logistic regression on training data only
   Mirrors: src/models/train.py  fit_logistic_regression()

   MODEL STATEMENT NOTE:
   Python produces one-hot dummies via pd.get_dummies(drop_first=True).
   PROC LOGISTIC with CLASS produces equivalent reference-cell coding
   internally — no need to manually create dummies.  The CLASS statement
   options achieve the same reference level as Python:
     PARAM=REF       = reference-cell coding (same as drop_first=True)
     ORDER=FORMATTED = sort levels alphabetically for character variables
     REF=FIRST       = make the first sorted level the reference (= dropped)
   Together these exactly replicate what pd.get_dummies(drop_first=True)
   does for each categorical column.

   DESCENDING / EVENT NOTE:
   y is binary numeric (0/1).  Without intervention PROC LOGISTIC models
   P(y=0) because 0 < 1 (it models the lower-ordered response by default).
   EVENT='1' makes it model P(y=1) — the probability of subscription —
   matching Python's predict_proba(X)[:, 1].

   LACKFIT NOTE:
   The LACKFIT option adds the Hosmer-Lemeshow goodness-of-fit test.
   See the bottom of this file for how this compares to Python's Brier score.

   PLOTS NOTE:
   PLOTS=(ROC CALIBRATION) requires ODS GRAPHICS ON (done above).
   The CALIBRATION plot is the SAS equivalent of
   sklearn.calibration.CalibrationDisplay.from_predictions().
   ============================================================================ */

proc logistic data=fulcrum.bank_train
              outmodel=work.lr_model
              plots(only)=(roc calibration);

    class job marital education default housing loan
          contact month day_of_week poutcome
          / param=ref ref=first order=formatted;

    /* Features:
       Continuous — age, campaign, was_contacted_before (binary flag for pdays),
         previous, and the five macro-economic indicators.
       NOTE: pdays itself is NOT listed here — was_contacted_before replaces it
         (see difference C in the header).  If you want pdays for a direct
         numerical comparison with Python, swap was_contacted_before for pdays.

       Class (categorical) — 10 variables; reference levels per table above. */
    model y(event='1') =
        age
        campaign
        was_contacted_before   /* replaces raw pdays; see header note C */
        previous
        emp_var_rate
        cons_price_idx
        cons_conf_idx
        euribor3m
        nr_employed
        job marital education default housing loan
        contact month day_of_week poutcome
        / link=logit lackfit;

    /* Training-set summary output — only appears in the Results tab, does not
       affect the score dataset.  Use this to inspect coefficients and model fit
       before scoring.  Key table to read: "Association of Predicted
       Probabilities and Observed Responses" (c-statistic = AUROC). */
run;


/* ============================================================================
   STEP 2 — Score the test set
   Mirrors: trained.model.predict_proba(X_test)[:, 1]  [python/04_model.py]

   INMODEL / SCORE NOTE:
   Using the saved model (work.lr_model from OUTMODEL above) to score a
   separate dataset is the SAS equivalent of .fit() on train then
   .predict_proba() on test — the coefficient estimates from STEP 1 are
   applied to the test-set predictors without re-fitting.

   SCORE OUTPUT VARIABLES:
   For a binary response y (levels 0 and 1) with EVENT='1', the SCORE
   statement adds these columns to the output:
     P_1  = P(y=1) = propensity score  <- what we want as p_hat
     P_0  = P(y=0) = 1 - P_1
     F_y  = predicted class (0 or 1) at 0.5 threshold
   We keep P_1 (renamed to p_hat) and drop the others.

   Verify: %put the min/max of p_hat — should be strictly in (0,1).
   ============================================================================ */

proc logistic inmodel=work.lr_model;
    score data=fulcrum.bank_test
          out=work.test_scored_raw;
run;

/* Rename P_1 → p_hat; drop scoring artefact columns. */
data fulcrum.bank_test_scored;
    set work.test_scored_raw(rename=(P_1=p_hat) drop=P_0 F_y);
    label p_hat = "Predicted probability of term deposit subscription";
run;

/* Verify p_hat is well-formed. */
proc means data=fulcrum.bank_test_scored min max mean stddev n nmiss noprint;
    var p_hat;
    output out=work.phat_check min=min_phat max=max_phat;
run;

data _null_;
    set work.phat_check;
    if min_phat < 0 or max_phat > 1 then
        put "ERROR: [FULCRUM] p_hat out of [0,1] bounds — check PROC LOGISTIC output";
    else
        put "NOTE- [FULCRUM] p_hat OK: min=" min_phat best8. " max=" max_phat best8.;
run;


/* ============================================================================
   STEP 3 — Model diagnostics (training set)
   These are printed to the Results tab; compare with python/04_model.py output.

   CONCORDANCE (c-statistic) = AUROC.  Already printed by PROC LOGISTIC above
   in the "Association of Predicted Probabilities" table.  Target: match Python
   roc_auc value from output/model_metrics.json within a few hundredths
   (regularisation will pull Python's c-statistic up slightly if the model
   was overfitting without it).

   HOSMER-LEMESHOW — see the calibration discussion below this step.
   The LACKFIT option in STEP 1 already generated this test.  Check:
     - HL chi-square p-value > 0.05 → no significant lack of fit per decile
     - Any decile where Obs Events >> Exp Events flags a miscalibrated range
   ============================================================================ */

/* Re-score training set for train-vs-test comparison diagnostics. */
proc logistic inmodel=work.lr_model;
    score data=fulcrum.bank_train out=work.train_scored_raw;
run;

data work.train_scored;
    set work.train_scored_raw(rename=(P_1=p_hat) drop=P_0 F_y);
run;

title "Diagnostic: train-set predicted probability distribution";
proc means data=work.train_scored mean stddev p5 p25 p50 p75 p95;
    var p_hat;
run;

title "Diagnostic: test-set predicted probability distribution";
proc means data=fulcrum.bank_test_scored mean stddev p5 p25 p50 p75 p95;
    var p_hat;
run;
title;


/* ── Confirm test scored dataset written ──────────────────────────────────── */
%macro assert_rowcount(ds=, expected=, label=);
    %local n;
    proc sql noprint;
        select count(*) into :n trimmed from &ds;
    quit;
    %if &n ne &expected %then
        %put ERROR: [FULCRUM ASSERTION FAILED] &label — expected &expected, found &n;
    %else
        %put NOTE- [FULCRUM] OK: &label — &n rows;
%mend assert_rowcount;

%assert_rowcount(ds=fulcrum.bank_test_scored, expected=6177, label=bank_test_scored)

%put NOTE- ;
%put NOTE- [FULCRUM 02_model.sas] Complete.;
%put NOTE-   fulcrum.bank_test_scored written with p_hat column.;
%put NOTE-   Inspect Results tab: c-statistic, Hosmer-Lemeshow, ROC, calibration plots.;
%put NOTE- ;

ods graphics off;
