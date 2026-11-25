-- 05_retention.sql
-- Business questions 6-11 (retention). Churn is formal line closure; lines close after 90 days of
-- inactivity, so the first closures in the data appear in May 2024 (a 4-month warm-up), and churn-rate
-- summaries below use May 2024 - Oct 2026.

-- @query q08_churn_rate_summary
-- Q6: overall monthly churn rate (customer-month weighted) and annualised equivalent.
SELECT SUM(churned)                                                        AS churned_customers,
       SUM(opening_base)                                                   AS opening_base_customer_months,
       ROUND(100.0 * SUM(churned) / SUM(opening_base), 3)                  AS avg_monthly_churn_pct,
       ROUND(100 * (1 - POWER(1 - SUM(churned)::numeric / SUM(opening_base), 12)), 1) AS annualised_churn_pct,
       ROUND(1 / (SUM(churned)::numeric / SUM(opening_base)), 1)           AS implied_avg_lifetime_months
FROM telco.v_monthly_kpis
WHERE month >= DATE '2024-05-01';

-- @query q09_churn_by_segment
-- Q7: which segments churn most? Average monthly churn = churned / opening-base customer-months in each group.
WITH cm AS (
    SELECT m.*, s.value_segment
    FROM telco.mv_customer_month m JOIN telco.v_customer_summary s USING (customer_id)
    WHERE m.month >= DATE '2024-05-01' AND s.value_segment NOT LIKE 'Unsegmented%'
)
SELECT dim, grp,
       SUM(is_churn_month::int)                                             AS churned,
       COUNT(*) FILTER (WHERE in_opening_base)                              AS base_customer_months,
       ROUND(100.0 * SUM(is_churn_month::int) / NULLIF(COUNT(*) FILTER (WHERE in_opening_base), 0), 2) AS monthly_churn_pct,
       RANK() OVER (PARTITION BY dim ORDER BY SUM(is_churn_month::int)::numeric
                                      / NULLIF(COUNT(*) FILTER (WHERE in_opening_base), 0) DESC) AS churn_rank_within_dim
FROM (
    SELECT 'customer_type' AS dim, customer_type AS grp, is_churn_month, in_opening_base FROM cm
    UNION ALL SELECT 'age_group', age_group, is_churn_month, in_opening_base FROM cm
    UNION ALL SELECT 'plan_type', plan_type, is_churn_month, in_opening_base FROM cm
    UNION ALL SELECT 'county', county, is_churn_month, in_opening_base FROM cm
    UNION ALL SELECT 'value_segment', value_segment, is_churn_month, in_opening_base FROM cm
) x
GROUP BY dim, grp
ORDER BY dim, monthly_churn_pct DESC;

-- @query q10_churn_by_tenure
-- Q8: how does tenure influence retention? Monthly churn hazard by tenure at the time of churn.
SELECT LEAST(tenure_months, 36)                                           AS tenure_month_capped_36,
       COUNT(*) FILTER (WHERE in_opening_base)                            AS base_customer_months,
       SUM(is_churn_month::int)                                           AS churned,
       ROUND(100.0 * SUM(is_churn_month::int) / NULLIF(COUNT(*) FILTER (WHERE in_opening_base), 0), 2) AS monthly_churn_pct
FROM telco.mv_customer_month
WHERE month >= DATE '2024-05-01'
GROUP BY 1 ORDER BY 1;

-- @query q11_cohort_retention_matrix
-- Q10: acquisition cohorts (Jan 2024 onwards) followed month by month.
-- retention_pct = cohort members active in month k / cohort size. NULL where month k is after Oct 2026.
WITH cohort AS (
    SELECT cohort_month, COUNT(DISTINCT customer_id) AS cohort_size
    FROM telco.mv_customer_month WHERE cohort_month >= DATE '2024-01-01'
    GROUP BY 1
), activity AS (
    SELECT cohort_month,
           (EXTRACT(YEAR FROM age(month, cohort_month)) * 12 + EXTRACT(MONTH FROM age(month, cohort_month)))::int AS k,
           COUNT(*) FILTER (WHERE is_active) AS active
    FROM telco.mv_customer_month WHERE cohort_month >= DATE '2024-01-01'
    GROUP BY 1, 2
), grid AS (
    SELECT c.cohort_month, c.cohort_size, k
    FROM cohort c CROSS JOIN generate_series(0, 24) AS k
)
SELECT g.cohort_month, g.cohort_size, g.k AS months_since_acquisition,
       CASE WHEN (g.cohort_month + make_interval(months => g.k))::date > DATE '2026-10-01' THEN NULL
            ELSE ROUND(100.0 * COALESCE(a.active, 0) / g.cohort_size, 1) END AS retention_pct
FROM grid g LEFT JOIN activity a USING (cohort_month, k)
ORDER BY g.cohort_month, g.k;

-- @query q12_retention_milestones
-- Q11: % of customers still active 1, 3, 6 and 12 months after acquisition, by acquisition quarter.
-- Only cohorts old enough to have reached each milestone are counted for that milestone.
WITH c AS (
    SELECT customer_id, cohort_month,
           BOOL_OR(is_active AND tenure_months = 1)  AS a1,
           BOOL_OR(is_active AND tenure_months = 3)  AS a3,
           BOOL_OR(is_active AND tenure_months = 6)  AS a6,
           BOOL_OR(is_active AND tenure_months = 12) AS a12
    FROM telco.mv_customer_month WHERE cohort_month >= DATE '2024-01-01'
    GROUP BY 1, 2
)
SELECT to_char(date_trunc('quarter', cohort_month), 'YYYY-"Q"Q')           AS acquisition_quarter,
       COUNT(*)                                                               AS customers,
       ROUND(100.0 * AVG(a1::int)  FILTER (WHERE cohort_month <= DATE '2026-09-01'), 1) AS active_after_1m_pct,
       ROUND(100.0 * AVG(a3::int)  FILTER (WHERE cohort_month <= DATE '2026-07-01'), 1) AS active_after_3m_pct,
       ROUND(100.0 * AVG(a6::int)  FILTER (WHERE cohort_month <= DATE '2026-04-01'), 1) AS active_after_6m_pct,
       ROUND(100.0 * AVG(a12::int) FILTER (WHERE cohort_month <= DATE '2025-10-01'), 1) AS active_after_12m_pct
FROM c GROUP BY 1 ORDER BY 1;

-- @query q13_activity_frequency
-- Customer frequency: share of observed months in which customers were active, and purchase frequency.
SELECT value_segment,
       ROUND(AVG(100.0 * active_months / months_observed), 1) AS pct_months_active,
       ROUND(AVG(avg_transactions), 1)                        AS avg_transactions_per_active_month
FROM telco.v_customer_summary
GROUP BY value_segment ORDER BY pct_months_active DESC;

-- @query q14_monthly_active_customers_by_type
-- Monthly active customers (MAU) by customer type, with each type's churn rate.
SELECT month, customer_type,
       COUNT(*) FILTER (WHERE is_active)                                  AS active_customers,
       ROUND(100.0 * COUNT(*) FILTER (WHERE is_churn_month)
             / NULLIF(COUNT(*) FILTER (WHERE in_opening_base), 0), 2)     AS churn_rate_pct
FROM telco.mv_customer_month
GROUP BY 1, 2 ORDER BY 1, 2;

-- @query q15_declining_customers
-- Q9/Q16: current customers whose activity is falling (Aug-Oct 2026 revenue < 50% of May-Jul 2026, or silent).
-- These are the customers to contact BEFORE the line is closed.
SELECT engagement_status, value_segment,
       COUNT(*)                                       AS customers,
       ROUND(SUM(rev_may_jul_2026) / 3, 0)            AS monthly_revenue_before_kes,
       ROUND(SUM(COALESCE(rev_aug_oct_2026, 0)) / 3, 0) AS monthly_revenue_now_kes,
       ROUND((SUM(rev_may_jul_2026) - SUM(COALESCE(rev_aug_oct_2026, 0))) / 3 * 12, 0) AS annualised_revenue_at_risk_kes
FROM telco.v_customer_summary
WHERE engagement_status IN ('Declining (>50% revenue drop)', 'Silent (no activity Aug-Oct)')
GROUP BY 1, 2
ORDER BY annualised_revenue_at_risk_kes DESC;
