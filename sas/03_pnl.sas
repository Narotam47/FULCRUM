/* ============================================================================
   FULCRUM — Campaign Performance & P&L Analyser
   FILE      : 03_pnl.sas
   PURPOSE   : %FULCRUM_PNL macro — tertile P&L economics applied to the
               scored test set from 02_model.sas.  SAS port of
               src/pnl/engine.py  compute_tertile_metrics().
   CREATED   : 2026-09-07
   AUTHOR    : FULCRUM pipeline port — reconciliation against Python output

   ENVIRONMENT
   -----------
   Platform  : SAS OnDemand for Academics (browser SAS Studio)
   Modules   : Base SAS + SAS/STAT
   Prerequisite: Run 01_prep.sas then 02_model.sas first.

   USAGE
   -----
   %FULCRUM_PNL(
       cost_per_contact = 2.50,
       nim              = 0.015,
       tenor            = 1.0,
       retention        = 0.50
   )

   The avg_deposit_balance is not a macro parameter because it is the most
   sensitive assumption (rank-1 in docs/assumptions.md) and is fixed at the
   10,000 EUR point estimate documented there.  Changing it requires updating
   the FULCRUM_BALANCE constant inside the macro — a deliberate friction so
   the deck assumption register stays the single source of truth.

   PYTHON vs SAS MACRO IDIOM
   ---------------------------------------------------------------
   Python engine.py: a typed function that accepts an Assumptions dataclass.
     Parameters are Python objects — numbers with type enforcement (float),
     validated at call time by Assumptions.__post_init__ or the engine.
   SAS %FULCRUM_PNL: macro parameters are TEXT tokens, not typed values.
     They are substituted into the macro body before the code is compiled —
     equivalent to C preprocessor macros, not function arguments.
     Arithmetic is done with %sysevalf() (floating-point evaluation), not
     natively.  Type validation has to be done explicitly (%sysevalf checks
     whether the text evaluates to a number; %if ...le 0 catches negatives).
     A Python function signature documents the type; a SAS macro signature
     documents nothing — all the type commentary is in the header or comments.

   ECONOMICS (matching src/pnl/engine.py TertileMetrics exactly)
   ---------------------------------------------------------------
   revenue_per_conversion = avg_deposit_balance * nim * tenor
   mppc                   = response_rate * revenue_per_conversion
                            - cost_per_contact
   contact_cost           = contacts * cost_per_contact
   gross_profit_1yr       = responders * revenue_per_conversion - contact_cost
   roi_1yr                = gross_profit_1yr / contact_cost
   cpa                    = contact_cost / responders

   TERTILE ASSIGNMENT (matching Python tertile construction)
   ---------------------------------------------------------------
   Python: predicted probabilities ranked, cut into three equal-count groups
     labelled T1 High / T2 Medium / T3 Low (T1 = highest propensity).
   SAS: PROC RANK GROUPS=3 TIES=MEAN assigns 0 (lowest), 1, 2 (highest).
     We invert and label: rank 2 → T1 High, rank 1 → T2 Medium, rank 0 → T3.
   GROUPS=3 with TIES=MEAN is the closest SAS equivalent to pd.qcut with
     duplicates='drop' — tied p_hat values share the boundary rank.  With a
     continuous probability score, ties at exact tertile cuts are very rare.

   RUN LOG
   ----------------------------------------
   Date       | Operator | Git ref / note
   -----------+----------+----------------------------------------------------
   2026-09-07 | <name>   | Initial port

   ============================================================================ */


/* ── LIBNAME ──────────────────────────────────────────────────────────────── */
options dlcreatedir;
libname fulcrum "%sysget(HOME)/FULCRUM/sas";
%put NOTE- FULCRUM lib path: %sysfunc(pathname(fulcrum));


/* ============================================================================
   %FULCRUM_PNL macro definition
   ============================================================================ */

%macro FULCRUM_PNL(
    cost_per_contact = ,   /* EUR per outbound call; rank-5 sensitivity       */
    nim              = ,   /* Net interest margin (decimal); rank-2 sensitivity */
    tenor            = ,   /* Deposit tenor in years; rank-3 sensitivity       */
    retention        = ,   /* Rollover/retention rate (decimal); rank-4        */
    scored_ds        = fulcrum.bank_test_scored  /* override in unit tests */
);

/* ── Parameter presence check ─────────────────────────────────────────────── */
%if %superq(cost_per_contact) =  %then %do;
    %put ERROR: [FULCRUM_PNL] cost_per_contact is required;
    %return;
%end;
%if %superq(nim) =  %then %do;
    %put ERROR: [FULCRUM_PNL] nim is required;
    %return;
%end;
%if %superq(tenor) =  %then %do;
    %put ERROR: [FULCRUM_PNL] tenor is required;
    %return;
%end;
%if %superq(retention) =  %then %do;
    %put ERROR: [FULCRUM_PNL] retention is required;
    %return;
%end;

/* ── Parameter range validation ───────────────────────────────────────────── */
/* %sysevalf() converts macro text to floating-point for the comparison.
   This is necessary because %if in SAS does integer comparison by default
   (%eval); %sysevalf(..., boolean) returns 1 if the expression is true.
   Equivalent to Python's Assumptions.__post_init__ value guards.         */
%if %sysevalf(&cost_per_contact <= 0) %then %do;
    %put ERROR: [FULCRUM_PNL] cost_per_contact must be > 0; got &cost_per_contact;
    %return;
%end;
%if %sysevalf(&nim <= 0) or %sysevalf(&nim > 1) %then %do;
    %put ERROR: [FULCRUM_PNL] nim must be in (0, 1]; got &nim;
    %return;
%end;
%if %sysevalf(&tenor <= 0) %then %do;
    %put ERROR: [FULCRUM_PNL] tenor must be > 0; got &tenor;
    %return;
%end;
%if %sysevalf(&retention < 0) or %sysevalf(&retention > 1) %then %do;
    %put ERROR: [FULCRUM_PNL] retention must be in [0, 1]; got &retention;
    %return;
%end;

/* ── Prerequisite dataset ─────────────────────────────────────────────────── */
%if not %sysfunc(exist(&scored_ds)) %then %do;
    %put ERROR: [FULCRUM_PNL] &scored_ds not found — run 02_model.sas first;
    %return;
%end;

/* ── Fixed assumption ─────────────────────────────────────────────────────── */
/* avg_deposit_balance is not a macro parameter; see header for rationale.
   Rank-1 sensitivity — a 50% error moves revenue by +/-34.50 EUR/contact.
   Point estimate: 10,000 EUR.  Source: docs/assumptions.md.              */
%let FULCRUM_BALANCE = 10000;

/* ── Derived values ───────────────────────────────────────────────────────── */
/* %sysevalf() required for floating-point arithmetic in macro context.
   Python equivalent: Assumptions.revenue_per_conversion_eur property.    */
%let rev_per_conv = %sysevalf(&FULCRUM_BALANCE * &nim * &tenor);
%let ltv_per_conv = %sysevalf(&rev_per_conv * (1 + &retention));

%put NOTE- [FULCRUM_PNL] Assumptions: cost=&cost_per_contact NIM=&nim tenor=&tenor retention=&retention;
%put NOTE- [FULCRUM_PNL] Derived: rev_per_conv=&rev_per_conv  ltv_per_conv=&ltv_per_conv;


/* ── STEP 1: Assign tertiles by p_hat rank ────────────────────────────────── */
/* PROC RANK GROUPS=3 TIES=MEAN assigns integer group values 0, 1, 2.
   0 = lowest propensity (fewest predicted subscribers)
   2 = highest propensity

   Python equivalent: np.digitize / pd.qcut applied to model.predict_proba()
   scores before tertile P&L computation in src/pnl/engine.py.

   NOTE on TIES=MEAN: for a continuous probability score, ties at an exact
   tertile boundary are extremely rare (<0.1% of rows).  TIES=MEAN assigns
   tied observations the average of their tied ranks, then GROUPS=3 maps
   that to a group.  This produces the same result as Python's pd.qcut for
   nearly all rows.  Any row that PROC RANK places differently from pd.qcut
   due to a tie is at a tertile boundary and carries near-identical p_hat to
   its neighbours — its assignment to T2 vs T3 has negligible P&L impact. */
proc rank data=&scored_ds out=work.fulcrum_ranked groups=3 ties=mean;
    var p_hat;
    ranks tertile_rank;   /* 0=low, 1=mid, 2=high */
run;

/* Assign labels.  Inverting the rank order so T1 is highest propensity
   matches Python engine.py convention (T1 High / T2 Medium / T3 Low).   */
data work.fulcrum_tertiled;
    set work.fulcrum_ranked;
    length tertile $10;
    select (tertile_rank);
        when (2) tertile = 'T1 High';
        when (1) tertile = 'T2 Medium';
        when (0) tertile = 'T3 Low';
        otherwise tertile = 'Unknown';
    end;
    label tertile = "Propensity tertile (T1=highest)";
run;


/* ── STEP 2: Aggregate contacts and responders per tertile ─────────────────── */
/* Python equivalent: compute_tertile_metrics() in src/pnl/engine.py,
   which receives contacts and responders counts per TertileInput.

   SAS: PROC MEANS with CLASS produces one summary row per tertile.
   N= gives contacts (all rows in tertile).
   SUM= gives responders (sum of binary y = subscriptions).
   MEAN= gives response rate (mean of binary y).                          */
proc means data=work.fulcrum_tertiled noprint;
    class tertile;
    var y;
    output out=work.tertile_agg(where=(_type_=1))
        n   = contacts
        sum = responders
        mean= response_rate;
run;

/* NOTE on _type_: PROC MEANS with CLASS outputs _TYPE_=0 (overall) and
   _TYPE_=1 (per-class).  WHERE _TYPE_=1 keeps only the per-tertile rows.
   This is a SAS idiom with no direct Python equivalent — pandas groupby()
   only produces the per-group rows, not the overall row.                  */


/* ── STEP 3: Compute economics ────────────────────────────────────────────── */
/* Matching TertileMetrics fields from src/pnl/engine.py exactly.
   Macro variable references (&rev_per_conv etc.) are text substitution —
   they expand to the numeric strings computed by %sysevalf above before
   the DATA step compiles.                                                  */
data work.tertile_pnl;
    set work.tertile_agg;

    /* Sort key for consistent output order (T1, T2, T3). */
    select (tertile);
        when ('T1 High')   sort_key = 1;
        when ('T2 Medium') sort_key = 2;
        when ('T3 Low')    sort_key = 3;
        otherwise          sort_key = 9;
    end;

    /* Economics — see ECONOMICS section in header. */
    contact_cost_eur         = contacts * &cost_per_contact;
    revenue_1yr_eur          = responders * &rev_per_conv;
    gross_profit_1yr_eur     = revenue_1yr_eur - contact_cost_eur;
    roi_1yr                  = gross_profit_1yr_eur / contact_cost_eur;
    cpa_eur                  = contact_cost_eur / max(responders, 1e-9);
    /* Marginal profit per contact — the sequencing metric.
       Python: TertileMetrics.marginal_profit_per_contact_eur
               = response_rate * revenue_per_conversion - cost_per_contact */
    mppc_eur = response_rate * &rev_per_conv - &cost_per_contact;

    format
        contacts       comma8.
        responders     comma8.
        response_rate  percent7.1
        contact_cost_eur revenue_1yr_eur gross_profit_1yr_eur
                       eurox10.2
        roi_1yr        8.1
        cpa_eur mppc_eur
                       8.2;
    label
        contacts           = "Contacts (n)"
        responders         = "Responders (n)"
        response_rate      = "Response rate"
        contact_cost_eur   = "Contact cost (EUR)"
        revenue_1yr_eur    = "Revenue 1yr (EUR)"
        gross_profit_1yr_eur= "Gross profit 1yr (EUR)"
        roi_1yr            = "ROI 1yr (x)"
        cpa_eur            = "Cost per acquisition (EUR)"
        mppc_eur           = "Marginal profit per contact (EUR)";
run;

proc sort data=work.tertile_pnl out=work.tertile_pnl;
    by sort_key;
run;


/* ── STEP 4: Print results to the log ────────────────────────────────────────
   Python equivalent: engine.print_tertile_table() in src/pnl/engine.py.

   DATA _NULL_ with PUT statements gives full control over log formatting.
   This is the SAS idiom for "print to log without creating a dataset" —
   there is no direct Python equivalent since Python print() is equivalent
   to SAS's PUT in a DATA step (both write to stdout / the execution log).  */
data _null_;
    /* Print header once before the loop. */
    if _n_ = 1 then do;
        put " ";
        put "═══════════════════════════════════════════════════════════════════════════════";
        put "  FULCRUM — Tertile P&L Summary  (SAS port of src/pnl/engine.py)";
        put "  Assumptions: cost=&cost_per_contact EUR  NIM=&nim  tenor=&tenor yr  retention=&retention";
        put "  avg_deposit_balance=&FULCRUM_BALANCE EUR  rev_per_conv=&rev_per_conv EUR";
        put "═══════════════════════════════════════════════════════════════════════════════";
        put "  Tertile      Contacts  Resp   Rate%     CPA€    Profit 1yr€    MPPC€    ROI";
        put "  ─────────────────────────────────────────────────────────────────────────";
    end;

    set work.tertile_pnl end=last;

    /* Format each row. */
    put "  " tertile $10.
        contacts     7.0 "  "
        responders   6.0 "  "
        @44 response_rate percent6.1
        @52 cpa_eur       8.2
        @62 gross_profit_1yr_eur comma12.0
        @76 mppc_eur      8.2
        @86 roi_1yr       6.1 "x";

    if last then do;
        put "  ─────────────────────────────────────────────────────────────────────────";
        put " ";
        put "  MPPC = marginal profit per contact — the budget sequencing metric.";
        put "  Rank: T1 (highest MPPC) > T2 > T3.  Greedy fill T1→T2→T3 is optimal.";
        put "  T1/T2 CIs overlap → treat as one priority tier for budget allocation.";
        put "  T2/T3 gap is the real budget decision point (src/pnl/engine.py).";
        put "═══════════════════════════════════════════════════════════════════════════════";
        put " ";
    end;
run;

/* Also write to Results tab for tabular view. */
title "FULCRUM — Tertile P&L (cost=&cost_per_contact NIM=&nim tenor=&tenor)";
proc print data=work.tertile_pnl label noobs;
    var tertile contacts responders response_rate cpa_eur
        gross_profit_1yr_eur mppc_eur roi_1yr;
run;
title;

%put NOTE- [FULCRUM_PNL] Macro complete. Check SAS log and Results tab.;

%mend FULCRUM_PNL;


/* ============================================================================
   Example call — point estimates from config/pnl_assumptions.yml
   This call replicates the Python engine output shown in the deck:
     T1 High:   ~46.1% response, ROI ~26.7x, CPA ~5.42 EUR
     T2 Medium: ~42.0% response, ROI ~24.2x, CPA ~5.95 EUR
     T3 Low:    ~27.3% response, ROI ~15.4x, CPA ~9.16 EUR
   NOTE: SAS values will differ from Python because of the regularisation
   and pdays/was_contacted_before differences documented in 02_model.sas.
   The RANK ORDER of tertiles and direction of all effects should agree.
   ============================================================================ */

%FULCRUM_PNL(
    cost_per_contact = 2.50,
    nim              = 0.015,
    tenor            = 1.0,
    retention        = 0.50
)


/* ============================================================================
   Sensitivity sweep — match python/06_sensitivity.py at the point estimates
   Vary one assumption at a time to verify the macro accepts the full range
   documented in docs/assumptions.md.
   ============================================================================ */

/* NIM low and high ends (range 0.0075 – 0.025, sourced to ECB MFI stats). */
%FULCRUM_PNL(cost_per_contact=2.50, nim=0.0075, tenor=1.0, retention=0.50)
%FULCRUM_PNL(cost_per_contact=2.50, nim=0.025,  tenor=1.0, retention=0.50)

/* Cost low and high ends (range 1.50 – 4.50, illustrative). */
%FULCRUM_PNL(cost_per_contact=1.50, nim=0.015,  tenor=1.0, retention=0.50)
%FULCRUM_PNL(cost_per_contact=4.50, nim=0.015,  tenor=1.0, retention=0.50)
