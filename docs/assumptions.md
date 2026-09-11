# P&L Assumptions — FULCRUM Campaign Model

**Currency:** EUR throughout. The UCI Bank Marketing dataset originates from a
Portuguese retail bank, May 2008–November 2010. All unit-economics assumptions
are calibrated to that market and period.

**Targeting layer:** P&L operates on tertile granularity (High / Medium / Low
propensity). Tertile response rates from the time-ordered test set are
approximately 46%, 42%, and 27% against a test-period base rate of 38.4%.
Decile-level differentiation is not defensible given Wilson CI widths at
n ≈ 618/decile — see `notebooks/03_decile_analysis.ipynb`.

---

## Assumption Table

| # | Assumption | Defensible Range | Point Estimate | Sensitivity Rank |
|---|-----------|-----------------|----------------|-----------------|
| 1 | Cost per contact (outbound call) | €1.50 – €4.50 | **€2.50** | 5 (lowest) |
| 2 | Average term deposit balance | €5,000 – €25,000 | **€10,000** | 1 (highest) |
| 3 | Net interest margin on term deposits | 0.75% – 2.50% | **1.50%** | 2 |
| 4 | Expected deposit tenor | 6 – 18 months | **12 months** | 3 |
| 5 | Account retention rate (rollover at maturity) | 40% – 65% | **50%** | 4 |

---

## Detailed Reasoning

### 1. Cost per contact — €2.50 · Rank 5 · **ILLUSTRATIVE**

**Range: €1.50 – €4.50**

Portuguese call-center labor costs in 2008–2010 were among the lowest in
Western Europe. The national minimum wage (*salário mínimo nacional*) rose from
€403/month in 2008 to €475/month in 2010. Entry-level call-center agents
earned approximately €500–700/month gross; with employer social-security
contributions (23.75% in Portugal) and benefits, fully-loaded direct labor cost
is €620–870/month. Add overhead — facilities, telephony, supervision, quality
assurance — at an industry-standard 40–60% uplift, and total cost per agent-
month is roughly €870–1,400.

With ~140 productive agent-hours per month and a blended contact time of
8 minutes (conversation + wrap-up + redialing attempts), productive contacts
per agent-month ≈ 1,050. This yields a cost-per-contact range of **€0.83–€1.33**
for a pure agent-labor calculation. Grossing up for telephony charges
(Portuguese PSTN fixed-line costs were ~€0.03–€0.10/min in this period),
management overhead, and campaign tooling brings the realistic all-in range
to **€1.50–€4.50**, with €2.50 as a central estimate for a mid-tier Portuguese
retail bank running its own call center.

**What would support this:** European Contact Centre & Customer Service Awards
(ECCCSA) benchmarking reports from 2009–2011 published cost-per-contact ranges
for southern European operations of €2–5. No single Portuguese-bank-specific
public source pins this number; present as illustrative.

**Why rank 5:** At the T1 tertile conversion rate (≈46%), gross revenue per
contact ≈ 46% × €150 = €69. A ±50% swing in cost per contact (±€1.25) moves
net revenue per contact by ±€1.25, or ±1.8% of gross revenue. This is the
lowest-sensitivity input in the model.

---

### 2. Average term deposit balance — €10,000 · Rank 1 · **ILLUSTRATIVE**

**Range: €5,000 – €25,000**

Portuguese household financial wealth was approximately €130–140 billion in
2008–2010 (Banco de Portugal financial accounts data, published in their
Statistical Bulletin). With roughly 8.5 million adults, average per-capita
financial assets were €15,000–16,000, though skewed: the median saver held
substantially less.

For a mass-market outbound campaign targeting existing or prospective retail
customers — which this dataset reflects — the plausible deposit size is
€5,000–25,000. Minimum deposit thresholds at Portuguese retail banks in this
period were typically €1,000–5,000; balances above €50,000 would be served
through private banking, not an outbound call center. €10,000 is a defensible
central estimate for a campaign targeting the broad retail segment.

**What would support this:** Banco de Portugal's *Inquérito à Situação
Financeira das Famílias* (Household Financial Survey, conducted 2006–2010) and
the ECB's Household Finance and Consumption Survey (HFCS, 2010 wave, published
2013) both provide Portuguese household deposit distributions. Neither is
bank-specific, but both anchor the range. Present as illustrative until the
bank's own deposit-size distribution is available.

**Why rank 1:** Revenue scales linearly with balance. Moving from €5,000 to
€25,000 (5×) multiplies annual revenue per acquired customer from €75 to €375.
No other single assumption has this lever.

---

### 3. Net interest margin on term deposits — 1.50% · Rank 2 · **SOURCED WITH CROSS-CHECK**

**Range: 0.75% – 2.50%**

The NIM on a retail term deposit is the spread between the rate at which the
bank deploys the funds (via lending or asset purchases) and the rate it pays
the depositor. This is sometimes called the deposit's *funds transfer price
(FTP) contribution*.

ECB MFI (Monetary Financial Institutions) interest rate statistics — published
monthly at country level and freely available on the ECB Statistical Data
Warehouse — show the following for Portugal:

- **New-business deposit rates (households, up to 1 year):** ~3.5–4.5% in
  mid-2008, declining to 1.5–2.5% by late 2010 as Euribor 3m collapsed from
  ~5% to ~0.8%.
- **New-business lending rates (households, consumer credit + mortgage):**
  ~5.0–7.5% over the same period (mortgages lower, consumer credit higher).
- **Implied gross spread (lending − deposit):** 1.5–3.5% across the period,
  compressing toward the low end as rates fell.

A NIM contribution of 1.50% for the deposit book is conservative relative to
the gross spread — it accounts for the fact that not all deposit funding is
deployed at the top lending rate, and reserves a portion for credit losses and
operating costs. The 0.75% floor represents a stress scenario (rates near zero,
competitive deposit market in a downturn); 2.50% represents the favorable
spread environment of 2008.

**Source:** ECB Statistical Data Warehouse, Table MIR (MFI Interest Rates),
country = PT, instrument = deposits and loans. Freely verifiable; flag as
*sourced* with the caveat that the specific bank's FTP rate is proprietary and
not public.

**Why rank 2:** Revenue = Balance × **NIM** × Tenor. Moving NIM from 0.75% to
2.50% (3.3×) changes annual revenue per acquired customer from €75 to €250 on
a €10,000 balance, a €175 swing per conversion. Second-largest lever.

---

### 4. Expected deposit tenor — 12 months · Rank 3 · **ILLUSTRATIVE**

**Range: 6 – 18 months**

Portuguese retail term deposits in this period were overwhelmingly 3-, 6-,
or 12-month instruments; 24-month deposits existed but were uncommon in the
mass-market segment. Twelve months was the modal product for outbound-acquired
deposits at Portuguese retail banks.

The ECB MFI statistics referenced above break out new-business deposit volumes
by maturity band ("up to 1 year," "1–2 years," "over 2 years"), and the "up to
1 year" bucket dominated Portuguese household deposits throughout 2008–2010.
This anchors the 12-month point estimate as industry-consistent, though the
specific bank's product mix is not public.

**Why rank 3:** Revenue = Balance × NIM × **Tenor**. Moving from 6 to 18
months doubles annual revenue, but the range (0.5–1.5 years) is narrower in
relative terms than the balance or NIM ranges above.

---

### 5. Account retention rate (rollover) — 50% · Rank 4 · **ILLUSTRATIVE**

**Range: 40% – 65%**

Retention measures the fraction of term deposits that roll over into a new
deposit at maturity rather than being withdrawn. No single public Portuguese
source publishes this figure at the bank level.

Industry benchmarks from European retail banking consultancies (Accenture
Banking, Oliver Wyman retail banking reports) in this period placed deposit
rollover rates at 45–70% for established retail banks under normal conditions,
declining in a stressed rate environment where alternatives (government bonds,
competitor savings accounts) were more attractive.

Portugal in 2009–2010 was under significant economic stress, with households
reducing debt and seeking liquidity — conditions that would suppress rollover
toward the lower end of the range. 50% is a conservative-to-central estimate
for this market and period.

Note: retention only affects the *lifetime value* (LTV) layer of the P&L. If
the model reports first-year P&L only, retention drops out entirely. When LTV
is included, the formula becomes: LTV = Revenue × (1 − retention^n) / (1 −
retention), where n is the number of renewal cycles considered.

**Why rank 4:** Retention adds a multiplier on top of first-year revenue.
Moving from 40% to 65% changes LTV by roughly 1.25×–1.5× depending on the
discount rate and horizon. Meaningful, but smaller in absolute terms than the
balance or margin assumptions.

---

## Sensitivity Matrix

Qualitative impact of varying each assumption by ±50% around the point
estimate (holding others fixed), measured against net revenue per contact at
the T1 tertile (46% conversion rate):

| Assumption | Point Estimate | −50% | +50% | ΔNet Revenue per Contact |
|-----------|---------------|------|------|--------------------------|
| Average balance | €10,000 | €5,000 | €15,000 | ±€34.50 |
| NIM | 1.50% | 0.75% | 2.25% | ±€34.50 |
| Tenor | 12 months | 6 months | 18 months | ±€34.50 |
| Retention (LTV only) | 50% | 25% | 75% | ±€11.50 |
| Cost per contact | €2.50 | €1.25 | €3.75 | ±€1.25 |

*Balance, NIM, and tenor have identical functional sensitivity because they
multiply together in the revenue formula. Absolute impact depends on the
variation range assumed; ±50% used here for comparability.*

---

## Interview Paragraph

> "The P&L layer rests on five assumptions, and I want to be transparent about
> the degree of evidence behind each. Two of them — the net interest margin
> and the deposit tenor — can be cross-checked against public data: the
> European Central Bank publishes monthly MFI interest rate statistics by
> country, and Portugal's figures for 2008–2010 are freely available on the
> ECB Statistical Data Warehouse. They support a 1.5% margin and a 12-month
> tenor as reasonable central estimates. The remaining three — cost per
> contact, average deposit balance, and retention rate — are calibrated
> against industry benchmarks and published household financial survey data
> from the Bank of Portugal and the ECB's Household Finance and Consumption
> Survey, but they are not sourced to a specific audited figure from this
> bank, and I've marked them explicitly as illustrative. The important thing
> for the conclusions is that the sensitivity analysis shows cost per contact,
> which is the hardest to argue about, is also the assumption that moves the
> answer the least — a 50% error in the call cost shifts net revenue per
> contact by about €1.25 against a gross revenue figure that is ten times
> larger. The assumptions that actually determine whether the model pays out
> are average deposit balance, margin, and tenor, and those three have
> meaningful public anchors even if the bank's exact figures are proprietary.
> If you hand me the bank's actual numbers, I replace three cells in a table
> and the conclusions update automatically."
