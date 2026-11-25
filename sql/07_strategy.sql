-- 07_strategy.sql
-- Business questions 16-19: who to retain, what works, where to grow.

-- @query q21_campaign_response
-- Response rates by campaign type.
SELECT campaign_type,
       COUNT(*)                                                                   AS contacts,
       ROUND(100.0 * COUNT(*) FILTER (WHERE campaign_response = 'Accepted') / COUNT(*), 1)  AS accepted_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE campaign_response = 'Opted out') / COUNT(*), 1) AS opted_out_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE campaign_response = 'Unknown') / COUNT(*), 1)   AS response_unknown_pct
FROM telco.campaigns GROUP BY 1 ORDER BY accepted_pct DESC;

-- @query q22_winback_effect
-- Does a win-back offer change what happens next? Customers contacted Jan 2024 - Apr 2026; outcome = line
-- closed within 6 months of the contact. Accepted vs not accepted is self-selected, so this is indicative only.
SELECT CASE WHEN c.campaign_response = 'Accepted' THEN 'Accepted offer' ELSE 'Did not accept' END AS response,
       COUNT(*)                                                                  AS contacts,
       COUNT(*) FILTER (WHERE s.end_date BETWEEN c.campaign_date AND c.campaign_date + 183) AS closed_within_6m,
       ROUND(100.0 * COUNT(*) FILTER (WHERE s.end_date BETWEEN c.campaign_date AND c.campaign_date + 183) / COUNT(*), 1) AS closed_within_6m_pct
FROM telco.campaigns c
LEFT JOIN telco.subscriptions s ON s.customer_id = c.customer_id AND s.subscription_status = 'Churned'
WHERE c.campaign_type = 'Win-back offer' AND c.campaign_date < DATE '2026-05-01'
GROUP BY 1 ORDER BY 1;

-- @query q23_valuable_customers_at_risk
-- Q16/Q17: high-value current customers with declining activity, ranked by revenue at risk.
SELECT customer_id, customer_type, plan_type, county, age_group, value_segment, engagement_status,
       ROUND(rev_may_jul_2026 / 3, 0)                         AS monthly_revenue_may_jul_kes,
       ROUND(COALESCE(rev_aug_oct_2026, 0) / 3, 0)            AS monthly_revenue_aug_oct_kes,
       open_complaints,
       ROW_NUMBER() OVER (ORDER BY rev_may_jul_2026 - COALESCE(rev_aug_oct_2026, 0) DESC) AS priority
FROM telco.v_customer_summary
WHERE engagement_status IN ('Declining (>50% revenue drop)', 'Silent (no activity Aug-Oct)')
  AND value_segment IN ('Platinum (top 10%)', 'Gold (next 20%)')
ORDER BY priority
LIMIT 50;

-- @query q24_usage_growth
-- Q18: where is engagement growing? Average usage per active customer, Year 2 vs Year 1.
SELECT CASE WHEN month >= DATE '2025-11-01' THEN 'Year 2 (Nov25-Oct26)' ELSE 'Year 1 (Nov24-Oct25)' END AS period,
       ROUND(AVG(data_mb) FILTER (WHERE is_active), 0)        AS avg_data_mb,
       ROUND(AVG(voice_minutes) FILTER (WHERE is_active), 0)  AS avg_voice_minutes,
       ROUND(AVG(sms_count) FILTER (WHERE is_active), 1)      AS avg_sms,
       ROUND(SUM(revenue) / COUNT(*) FILTER (WHERE is_active), 0) AS arpu_kes
FROM telco.mv_customer_month
WHERE month >= DATE '2024-11-01'
GROUP BY 1 ORDER BY 1;

-- @query q25_price_change_churn
-- Context from management: bundle prices rose ~10% in July 2025. Because lines close ~4 months after a
-- customer stops, the effect should appear in closures from Nov 2025. Compare churn by group before and after.
WITH cm AS (
    SELECT m.*, s.value_segment,
           CASE WHEN m.month BETWEEN DATE '2025-03-01' AND DATE '2025-10-01' THEN 'a) Before (Mar-Oct 2025)'
                WHEN m.month BETWEEN DATE '2025-11-01' AND DATE '2026-02-01' THEN 'b) After (Nov 2025-Feb 2026)'
                WHEN m.month BETWEEN DATE '2026-03-01' AND DATE '2026-10-01' THEN 'c) Later (Mar-Oct 2026)' END AS period
    FROM telco.mv_customer_month m JOIN telco.v_customer_summary s USING (customer_id)
)
SELECT period, customer_type, value_segment,
       ROUND(100.0 * SUM(is_churn_month::int) / NULLIF(COUNT(*) FILTER (WHERE in_opening_base), 0), 2) AS monthly_churn_pct
FROM cm WHERE period IS NOT NULL
GROUP BY 1, 2, 3 ORDER BY 2, 3, 1;
