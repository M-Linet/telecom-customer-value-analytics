# SQL query guide

This guide covers the 25 analytical queries and 10 data-quality queries. Each is listed with its business question, the SQL techniques it uses, and what the result showed. The SQL is in `sql/`, and the full result of every query is in `reports/sql_outputs/<name>.csv` (regenerate with `python -m src.run_sql`). All figures describe the **fictional** operator Jamii Mobile, built from synthetic data.

Technique key: **J** = joins · **A** = aggregation · **CW** = CASE WHEN · **F** = conditional aggregation (`FILTER`) · **CTE** · **SQ** = subquery · **W** = window function · **GS** = `generate_series` · **R** = `ROLLUP` · **P** = percentiles · **V** = semantic view

## Semantic layer (`03_views.sql`)
| View | Why it exists |
|---|---|
| `mv_customer_month` (materialized) | One row per customer per subscribed month (Jan 2024 – Oct 2026, 602,836 rows): revenue, transactions, usage, `is_active`, `in_opening_base`, `is_churn_month`, tenure and plan. Every churn, ARPU and retention metric reads from it, so they share one denominator. Built with `generate_series`. |
| `v_customer_summary` | One row per customer: early monthly revenue, value decile and segment (`NTILE` over customers with an early-revenue value), engagement status (Declining / Silent / Stable / Too new / Churned), complaints and open complaints. |
| `v_monthly_kpis` | One row per month: opening base, new, active, churned, revenue, ARPU and churn rate. |

## Data quality (`02_data_quality_checks.sql`)
Part A profiles the raw staging layer: `dq_a01` row counts against distinct keys (80 duplicate customers, 5,311 duplicate transactions, 1,120 duplicate usage rows), `dq_a02` label variants, `dq_a03` missing values, `dq_a04` amount bands, `dq_a04b` amount range **per service** (which exposed three mobile-money fees keyed × 1000 that a single ceiling missed), `dq_a05` usage anomalies, `dq_a06` date logic. Part B proves the clean layer: `dq_b01` runs eight integrity checks that must all return 0 (they do), `dq_b02` reconciles the customer-month grid with transactions and usage, and `dq_b03` summarises the exception log.

## Customer value (`04_customer_value.sql`)

**q01_headline_kpis**: *How big is the base, and is it growing?* CTE, W (`LAG` 12 months), V.
Result: October 2026: 19,182 active customers (+10.8% YoY), KES 17.9M revenue (+19.3%), ARPU KES 934.53 (+7.6%), opening base 20,186, 434 new customers, 280 closures.

**q02_monthly_kpi_trend**: *How do ARPU, the active base and revenue move over time?* CTE, W (`LAG`, 3-month moving average with `ROWS BETWEEN`), V.
Result: ARPU rose steadily from KES 679 (Jan 2024) to 935, with a 9.9% jump in July 2025, the month of the price change. Churn is zero until April 2024 because of the 90-day closure rule, then runs at 1.2–1.8% a month.

**q03_revenue_by_service**: *Which services drive revenue, and which are growing?* A, F, W (share of total).
Result: Postpaid Bill 33.6%, Data Bundle 26.3%, Combo 16.5%, Voice 13.7%, Mobile Money Fees 6.6%, SMS 3.3%. Year-2 growth is lowest for mobile-money fees (+12%), which were not part of the price change.

**q04_value_by_customer_group**: *Which groups generate the most revenue and highest ARPU?* A, F, W, UNION ALL, V.
Result: ages 25–34 bring 30% of revenue, but 35–44 have the highest ARPU (KES 946). Nairobi brings 24% of revenue.

**q05_value_segments**: *How concentrated is value?* A, W, V.
Result: Platinum (9.9% of customers) brings 36.4% of revenue; Bronze (39.4%) brings 15.6%. 72% of Platinum customers are postpaid. 42.6% of Bronze customers have churned during the window against 8.5% of Platinum.

**q06_value_by_tenure**: *How does value change with tenure?* CTE, CW, F, V.
Result: ARPU rises from KES 681 in months 0–2 to about 850 in months 12–23, then flattens. Monthly churn is highest at 3–11 months (2.2–2.3%) and lowest after 24 months (1.1%).

**q07_top_customers_by_county**: *Who are the three highest-value current customers in each county?* CTE, W (`RANK() OVER (PARTITION BY county)`), V.
Result: 39 rows (the top three in each of 13 county groups); almost all are Postpaid Business customers, a ready list for account management.

## Retention (`05_retention.sql`)

**q08_churn_rate_summary**: *What is the overall churn rate?* A, V.
Result: 8,156 closures over 532,454 opening-base customer-months = **1.532% a month**, 16.9% annualised, an implied average lifetime of about 65 months.

**q09_churn_by_segment**: *Which segments churn most?* J, CTE, F, W (`RANK` within each dimension), UNION ALL, V.
Result: prepaid 1.68% vs postpaid 0.55%; Prepaid Flex 1.86% (highest plan); Bronze 2.42% vs Platinum 0.41%; age 18–24 highest (1.73%); Garissa, Kilifi and Turkana highest counties (about 2%).

**q10_churn_by_tenure**: *How does tenure influence retention?* F, V.
Result: almost no closures before tenure month 4 (the 90-day rule), a peak of about 3.5% a month in months 4–6, then a gradual decline.

**q11_cohort_retention_matrix**: *How do acquisition cohorts retain month by month?* J, CTE, CW, F, GS, V.
Result: 34 cohorts × up to 25 months (850 cells); unobserved cells are NULL, not 0. Feeds the heatmap in notebook 05 and Power BI. Matches the pandas calculation within 0.1 points.

**q12_retention_milestones**: *What share is still active after 1, 3, 6 and 12 months?* CTE, F, V.
Result: about 97%, 90%, 83% and 71–74%. The 2025-Q3 cohort has the weakest 3-month retention (88.2%).

**q13_activity_frequency**: *How regularly are customers active?* A, V.
Result: Platinum customers are active in 97% of their months, Bronze in 81.7%.

**q14_monthly_active_customers_by_type**: *MAU and churn by customer type over time.* CTE, F, V.
Result: both types grow; postpaid churn never exceeds 0.85% a month, against 1.3–2.3% for prepaid.

**q15_declining_customers**: *Which current customers are declining?* A, V.
Result: 700 declining and 2 silent customers; KES 3.5M of annualised revenue already lost, KES 1.7M from Platinum and Gold.

## Customer experience (`06_customer_experience.sql`)

**q16_complaints_by_category**: *Which complaints occur most often?* A, W, SQ, V.
Result: network coverage 22.1% (3.9 per 1,000 subscriber-months), data speed 20.8%, billing 16.7%.

**q17_resolution_time**: *Which categories take longest, and how many are never resolved?* A, F, P (`PERCENTILE_CONT`).
Result: network coverage averages 12.8 days (median 10, 90th percentile 27) with 29.8% unresolved or escalated; billing and SIM issues are resolved in about 2.5 days.

**q18_complaints_and_churn**: *Is churn associated with unresolved complaints?* J, CTE, CW, R (`ROLLUP` over value tier), V.
Result: within each value tier, unresolved/escalated complainers churned 1.2–1.5× more than non-complainers; resolved complainers churned less. The `ROLLUP` total row shows why stratifying matters.

**q19_complaints_by_county**: *Which areas generate the most complaints?* CTE, F, V.
Result: Garissa 28.5, Kilifi 27.3, Turkana 26.9 complaints per 1,000 subscriber-months, about 1.8× other counties, driven by network and data-speed tickets.

**q20_complaints_by_segment**: *Do complaint patterns differ by value?* A, V.
Result: 45.9% of postpaid Platinum customers have complained at least once, against 25–34% elsewhere: high-value customers are the most demanding as well as the most loyal.

## Strategy (`07_strategy.sql`)

**q21_campaign_response**: *How do campaigns perform?* A, F.
Result: loyalty points 34.4% acceptance, win-back 29.5%, data bonus 24.0%, bundle upsell 11.8%.

**q22_winback_effect**: *Does a win-back offer change what happens next?* J, CW, F.
Result: 1.7% of acceptors vs 93.7% of non-acceptors closed within six months. The groups are self-selected, so this is not the offer's effect.

**q23_valuable_customers_at_risk**: *Which high-value customers should be contacted first?* CTE, W (`ROW_NUMBER` by revenue at risk), V.
Result: a ranked list of the 50 Platinum/Gold customers with the largest revenue decline, with plan, county and open complaints.

**q24_usage_growth**: *Where is engagement growing?* CW, F, V.
Result: data per active customer +25% (4,245 → 5,312 MB a month) Year 2 vs Year 1; voice −2%, SMS −10%; ARPU +16%.

**q25_price_change_churn**: *Did the July 2025 price change affect churn, and for whom?* J, CTE, CW, F, V.
Result: prepaid Bronze churn 2.37% → 3.62% (allowing for the four-month closure lag), then 2.15%; prepaid Silver 1.13% → 1.42%; little change for Platinum, Gold or postpaid.
