-- 04_customer_value.sql
-- Business questions 1-5 (customer value). Definitions: sql/03_views.sql.

-- @query q01_headline_kpis
-- Q1-2: subscriber base, revenue and ARPU at the latest month, with the same month a year earlier.
SELECT month, opening_base, active_customers, new_customers, churned, revenue, arpu, churn_rate_pct,
       ROUND(100 * (revenue / LAG(revenue, 12) OVER (ORDER BY month) - 1), 2)          AS revenue_yoy_pct,
       ROUND(100 * (arpu / LAG(arpu, 12) OVER (ORDER BY month) - 1), 2)                AS arpu_yoy_pct,
       ROUND(100 * (active_customers::numeric / LAG(active_customers, 12) OVER (ORDER BY month) - 1), 2) AS active_yoy_pct
FROM telco.v_monthly_kpis
ORDER BY month DESC
LIMIT 1;

-- @query q02_monthly_kpi_trend
-- Q2: ARPU, active base and revenue over time, with month-over-month change and a 3-month rolling churn rate.
SELECT month, active_customers, revenue, arpu,
       ROUND(100 * (arpu / LAG(arpu) OVER (ORDER BY month) - 1), 2)                     AS arpu_mom_pct,
       churn_rate_pct,
       ROUND(100.0 * SUM(churned) OVER w / NULLIF(SUM(opening_base) OVER w, 0), 3)     AS churn_rate_3m_pct
FROM telco.v_monthly_kpis
WINDOW w AS (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
ORDER BY month;

-- @query q03_revenue_by_service
-- Q4/Q18: which services drive revenue, and which are growing? Year 2 = Nov 2025-Oct 2026 vs Nov 2024-Oct 2025.
SELECT service_type,
       ROUND(SUM(transaction_amount), 0)                                                       AS revenue_kes,
       ROUND(100 * SUM(transaction_amount) / SUM(SUM(transaction_amount)) OVER (), 2)           AS revenue_share_pct,
       COUNT(*)                                                                                 AS transactions,
       ROUND(AVG(transaction_amount), 0)                                                        AS avg_ticket_kes,
       ROUND(100 * (SUM(transaction_amount) FILTER (WHERE transaction_date >= DATE '2025-11-01')
              / NULLIF(SUM(transaction_amount) FILTER (WHERE transaction_date >= DATE '2024-11-01'
                                                         AND transaction_date < DATE '2025-11-01'), 0) - 1), 2) AS yoy_growth_pct
FROM telco.transactions
GROUP BY service_type
ORDER BY revenue_kes DESC;

-- @query q04_value_by_customer_group
-- Q1/Q5: which customer groups generate the most revenue and the highest ARPU?
-- ARPU here = revenue / active customer-months for the group (so groups of different size compare fairly).
SELECT dim, grp,
       COUNT(DISTINCT customer_id)                                         AS customers,
       ROUND(SUM(revenue), 0)                                              AS revenue_kes,
       ROUND(100 * SUM(revenue) / SUM(SUM(revenue)) OVER (PARTITION BY dim), 2) AS revenue_share_pct,
       ROUND(SUM(revenue) / NULLIF(COUNT(*) FILTER (WHERE is_active), 0), 0) AS arpu_kes
FROM (
    SELECT 'customer_type' AS dim, customer_type AS grp, customer_id, revenue, is_active FROM telco.mv_customer_month
    UNION ALL SELECT 'age_group', age_group, customer_id, revenue, is_active FROM telco.mv_customer_month
    UNION ALL SELECT 'plan_type', plan_type, customer_id, revenue, is_active FROM telco.mv_customer_month
    UNION ALL SELECT 'county', county, customer_id, revenue, is_active FROM telco.mv_customer_month
) x
GROUP BY dim, grp
ORDER BY dim, revenue_kes DESC;

-- @query q05_value_segments
-- Q5: how concentrated is value? Segments come from v_customer_summary: deciles of EARLY monthly revenue
-- (first 3 months, or Jan-Mar 2024 for the opening base), so churners are not ranked low just because they left.
SELECT value_segment,
       COUNT(*)                                                         AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)               AS customer_share_pct,
       ROUND(SUM(revenue), 0)                                           AS revenue_kes,
       ROUND(100 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 1)         AS revenue_share_pct,
       ROUND(AVG(avg_monthly_revenue), 0)                               AS avg_monthly_revenue_kes,
       ROUND(100.0 * AVG(churned::int), 1)                              AS churned_pct,
       ROUND(100.0 * AVG((customer_type = 'Postpaid')::int), 1)         AS postpaid_pct
FROM telco.v_customer_summary
GROUP BY value_segment
ORDER BY avg_monthly_revenue_kes DESC;

-- @query q06_value_by_tenure
-- Q3: how does customer value change with tenure? Uses active customer-months in each tenure band.
SELECT CASE WHEN tenure_months < 3 THEN 'a) 0-2 months'
            WHEN tenure_months < 6 THEN 'b) 3-5 months'
            WHEN tenure_months < 12 THEN 'c) 6-11 months'
            WHEN tenure_months < 24 THEN 'd) 12-23 months'
            WHEN tenure_months < 48 THEN 'e) 24-47 months'
            ELSE 'f) 48+ months' END                                   AS tenure_band,
       COUNT(DISTINCT customer_id)                                     AS customers,
       COUNT(*) FILTER (WHERE is_active)                               AS active_customer_months,
       ROUND(SUM(revenue) / NULLIF(COUNT(*) FILTER (WHERE is_active), 0), 0) AS arpu_kes,
       ROUND(AVG(data_mb) FILTER (WHERE is_active), 0)                 AS avg_data_mb,
       ROUND(100.0 * COUNT(*) FILTER (WHERE is_churn_month) / NULLIF(COUNT(*) FILTER (WHERE in_opening_base), 0), 2) AS monthly_churn_pct
FROM telco.mv_customer_month
GROUP BY 1 ORDER BY 1;

-- @query q07_top_customers_by_county
-- Customer ranking: the three highest-value current customers in each county (RANK partitioned by county).
WITH ranked AS (
    SELECT customer_id, county, customer_type, plan_type, value_segment, engagement_status,
           ROUND(avg_monthly_revenue, 0) AS avg_monthly_revenue_kes,
           RANK() OVER (PARTITION BY county ORDER BY avg_monthly_revenue DESC) AS rank_in_county
    FROM telco.v_customer_summary
    WHERE NOT churned
)
SELECT * FROM ranked WHERE rank_in_county <= 3 ORDER BY county, rank_in_county;
