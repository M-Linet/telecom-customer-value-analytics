# Methodology

All data in this project is **synthetic**, generated for the fictional operator *Jamii Mobile*. This document explains how the data was built, cleaned, validated and analysed, and which choices affect the results.

## 1. Why synthetic data
| Source reviewed | What it offers | Why it was not used directly |
|---|---|---|
| IBM Telco Customer Churn (IBM sample data; Kaggle mirror `blastchar/telco-customer-churn`) | 7,043 customers of a fictional California operator: tenure, contract, services, monthly charges, a churn flag | One snapshot with no monthly history (no cohorts, no MAU, no declining activity), no usage, complaints or campaigns, US home-phone and internet products, no published licence |
| Communications Authority of Kenya quarterly sector statistics | Real national totals (subscriptions, data, mobile money) | Aggregates only; used as context in the README |

No public dataset combines customer-level monthly history, prepaid bundles, complaints and campaigns for a Kenyan-style market. I therefore wrote `src/generate_data.py` (seed 2027) and kept real statistics strictly as labelled context.

## 2. How the data is generated
The generator simulates the business **month by month** from January 2024 to October 2026 (34 months):

- **Base and acquisition.** 13,000 customers exist at the start (acquired 2019–2023) and about 430 join each month, 28,496 in total. About 12% are postpaid.
- **Hidden archetypes.** Each customer gets one of five behaviours: youth data-heavy, voice-centric, mainstream balanced, business, low-value occasional. The archetype drives bundle choice, usage and spend. It is written only to `data/synthetic/raw/_truth_archetypes.csv` and never loaded into the database; its only use is to check the K-means extension afterwards.
- **Transactions and usage.** Bundle purchases, mobile-money fees and postpaid bills, with usage per customer-month. Bundle prices rise about 10% in July 2025 (management context given in the brief).
- **Churn process.** Each month a customer has a churn hazard driven by tenure, plan type (postpaid × 0.6), an unresolved complaint (× 3.0 for four months), slow resolution of more than 10 days (× 1.6), living in a poor-coverage county (Garissa, Kilifi, Turkana: × 1.35), the price change for low-value prepaid customers (× 1.9 for four months), and an accepted win-back offer (× 0.5). A churning customer first **declines** (spend × 0.6, then × 0.25), then goes **silent** for three months, and the operator closes the line after 90 days without activity. That makes closure dates lag real disengagement by about three months, as in a real prepaid business.
- **Campaigns.** Win-back offers go to declining customers (35% contacted, 30% accept, which stops the decline); upsell, data bonus and loyalty campaigns are sent at random.

I designed these mechanisms, so the broad direction of the findings is not a discovery. What the analysis has to do is **recover and size** them from messy records without being told they exist, and avoid the traps (wrong denominators, reverse causality, confounding, self-selection) that would give misleading numbers. The magnitudes in the report are measured from the data, not typed in.

## 3. Injected data-quality problems
| Table | Problem (injected count) | Rule | Result in the exception log |
|---|---|---|---|
| customers | exact duplicate rows (80) | keep one copy | 80 removed |
| customers | age group written `25 - 34` (300) | remove spaces | 264 standardised (36 fell on `55+`, which has no hyphen, so nothing changed) |
| customers | customer type case/whitespace variants (250) | map to `Prepaid`/`Postpaid` | 250 standardised |
| customers | acquisition year typed 2062 (12) | replace with first subscription start | 12 corrected, flagged `acquisition_date_corrected` |
| customers | missing county (854) | keep NULL, report as *Unknown* | 854 logged |
| transactions | exact duplicate rows (5,311) | keep one copy | 5,311 removed |
| transactions | service label variants (35,342 rows touched) | alias map; the build **fails** on an unmapped label | 32,509 changed (the rest were Postpaid Bill / SMS rows with no variant defined) |
| transactions | amount keyed × 1000 (30) | quarantine above the service's plausibility limit | 30 quarantined |
| transactions | customer ID not in master (45) | quarantine | 46 quarantined (one reversal was copied from an orphan row) |
| transactions | reversals with negative amounts (3,534) | move to `telco.reversals` | 3,533 moved (one is the orphan above) |
| usage_monthly | duplicate rows (1,120) | keep one copy | 1,120 removed |
| usage_monthly | negative data (25) and meter sentinel 999,999,999 (20) | set `data_mb` to NULL, keep the row | 45 nulled |
| complaints | resolution date before complaint date (30) | resolution date to NULL, status kept | 30 nulled |
| complaints | category (120) and status (90) case variants | standardise | 210 standardised |
| campaigns | missing response (710) | `Unknown` | 710 set |

Every difference between "injected" and "logged" is explained above; notebook 02 checks the exception log against `injection_manifest.json` programmatically.

**The rule I had to fix.** My first transaction rule quarantined only amounts above KES 25,000. Profiling amounts **per service** (`dq_a04b`) showed three mobile-money fees of KES 13,000–22,000: fees never exceed KES 95, so these were KES 13–22 fees keyed × 1000, too small to cross the general ceiling. The final rule uses a KES 1,000 limit for mobile-money fees and KES 25,000 for everything else, and catches all 30.

**Principle:** fix only what is certain, quarantine what would be a guess, log everything. Nothing is imputed.

## 4. Validation
- `dq_b01`: eight integrity checks (one open subscription per customer, no transactions before acquisition or after closure, no grid activity after churn, acquisition date = first subscription start, and others). All return 0.
- `dq_b02`: the customer-month grid carries every transaction and usage row exactly once (revenue in the grid = revenue in transactions).
- Primary-key uniqueness, `CHECK` constraints and foreign keys are enforced by PostgreSQL.
- The cohort retention matrix is computed independently in SQL (`q11`) and pandas (`analysis.retention_matrix`); they agree within 0.1 percentage points.
- The Power BI measures are checked against `powerbi/kpi_reconciliation.csv`.
- 33 pytest tests cover the cleaning rules, metric functions and database integrity.

## 5. Metric definitions
Fixed once in `sql/03_views.sql`:

| Metric | Definition | Why this way |
|---|---|---|
| Revenue | sum of purchase transactions; reversals excluded | refunds are tracked separately rather than silently netted |
| Subscribed base (month m) | lines open on day 1 of m | the churn denominator must be people who *could* churn that month |
| Active (month m) | any paid transaction or recorded usage in m | a customer using only free in-bundle minutes is still active |
| Monthly churn rate | lines closed in m ÷ subscribed base at the start of m | standard opening-base definition |
| Average churn | Σ churned ÷ Σ opening base over May 2024–Oct 2026 | customer-month weighted; months before May 2024 cannot show closures (the 90-day clock) |
| Annualised churn | 1 − (1 − monthly)^12 | compounding, not × 12 |
| ARPU | revenue in m ÷ active customers in m | dividing by all customers ever would understate ARPU |
| Cohort retention (c, k) | cohort *c* customers active in month *c + k* ÷ cohort size | fixed denominator; unobserved cells are NULL, not 0 |
| Value segment | decile of early monthly revenue (tenure months 1–3, or Jan–Mar 2024 for the opening base) | avoids reverse causality (see §6) |
| Declining | Aug–Oct 2026 revenue < 50% of May–Jul 2026, or no activity in Aug–Oct | a simple, explainable early-warning rule |
| Simple CLV | m × (1 + d) ÷ (d + churn), m = monthly revenue × margin, d = 1% monthly discount | shown as a range over 45/55/65% margins because margin is unknown |

## 6. Analytical choices that change the answer
1. **Early-spend segments.** Segmenting on lifetime average revenue ranks churners as low-value partly *because* they stopped spending before leaving. Using early spend fixes the segment before the outcome happens.
2. **Stratifying the complaint–churn link.** High-value customers complain more and churn less. Without stratification, complainers appear to churn *less* than non-complainers. `q18` compares complaint outcomes within value tiers, on a fixed population (customers subscribed on 1 January 2025), with exposure in Jan–Jun 2025 and outcome in Feb 2025–Mar 2026.
3. **Lag between disengagement and closure.** Because closure follows 90 days of silence, effects (such as the July 2025 price change) appear in closures about four months later. `q25` compares Mar–Oct 2025 with Nov 2025–Feb 2026 for that reason.
4. **Self-selection in win-back.** Customers who accept an offer differ from those who do not, so the accepted/not-accepted gap (`q22`) is not the effect of the offer.
5. **K-means *k*.** Silhouette is highest at *k* = 2, which only separates business postpaid users. *k* is restricted to 3–6 and chosen by silhouette within that range (*k* = 4), then interpreted against the value segments.

## 7. Limitations
- Synthetic data: the analysis demonstrates method, not facts about a real operator.
- Usage is monthly; within-month patterns and daily activity are invisible.
- No cost data: CLV uses an assumed margin range.
- Associations, not causes: complaints, coverage, price and campaign results are observational.
- Postpaid churn is low in absolute numbers (396 closures), so postpaid sub-group rates are noisy.
- County is missing for 3% of customers.
