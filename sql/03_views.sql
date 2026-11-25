-- 03_views.sql
-- The semantic layer. Every KPI definition used by SQL, Python and Power BI is fixed here.
--
-- DEFINITIONS (data window: Jan 2024 - Oct 2026; all money in KES)
--   Revenue            = sum of purchase transactions (bundles, mobile-money fees, postpaid bills); reversals excluded.
--   Subscribed (base)  = customer whose line is open on the first day of the month
--                        (acquired before the month and not yet closed).
--   Active in month    = at least one revenue transaction OR any recorded usage (data, voice or SMS) in that month.
--   Churned            = line closed by the operator (subscription_status = 'Churned'); churn month = month of end_date.
--                        Lines are closed after 90 days without activity, so churn is recorded ~3 months after the
--                        customer actually stopped using the service.
--   Monthly churn rate = churned in month m / subscribed base at the start of month m.
--   ARPU               = revenue in month m / active customers in month m.
--   Cohort             = calendar month of acquisition. Retention(c, k) = cohort members active in month c+k /
--                        cohort size (fixed denominator). Cells beyond the data window are NULL, not zero.

DROP MATERIALIZED VIEW IF EXISTS telco.mv_customer_month CASCADE;
CREATE MATERIALIZED VIEW telco.mv_customer_month AS
WITH churn AS (
    SELECT customer_id, end_date AS churn_date
    FROM telco.subscriptions WHERE subscription_status = 'Churned'
), plan_now AS (            -- plan in force at the customer's last subscription row
    SELECT DISTINCT ON (customer_id) customer_id, plan_type
    FROM telco.subscriptions ORDER BY customer_id, start_date DESC
), bounds AS (
    SELECT c.customer_id, c.customer_type, c.age_group, COALESCE(c.county, 'Unknown') AS county, p.plan_type,
           date_trunc('month', c.acquisition_date)::date                                   AS cohort_month,
           GREATEST(date_trunc('month', c.acquisition_date)::date, DATE '2024-01-01')      AS first_month,
           LEAST(COALESCE(date_trunc('month', ch.churn_date)::date, DATE '2026-10-01'), DATE '2026-10-01') AS last_month,
           ch.churn_date
    FROM telco.customers c
    LEFT JOIN churn ch USING (customer_id)
    LEFT JOIN plan_now p USING (customer_id)
), grid AS (
    SELECT b.*, gs::date AS month
    FROM bounds b, generate_series(b.first_month, b.last_month, INTERVAL '1 month') AS gs
), rev AS (
    SELECT customer_id, date_trunc('month', transaction_date)::date AS month,
           SUM(transaction_amount) AS revenue, COUNT(*) AS transactions
    FROM telco.transactions GROUP BY 1, 2
)
SELECT g.customer_id, g.month, g.cohort_month, g.customer_type, g.age_group, g.county, g.plan_type,
       (EXTRACT(YEAR FROM age(g.month, g.cohort_month)) * 12 + EXTRACT(MONTH FROM age(g.month, g.cohort_month)))::int AS tenure_months,
       COALESCE(r.revenue, 0)       AS revenue,
       COALESCE(r.transactions, 0)  AS transactions,
       COALESCE(u.data_mb, 0)       AS data_mb,
       COALESCE(u.voice_minutes, 0) AS voice_minutes,
       COALESCE(u.sms_count, 0)     AS sms_count,
       (COALESCE(r.revenue, 0) > 0 OR COALESCE(u.data_mb, 0) > 0 OR COALESCE(u.voice_minutes, 0) > 0
        OR COALESCE(u.sms_count, 0) > 0)                                         AS is_active,
       (g.cohort_month < g.month OR (g.cohort_month = g.month AND FALSE))        AS in_opening_base,   -- open on day 1
       (g.churn_date IS NOT NULL AND date_trunc('month', g.churn_date)::date = g.month) AS is_churn_month
FROM grid g
LEFT JOIN rev r ON r.customer_id = g.customer_id AND r.month = g.month
LEFT JOIN telco.usage_monthly u ON u.customer_id = g.customer_id AND u.usage_month = g.month;

CREATE UNIQUE INDEX ux_cm ON telco.mv_customer_month (customer_id, month);
CREATE INDEX ix_cm_month ON telco.mv_customer_month (month);

-- One row per customer: value in the window, status, engagement trend and value segment.
-- value_segment = decile of EARLY monthly revenue (see early_monthly_revenue); customers with
-- no early month yet (acquired in the last month) are 'Unsegmented (too new)'.
CREATE VIEW telco.v_customer_summary AS
WITH agg AS (
    SELECT customer_id,
           MIN(customer_type) AS customer_type, MIN(age_group) AS age_group, MIN(county) AS county,
           MIN(plan_type) AS plan_type, MIN(cohort_month) AS cohort_month,
           COUNT(*)                                  AS months_observed,
           COUNT(*) FILTER (WHERE is_active)         AS active_months,
           SUM(revenue)                              AS revenue,
           SUM(revenue) / COUNT(*)                   AS avg_monthly_revenue,
           MAX(month) FILTER (WHERE is_active)       AS last_active_month,
           BOOL_OR(is_churn_month)                   AS churned,
           MAX(tenure_months)                        AS tenure_months,
           SUM(revenue)  FILTER (WHERE month BETWEEN DATE '2026-05-01' AND DATE '2026-07-01') AS rev_may_jul_2026,
           SUM(revenue)  FILTER (WHERE month BETWEEN DATE '2026-08-01' AND DATE '2026-10-01') AS rev_aug_oct_2026,
           SUM(data_mb)  FILTER (WHERE month BETWEEN DATE '2026-05-01' AND DATE '2026-07-01') AS data_may_jul_2026,
           SUM(data_mb)  FILTER (WHERE month BETWEEN DATE '2026-08-01' AND DATE '2026-10-01') AS data_aug_oct_2026,
           SUM(data_mb) / NULLIF(SUM(data_mb + voice_minutes * 1.0 + sms_count), 0) AS data_share_proxy,
           AVG(data_mb) FILTER (WHERE is_active)       AS avg_data_mb,
           AVG(voice_minutes) FILTER (WHERE is_active) AS avg_voice_minutes,
           AVG(sms_count) FILTER (WHERE is_active)     AS avg_sms,
           AVG(transactions) FILTER (WHERE is_active)  AS avg_transactions,
           -- Early value: average monthly revenue in the first 3 full months we observe the customer
           -- (Jan-Mar 2024 for the existing base; months 1-3 after acquisition for new customers).
           -- Segmenting on EARLY behaviour avoids circularity: a value segment built on lifetime averages
           -- would label churners "low value" partly because their revenue fell while they were leaving.
           AVG(revenue) FILTER (WHERE (cohort_month < DATE '2024-01-01' AND month <= DATE '2024-03-01')
                                   OR (cohort_month >= DATE '2024-01-01' AND tenure_months BETWEEN 1 AND 3)) AS early_monthly_revenue
    FROM telco.mv_customer_month GROUP BY customer_id
), comp AS (
    SELECT customer_id, COUNT(*) AS complaints,
           COUNT(*) FILTER (WHERE resolution_status <> 'Resolved') AS open_complaints
    FROM telco.complaints GROUP BY customer_id
), ranked AS (
    SELECT a.*, CASE WHEN a.early_monthly_revenue IS NOT NULL
                     THEN NTILE(10) OVER (PARTITION BY a.early_monthly_revenue IS NULL ORDER BY a.early_monthly_revenue DESC) END AS value_decile
    FROM agg a
)
SELECT r.*,
       CASE WHEN value_decile IS NULL THEN 'Unsegmented (too new)'
            WHEN value_decile = 1 THEN 'Platinum (top 10%)'
            WHEN value_decile <= 3 THEN 'Gold (next 20%)'
            WHEN value_decile <= 6 THEN 'Silver (next 30%)'
            ELSE 'Bronze (bottom 40%)' END                                   AS value_segment,
       COALESCE(c.complaints, 0)      AS complaints,
       COALESCE(c.open_complaints, 0) AS open_complaints,
       CASE WHEN r.churned THEN 'Churned'
            WHEN r.months_observed < 6 THEN 'Too new to assess'
            WHEN COALESCE(r.rev_aug_oct_2026, 0) = 0 AND COALESCE(r.data_aug_oct_2026, 0) = 0 THEN 'Silent (no activity Aug-Oct)'
            WHEN r.rev_aug_oct_2026 < 0.5 * r.rev_may_jul_2026 THEN 'Declining (>50% revenue drop)'
            ELSE 'Stable or growing' END                                       AS engagement_status
FROM ranked r LEFT JOIN comp c USING (customer_id);

-- Month-level KPI table (also used to reconcile Power BI)
CREATE VIEW telco.v_monthly_kpis AS
WITH base AS (
    SELECT month,
           COUNT(*) FILTER (WHERE in_opening_base)   AS opening_base,
           COUNT(*) FILTER (WHERE is_active)         AS active_customers,
           COUNT(*) FILTER (WHERE is_churn_month)    AS churned,
           COUNT(*) FILTER (WHERE cohort_month = month) AS new_customers,
           SUM(revenue)                              AS revenue
    FROM telco.mv_customer_month GROUP BY month
)
SELECT month, opening_base, new_customers, active_customers, churned, revenue,
       ROUND(revenue / NULLIF(active_customers, 0), 2)                 AS arpu,
       ROUND(100.0 * churned / NULLIF(opening_base, 0), 3)             AS churn_rate_pct
FROM base;
