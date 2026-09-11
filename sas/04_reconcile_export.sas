/* ============================================================================
   FULCRUM — Campaign Performance & P&L Analyser
   FILE      : 04_reconcile_export.sas
   PURPOSE   : Export SAS model outputs to CSV for reconciliation with Python.
               Mirrors python/07_reconcile_export.py — writes four CSVs to
               data/reconciliation/sas_outputs/ in the ODA home directory.
               python/08_reconcile.py then reads both directories.
   CREATED   : 2026-09-07
   AUTHOR    : FULCRUM pipeline port — reconciliation against Python output

   PREREQUISITES
   -------------
   Run in order:  01_prep.sas  →  02_model.sas  →  03_pnl.sas  →  this file.
   This script re-fits PROC LOGISTIC (same spec as 02_model.sas) to capture
   the ODS ParameterEstimates table.  The estimate values are identical to
   02_model.sas because the data and model spec are unchanged.

   OUTPUT FILES  (all in %sysget(HOME)/FULCRUM/data/reconciliation/sas_outputs/)
   -------------------------------------------------------------------------------
   coef_table.csv          Variable, ClassVal0, Estimate, StdErr
   tertile_boundaries.csv  tertile, p_hat_min, p_hat_max, p_hat_mean
   tertile_rates.csv       tertile, contacts, responders, response_rate
   tertile_pnl.csv         tertile, mppc_eur, gross_profit_1yr_eur, roi_1yr, cpa_eur

   WHAT 08_reconcile.py DOES WITH THESE FILES
   -------------------------------------------
   It joins coef_table.csv by normalized feature name:
     SAS  canonical name = Variable + "_" + ClassVal0 (where not missing)
     Python canonical name = raw get_dummies column name
     Both normalized: lowercase, spaces/dots/hyphens → underscores.
   It compares tertile rates and MPPC against the Python counterparts.
   Pass/fail is reported against stated tolerances.

   RUN LOG
   ----------------------------------------
   Date       | Operator | Git ref / note
   -----------+----------+----------------------------------------------------
   2026-09-07 | <name>   | Initial reconciliation export

   ============================================================================ */


/* ── LIBNAME and output path ─────────────────────────────────────────────── */
options dlcreatedir;
libname fulcrum "%sysget(HOME)/FULCRUM/sas";
%put NOTE- FULCRUM lib: %sysfunc(pathname(fulcrum));

%let sas_out = %sysget(HOME)/FULCRUM/data/reconciliation/sas_outputs;
options dlcreatedir;
libname sasr "&sas_out";   /* dlcreatedir creates the directory */
%put NOTE- SAS reconciliation output path: &sas_out;


/* ── Prerequisites check ─────────────────────────────────────────────────── */
%macro check(ds=,step=);
    %if not %sysfunc(exist(&ds)) %then %do;
        %put ERROR: &ds not found — run &step first;
        %abort cancel;
    %end;
%mend;

%check(ds=fulcrum.bank_train,       step=01_prep.sas)
%check(ds=fulcrum.bank_test_scored, step=02_model.sas)


/* ============================================================================
   STEP 1 — Re-fit PROC LOGISTIC and capture ODS ParameterEstimates
   The ODS OUTPUT statement captures the parameter table that PROC LOGISTIC
   normally only prints to the Results tab.  Re-fitting here (vs reading from
   work.lr_model) is necessary because PROC LOGISTIC with INMODEL does not
   re-emit the ParameterEstimates ODS table.

   ODS ParameterEstimates table columns we keep:
     Variable  : variable name (CLASS variable name, or continuous var name,
                 or "Intercept")
     ClassVal0 : for CLASS levels, the category value (e.g., "blue-collar")
                 for non-CLASS rows, this column is blank/missing
     Estimate  : MLE coefficient
     StdErr    : standard error of the estimate

   python/08_reconcile.py builds the canonical feature name as:
     Variable + "_" + ClassVal0   (when ClassVal0 is non-blank)
     Variable                     (when ClassVal0 is blank)
   and then normalises by lowercasing and replacing spaces, dots, hyphens
   with underscores.  This produces names comparable to Python's
   pd.get_dummies column names (also normalised the same way).
   ============================================================================ */

ods output ParameterEstimates=work.coef_raw;

proc logistic data=fulcrum.bank_train;

    class job marital education default housing loan
          contact month day_of_week poutcome
          / param=ref ref=first order=formatted;

    /* Identical model spec to 02_model.sas.  See that file's header for
       the full reference-level table and structural differences vs Python. */
    model y(event='1') =
        age
        campaign
        was_contacted_before
        previous
        emp_var_rate
        cons_price_idx
        cons_conf_idx
        euribor3m
        nr_employed
        job marital education default housing loan
        contact month day_of_week poutcome
        / link=logit;

run;

ods output close;

/* Keep only the columns needed for reconciliation. */
data work.coef_sas;
    set work.coef_raw;
    keep Variable ClassVal0 Estimate StdErr;
    /* Rename to lowercase for CSV compatibility with the Python reader. */
    rename Variable=variable ClassVal0=class_val Estimate=estimate StdErr=std_err;
run;

/* Export. */
proc export data=work.coef_sas
    outfile="&sas_out/coef_table.csv"
    dbms=csv replace;
run;

%put NOTE- [FULCRUM] Exported: coef_table.csv (%left(%trim(
    %sysfunc(attrn(%sysfunc(open(work.coef_sas)),nobs)))) rows);


/* ============================================================================
   STEP 2 — Assign tertiles and compute p_hat boundaries
   Mirrors python/07_reconcile_export.py proc_rank_groups() exactly:
     PROC RANK GROUPS=3 TIES=MEAN is the reference implementation;
     the Python function mimics its formula  floor((rank-1)*g/n).
   Any difference here is a real grouping-rule inconsistency, not a model diff.
   ============================================================================ */

proc rank data=fulcrum.bank_test_scored out=work.test_ranked groups=3 ties=mean;
    var p_hat;
    ranks tertile_rank;   /* 0=lowest propensity, 2=highest */
run;

data work.test_tertiled;
    set work.test_ranked;
    length tertile $10;
    select (tertile_rank);
        when (2) tertile = 'T1 High';
        when (1) tertile = 'T2 Medium';
        when (0) tertile = 'T3 Low';
        otherwise tertile = 'Unknown';   /* should never fire */
    end;
run;

/* Tertile p_hat boundaries. */
proc means data=work.test_tertiled noprint;
    class tertile;
    var p_hat;
    output out=work.bounds_raw(where=(_type_=1))
        min(p_hat)  = p_hat_min
        max(p_hat)  = p_hat_max
        mean(p_hat) = p_hat_mean;
run;

data work.tertile_bounds;
    set work.bounds_raw;
    keep tertile p_hat_min p_hat_max p_hat_mean;
run;

proc export data=work.tertile_bounds
    outfile="&sas_out/tertile_boundaries.csv"
    dbms=csv replace;
run;

%put NOTE- [FULCRUM] Exported: tertile_boundaries.csv;


/* ============================================================================
   STEP 3 — Tertile response rates
   Mirrors 03_pnl.sas PROC MEANS step.  Computing separately here (rather
   than reusing work.tertile_agg from the macro) so this script is
   self-contained and does not depend on the macro having been run.
   ============================================================================ */

proc means data=work.test_tertiled noprint;
    class tertile;
    var y;
    output out=work.rates_raw(where=(_type_=1))
        n(y)    = contacts
        sum(y)  = responders
        mean(y) = response_rate;
run;

data work.tertile_rates;
    set work.rates_raw;
    keep tertile contacts responders response_rate;
run;

proc export data=work.tertile_rates
    outfile="&sas_out/tertile_rates.csv"
    dbms=csv replace;
run;

%put NOTE- [FULCRUM] Exported: tertile_rates.csv;


/* ============================================================================
   STEP 4 — P&L economics per tertile
   Uses the same point-estimate assumptions as config/pnl_assumptions.yml.
   These values are also used by python/07_reconcile_export.py via
   src/pnl/engine.py load_assumptions().  If the assumptions config changes,
   update these macro variables to match.

   Point estimates (docs/assumptions.md):
     avg_deposit_balance_eur : 10,000  (rank-1 sensitivity)
     net_interest_margin     :  0.015  (rank-2; sourced to ECB MFI Table MIR PT)
     deposit_tenor_yrs       :  1.0    (rank-3)
     cost_per_contact_eur    :  2.50   (rank-5)
     retention_rate          :  0.50   (rank-4; LTV only — zero 1yr ROI impact)
   ============================================================================ */

%let balance  = 10000;
%let nim      = 0.015;
%let tenor    = 1.0;
%let cost     = 2.50;
/* retention not needed for 1yr P&L */

%let rev = %sysevalf(&balance * &nim * &tenor);   /* 150 EUR */

data work.tertile_pnl;
    set work.tertile_rates;

    /* Economics — matching TertileMetrics fields from src/pnl/engine.py. */
    contact_cost_eur         = contacts * &cost;
    revenue_1yr_eur          = responders * &rev;
    gross_profit_1yr_eur     = revenue_1yr_eur - contact_cost_eur;
    roi_1yr                  = gross_profit_1yr_eur / contact_cost_eur;
    cpa_eur                  = contact_cost_eur / max(responders, 1e-9);
    mppc_eur                 = response_rate * &rev - &cost;

    keep tertile mppc_eur gross_profit_1yr_eur roi_1yr cpa_eur response_rate;
run;

proc export data=work.tertile_pnl
    outfile="&sas_out/tertile_pnl.csv"
    dbms=csv replace;
run;

%put NOTE- [FULCRUM] Exported: tertile_pnl.csv;


/* ── Summary ─────────────────────────────────────────────────────────────── */
title "SAS Reconciliation Export — Tertile Summary";
proc print data=work.tertile_pnl noobs label;
    var tertile response_rate mppc_eur gross_profit_1yr_eur roi_1yr cpa_eur;
    format response_rate percent7.2 mppc_eur gross_profit_1yr_eur cpa_eur comma10.2 roi_1yr 8.2;
run;
title;

%put NOTE- ;
%put NOTE- [FULCRUM 04_reconcile_export.sas] Complete.;
%put NOTE-   4 CSVs written to: &sas_out;
%put NOTE-   Next: run python/08_reconcile.py from the FULCRUM project root.;
%put NOTE- ;
