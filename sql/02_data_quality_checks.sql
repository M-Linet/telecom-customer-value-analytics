-- 02_data_quality_checks.sql
-- Part A profiles the raw staging layer; Part B proves the clean layer is sound (every B value should be 0).

-- @query dq_a01_row_counts
-- Purpose: raw rows vs distinct business keys reveals duplicates.
SELECT 'customers' AS table_name, COUNT(*) AS raw_rows, COUNT(DISTINCT customer_id) AS distinct_keys FROM staging.customers
UNION ALL SELECT 'subscriptions', COUNT(*), COUNT(DISTINCT subscription_id) FROM staging.subscriptions
UNION ALL SELECT 'transactions', COUNT(*), COUNT(DISTINCT transaction_id) FROM staging.transactions
UNION ALL SELECT 'usage_monthly', COUNT(*), COUNT(DISTINCT (customer_id, usage_month)) FROM staging.usage_monthly
UNION ALL SELECT 'complaints', COUNT(*), COUNT(DISTINCT complaint_id) FROM staging.complaints
UNION ALL SELECT 'campaigns', COUNT(*), COUNT(DISTINCT campaign_id) FROM staging.campaigns
ORDER BY 1;

-- @query dq_a02_label_variants
-- Purpose: inconsistent categorical labels that would split groups in every chart.
SELECT 'customer_type' AS field, customer_type AS value, COUNT(*) AS n FROM staging.customers GROUP BY 2
UNION ALL SELECT 'age_group', age_group, COUNT(*) FROM staging.customers GROUP BY 2
UNION ALL SELECT 'service_type', service_type, COUNT(*) FROM staging.transactions GROUP BY 2
UNION ALL SELECT 'resolution_status', resolution_status, COUNT(*) FROM staging.complaints GROUP BY 2
ORDER BY 1, 3 DESC;

-- @query dq_a03_missing_values
SELECT 'customers.county' AS field, COUNT(*) FILTER (WHERE county IS NULL) AS missing, COUNT(*) AS total FROM staging.customers
UNION ALL SELECT 'campaigns.campaign_response', COUNT(*) FILTER (WHERE campaign_response IS NULL), COUNT(*) FROM staging.campaigns
UNION ALL SELECT 'complaints.resolution_date', COUNT(*) FILTER (WHERE resolution_date IS NULL), COUNT(*) FROM staging.complaints
UNION ALL SELECT 'subscriptions.end_date', COUNT(*) FILTER (WHERE end_date IS NULL), COUNT(*) FROM staging.subscriptions;

-- @query dq_a04_amount_profile
-- Purpose: separate reversals, normal purchases and implausible amounts before setting rules.
SELECT CASE WHEN transaction_amount::numeric < 0 THEN 'a) negative (reversal)'
            WHEN transaction_amount::numeric <= 1000 THEN 'b) 1 - 1,000'
            WHEN transaction_amount::numeric <= 15000 THEN 'c) 1,001 - 15,000'
            WHEN transaction_amount::numeric <= 25000 THEN 'd) 15,001 - 25,000'
            ELSE 'e) above 25,000' END AS band,
       COUNT(*) AS rows, MIN(transaction_amount::numeric) AS min_kes, MAX(transaction_amount::numeric) AS max_kes
FROM staging.transactions GROUP BY 1 ORDER BY 1;

-- @query dq_a04b_amount_by_service
-- Purpose: a single ceiling misses keying errors on small fees, so check each service's own range.
-- Mobile money fees stop at KES 95 and then jump to 13,000+: those are KES 13-22 fees keyed x1000.
SELECT service_type, COUNT(*) AS rows,
       PERCENTILE_CONT(0.999) WITHIN GROUP (ORDER BY transaction_amount::numeric) AS p99_9_kes,
       MAX(transaction_amount::numeric) AS max_kes,
       COUNT(*) FILTER (WHERE transaction_amount::numeric > 1000) AS rows_above_1000
FROM staging.transactions
WHERE transaction_amount::numeric > 0 AND service_type IN ('Mobile Money Fees', 'Data Bundle', 'Voice Bundle', 'Postpaid Bill')
GROUP BY 1 ORDER BY 1;

-- @query dq_a05_usage_anomalies
SELECT COUNT(*) FILTER (WHERE data_mb::numeric < 0)            AS negative_data_rows,
       COUNT(*) FILTER (WHERE data_mb::numeric >= 999999999)    AS meter_sentinel_rows,
       MAX(data_mb::numeric) FILTER (WHERE data_mb::numeric < 999999999) AS max_plausible_data_mb
FROM staging.usage_monthly;

-- @query dq_a06_date_logic
SELECT 'acquisition date after data window' AS check_name, COUNT(*) AS rows
FROM staging.customers WHERE acquisition_date::date > DATE '2026-10-31'
UNION ALL SELECT 'complaint resolved before it was raised', COUNT(*)
FROM staging.complaints WHERE resolution_date::date < complaint_date::date
UNION ALL SELECT 'transactions for unknown customers', COUNT(*)
FROM staging.transactions t LEFT JOIN (SELECT DISTINCT customer_id FROM staging.customers) c USING (customer_id)
WHERE c.customer_id IS NULL;

-- @query dq_b01_integrity_summary
SELECT 'duplicate customer-month usage rows' AS check_name,
       (SELECT COUNT(*) - COUNT(DISTINCT (customer_id, usage_month)) FROM telco.usage_monthly) AS failures
UNION ALL SELECT 'customers with no subscription row',
       (SELECT COUNT(*) FROM telco.customers c LEFT JOIN telco.subscriptions s USING (customer_id) WHERE s.customer_id IS NULL)
UNION ALL SELECT 'customers with more than one open subscription',
       (SELECT COUNT(*) FROM (SELECT customer_id FROM telco.subscriptions WHERE end_date IS NULL GROUP BY 1 HAVING COUNT(*) > 1) x)
UNION ALL SELECT 'customers with more than one churn record',
       (SELECT COUNT(*) FROM (SELECT customer_id FROM telco.subscriptions WHERE subscription_status = 'Churned' GROUP BY 1 HAVING COUNT(*) > 1) x)
UNION ALL SELECT 'transactions before acquisition',
       (SELECT COUNT(*) FROM telco.transactions t JOIN telco.customers c USING (customer_id) WHERE t.transaction_date < c.acquisition_date)
UNION ALL SELECT 'transactions after line closed',
       (SELECT COUNT(*) FROM telco.transactions t JOIN telco.subscriptions s USING (customer_id)
         WHERE s.subscription_status = 'Churned' AND t.transaction_date > s.end_date)
UNION ALL SELECT 'acquisition date not equal to first subscription start',
       (SELECT COUNT(*) FROM telco.customers c JOIN (SELECT customer_id, MIN(start_date) d FROM telco.subscriptions GROUP BY 1) s USING (customer_id)
         WHERE c.acquisition_date <> s.d)
UNION ALL SELECT 'customer-month grid rows with activity after churn',
       (SELECT COUNT(*) FROM telco.mv_customer_month m JOIN telco.subscriptions s USING (customer_id)
         WHERE s.subscription_status = 'Churned' AND m.month > date_trunc('month', s.end_date));

-- @query dq_b02_grid_reconciliation
-- Purpose: the customer-month grid must carry every transaction and usage row exactly once.
SELECT (SELECT SUM(transaction_amount) FROM telco.transactions)     AS revenue_in_transactions,
       (SELECT SUM(revenue) FROM telco.mv_customer_month)            AS revenue_in_grid,
       (SELECT COUNT(*) FROM telco.usage_monthly)                    AS usage_rows,
       (SELECT COUNT(*) FROM telco.mv_customer_month m JOIN telco.usage_monthly u
          ON u.customer_id = m.customer_id AND u.usage_month = m.month) AS usage_rows_matched_in_grid;

-- @query dq_b03_exception_log
SELECT source_table, issue, action_taken, COUNT(*) AS records
FROM telco.dq_exceptions GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;
