-- 01_create_tables.sql
-- staging : raw CSVs loaded as TEXT (no constraints), so bad values can be profiled
-- telco   : cleaned, typed and constrained model for analysis and Power BI

DROP SCHEMA IF EXISTS staging CASCADE;
DROP SCHEMA IF EXISTS telco CASCADE;
CREATE SCHEMA staging;
CREATE SCHEMA telco;

CREATE TABLE staging.customers     (customer_id TEXT, age_group TEXT, county TEXT, acquisition_date TEXT, customer_type TEXT);
CREATE TABLE staging.subscriptions (subscription_id TEXT, customer_id TEXT, plan_type TEXT, subscription_status TEXT, start_date TEXT, end_date TEXT);
CREATE TABLE staging.transactions  (transaction_id TEXT, customer_id TEXT, transaction_date TEXT, transaction_amount TEXT, service_type TEXT);
CREATE TABLE staging.usage_monthly (usage_id TEXT, customer_id TEXT, usage_month TEXT, data_mb TEXT, voice_minutes TEXT, sms_count TEXT);
CREATE TABLE staging.complaints    (complaint_id TEXT, customer_id TEXT, complaint_date TEXT, complaint_category TEXT, resolution_status TEXT, resolution_date TEXT);
CREATE TABLE staging.campaigns     (campaign_id TEXT, customer_id TEXT, campaign_date TEXT, campaign_type TEXT, campaign_response TEXT);

CREATE TABLE telco.customers (
    customer_id        VARCHAR(8)  PRIMARY KEY,
    age_group          VARCHAR(10) NOT NULL CHECK (age_group IN ('18-24','25-34','35-44','45-54','55+')),
    county             VARCHAR(30),                                   -- NULL = not captured at registration
    acquisition_date   DATE        NOT NULL,
    customer_type      VARCHAR(10) NOT NULL CHECK (customer_type IN ('Prepaid','Postpaid')),
    acquisition_date_corrected BOOLEAN NOT NULL DEFAULT FALSE
);

-- One row per plan period. The open row (end_date IS NULL) is the current plan.
CREATE TABLE telco.subscriptions (
    subscription_id      VARCHAR(9)  PRIMARY KEY,
    customer_id          VARCHAR(8)  NOT NULL REFERENCES telco.customers(customer_id),
    plan_type            VARCHAR(30) NOT NULL,
    subscription_status  VARCHAR(15) NOT NULL CHECK (subscription_status IN ('Active','Plan Changed','Churned')),
    start_date           DATE NOT NULL,
    end_date             DATE,
    CHECK (end_date IS NULL OR end_date >= start_date),
    CHECK ((subscription_status = 'Active') = (end_date IS NULL))
);

CREATE TABLE telco.transactions (
    transaction_id      VARCHAR(10)   PRIMARY KEY,
    customer_id         VARCHAR(8)    NOT NULL REFERENCES telco.customers(customer_id),
    transaction_date    DATE          NOT NULL,
    transaction_amount  NUMERIC(12,2) NOT NULL CHECK (transaction_amount > 0),   -- KES paid by the subscriber
    service_type        VARCHAR(20)   NOT NULL CHECK (service_type IN
                        ('Data Bundle','Voice Bundle','SMS Bundle','Combo Bundle','Mobile Money Fees','Postpaid Bill'))
);

-- Negative amounts in the export are reversals/refunds of earlier purchases.
CREATE TABLE telco.reversals (
    transaction_id    VARCHAR(10)   PRIMARY KEY,
    customer_id       VARCHAR(8)    NOT NULL REFERENCES telco.customers(customer_id),
    transaction_date  DATE          NOT NULL,
    reversal_amount   NUMERIC(12,2) NOT NULL CHECK (reversal_amount > 0),
    service_type      VARCHAR(20)   NOT NULL
);

-- Grain: customer x calendar month (daily records would be ~20M rows for no analytical gain here).
CREATE TABLE telco.usage_monthly (
    usage_id       BIGINT       PRIMARY KEY,
    customer_id    VARCHAR(8)   NOT NULL REFERENCES telco.customers(customer_id),
    usage_month    DATE         NOT NULL CHECK (EXTRACT(DAY FROM usage_month) = 1),
    data_mb        NUMERIC(14,1) CHECK (data_mb >= 0),             -- NULL where the meter reading was invalid
    voice_minutes  NUMERIC(10,1) NOT NULL CHECK (voice_minutes >= 0),
    sms_count      INTEGER       NOT NULL CHECK (sms_count >= 0),
    UNIQUE (customer_id, usage_month)
);

CREATE TABLE telco.complaints (
    complaint_id        VARCHAR(8)  PRIMARY KEY,
    customer_id         VARCHAR(8)  NOT NULL REFERENCES telco.customers(customer_id),
    complaint_date      DATE        NOT NULL,
    complaint_category  VARCHAR(30) NOT NULL,
    resolution_status   VARCHAR(12) NOT NULL CHECK (resolution_status IN ('Resolved','Unresolved','Escalated')),
    resolution_date     DATE,
    CHECK (resolution_date IS NULL OR resolution_date >= complaint_date)
);

CREATE TABLE telco.campaigns (
    campaign_id        VARCHAR(8)  PRIMARY KEY,
    customer_id        VARCHAR(8)  NOT NULL REFERENCES telco.customers(customer_id),
    campaign_date      DATE        NOT NULL,
    campaign_type      VARCHAR(30) NOT NULL,
    campaign_response  VARCHAR(10) NOT NULL CHECK (campaign_response IN ('Accepted','Ignored','Opted out','Unknown'))
);

CREATE TABLE telco.dq_exceptions (
    exception_id  BIGSERIAL PRIMARY KEY,
    source_table  VARCHAR(30) NOT NULL,
    record_key    VARCHAR(30) NOT NULL,
    issue         VARCHAR(90) NOT NULL,
    action_taken  VARCHAR(80) NOT NULL,
    logged_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX ix_tx_customer_date  ON telco.transactions (customer_id, transaction_date);
CREATE INDEX ix_usage_month       ON telco.usage_monthly (usage_month);
CREATE INDEX ix_sub_customer      ON telco.subscriptions (customer_id);
CREATE INDEX ix_complaint_customer ON telco.complaints (customer_id, complaint_date);
CREATE INDEX ix_campaign_customer ON telco.campaigns (customer_id, campaign_date);
