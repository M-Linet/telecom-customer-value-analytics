-- 06_customer_experience.sql
-- Business questions 12-15 (customer experience).

-- @query q16_complaints_by_category
-- Q12: which complaints occur most often? Rate per 1,000 subscriber-months makes it comparable over time.
SELECT complaint_category,
       COUNT(*)                                                       AS complaints,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)             AS share_pct,
       ROUND(1000.0 * COUNT(*) / (SELECT SUM(opening_base + new_customers) FROM telco.v_monthly_kpis), 2) AS per_1000_subscriber_months
FROM telco.complaints
GROUP BY 1 ORDER BY complaints DESC;

-- @query q17_resolution_time
-- Q13: which categories take longest to resolve, and how many are never resolved?
SELECT complaint_category,
       COUNT(*)                                                                         AS complaints,
       ROUND(AVG(resolution_date - complaint_date), 1)                                   AS avg_days_to_resolve,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_date - complaint_date)    AS median_days,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY resolution_date - complaint_date)    AS p90_days,
       ROUND(100.0 * COUNT(*) FILTER (WHERE resolution_status <> 'Resolved') / COUNT(*), 1) AS unresolved_or_escalated_pct
FROM telco.complaints
GROUP BY 1 ORDER BY unresolved_or_escalated_pct DESC;

-- @query q18_complaints_and_churn
-- Q14: is inactivity/churn associated with unresolved complaints?
-- Population: customers subscribed on 1 Jan 2025. Exposure: their worst complaint outcome in Jan-Jun 2025.
-- Outcome: line closed between Feb 2025 and Mar 2026 (churn is recorded ~3-4 months after the customer stops).
-- This shows association, not proof of cause: unhappy customers may both complain and leave.
WITH base AS (
    SELECT customer_id FROM telco.mv_customer_month WHERE month = DATE '2025-01-01' AND in_opening_base
), exposure AS (
    SELECT customer_id,
           MAX(CASE WHEN resolution_status <> 'Resolved' THEN 3
                    WHEN resolution_date IS NULL THEN 1
                    WHEN resolution_date - complaint_date > 7 THEN 2 ELSE 1 END) AS worst
    FROM telco.complaints
    WHERE complaint_date BETWEEN DATE '2025-01-01' AND DATE '2025-06-30'
    GROUP BY 1
), outcome AS (
    SELECT customer_id FROM telco.subscriptions
    WHERE subscription_status = 'Churned' AND end_date BETWEEN DATE '2025-02-01' AND DATE '2026-03-31'
)
-- Results are also split by value tier: complainers skew towards higher-value customers, who churn less
-- anyway, so an unstratified comparison understates the effect (a confounder).
SELECT CASE WHEN s.value_segment IN ('Platinum (top 10%)', 'Gold (next 20%)') THEN 'Higher value (Platinum/Gold)'
            ELSE 'Lower value (Silver/Bronze)' END                    AS value_tier,
       CASE COALESCE(e.worst, 0) WHEN 0 THEN 'a) No complaint'
                                 WHEN 1 THEN 'b) Resolved within 7 days'
                                 WHEN 2 THEN 'c) Resolved after 7+ days'
                                 ELSE 'd) Unresolved or escalated' END AS complaint_experience,
       COUNT(*)                                                       AS customers,
       COUNT(o.customer_id)                                           AS churned,
       ROUND(100.0 * COUNT(o.customer_id) / COUNT(*), 1)              AS churned_pct
FROM base b
JOIN telco.v_customer_summary s USING (customer_id)
LEFT JOIN exposure e USING (customer_id) LEFT JOIN outcome o USING (customer_id)
GROUP BY ROLLUP (1), 2 ORDER BY 1 NULLS FIRST, 2;

-- @query q19_complaints_by_county
-- Q15: which areas generate the most complaints, and of what kind? Rate per 1,000 subscriber-months.
WITH exposure AS (
    SELECT county, COUNT(*) AS subscriber_months FROM telco.mv_customer_month GROUP BY county
)
SELECT COALESCE(c2.county, 'Unknown')                                     AS county,
       COUNT(*)                                                           AS complaints,
       ROUND(1000.0 * COUNT(*) / MAX(e.subscriber_months), 2)             AS per_1000_subscriber_months,
       ROUND(1000.0 * COUNT(*) FILTER (WHERE complaint_category IN ('Network coverage', 'Data speed')) / MAX(e.subscriber_months), 2)
                                                                          AS network_and_speed_per_1000,
       ROUND(100.0 * COUNT(*) FILTER (WHERE resolution_status <> 'Resolved') / COUNT(*), 1) AS unresolved_pct
FROM telco.complaints c
JOIN telco.customers c2 USING (customer_id)
JOIN exposure e ON e.county = COALESCE(c2.county, 'Unknown')
GROUP BY 1 ORDER BY per_1000_subscriber_months DESC;

-- @query q20_complaints_by_segment
-- Complaint patterns by value segment and customer type.
SELECT s.value_segment, s.customer_type,
       COUNT(DISTINCT s.customer_id)                                       AS customers,
       ROUND(100.0 * AVG((s.complaints > 0)::int), 1)                      AS pct_ever_complained,
       ROUND(AVG(s.complaints::numeric) * 1000 / AVG(s.months_observed), 1) AS complaints_per_1000_customer_months,
       ROUND(100.0 * SUM(s.open_complaints) / NULLIF(SUM(s.complaints), 0), 1) AS unresolved_share_pct
FROM telco.v_customer_summary s
GROUP BY 1, 2 ORDER BY 1, 2;
