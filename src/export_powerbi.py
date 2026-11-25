"""Export the Power BI star schema (views in a `powerbi` schema + CSV files) and the KPI reconciliation sheet.

    python -m src.export_powerbi
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from src.data_loader import PROJECT_ROOT, get_engine, query

OUT = PROJECT_ROOT / "data" / "processed" / "powerbi"

VIEWS = {
    "dim_date": """SELECT d::date AS date, EXTRACT(YEAR FROM d)::int AS year, EXTRACT(MONTH FROM d)::int AS month_number,
                   to_char(d, 'Mon') AS month_short, to_char(d, 'YYYY-MM') AS year_month, date_trunc('month', d)::date AS month_start
                   FROM generate_series(DATE '2024-01-01', DATE '2026-10-31', INTERVAL '1 day') d""",
    "dim_customer": """SELECT customer_id, customer_type, age_group, county, plan_type, cohort_month,
                       to_char(cohort_month, 'YYYY-MM') AS cohort_label,
                       (cohort_month >= DATE '2024-01-01') AS acquired_in_window, value_segment, engagement_status, churned,
                       tenure_months, ROUND(avg_monthly_revenue, 2) AS avg_monthly_revenue,
                       ROUND(COALESCE(rev_may_jul_2026, 0), 2) AS rev_may_jul_2026, ROUND(COALESCE(rev_aug_oct_2026, 0), 2) AS rev_aug_oct_2026,
                       complaints, open_complaints
                       FROM telco.v_customer_summary""",
    "fact_customer_month": """SELECT customer_id, month, tenure_months,
                       CASE WHEN tenure_months < 3 THEN '0-2 months' WHEN tenure_months < 6 THEN '3-5 months'
                            WHEN tenure_months < 12 THEN '6-11 months' WHEN tenure_months < 24 THEN '12-23 months'
                            WHEN tenure_months < 48 THEN '24-47 months' ELSE '48+ months' END AS tenure_band,
                       CASE WHEN tenure_months < 3 THEN 1 WHEN tenure_months < 6 THEN 2 WHEN tenure_months < 12 THEN 3
                            WHEN tenure_months < 24 THEN 4 WHEN tenure_months < 48 THEN 5 ELSE 6 END AS tenure_band_order,
                       revenue, transactions, data_mb, voice_minutes, sms_count, is_active, in_opening_base, is_churn_month,
                       (cohort_month = month) AS is_new_customer_month
                       FROM telco.mv_customer_month""",
    "fact_service_revenue": """SELECT customer_id, date_trunc('month', transaction_date)::date AS month, service_type,
                       SUM(transaction_amount) AS revenue, COUNT(*) AS transactions
                       FROM telco.transactions GROUP BY 1, 2, 3""",
    "fact_complaints": """SELECT complaint_id, customer_id, date_trunc('month', complaint_date)::date AS month, complaint_category,
                       resolution_status, (resolution_date - complaint_date) AS days_to_resolve FROM telco.complaints""",
    "fact_campaigns": """SELECT campaign_id, customer_id, date_trunc('month', campaign_date)::date AS month, campaign_type, campaign_response
                       FROM telco.campaigns""",
}


def create_powerbi_schema(engine) -> None:
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS powerbi CASCADE; CREATE SCHEMA powerbi;"))
        for name, sql in VIEWS.items():
            c.execute(text(f"CREATE VIEW powerbi.{name} AS {sql}"))


def export_csv(engine) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in VIEWS:
        df = query(engine, f"SELECT * FROM powerbi.{name}")
        df.to_csv(OUT / f"{name}.csv", index=False)
        counts[name] = len(df)
    # Pre-computed analytical tables imported as-is (logic is clearer and testable in SQL)
    so = PROJECT_ROOT / "reports" / "sql_outputs"
    coh = pd.read_csv(so / "q11_cohort_retention_matrix.csv")
    coh["cohort_label"] = pd.to_datetime(coh["cohort_month"]).dt.strftime("%Y-%m")
    coh.to_csv(OUT / "cohort_retention.csv", index=False)
    q18 = pd.read_csv(so / "q18_complaints_and_churn.csv").dropna(subset=["value_tier"])
    q18.to_csv(OUT / "complaint_churn_link.csv", index=False)
    counts.update({"cohort_retention": len(coh), "complaint_churn_link": len(q18)})
    return counts


def write_reconciliation(engine) -> pd.DataFrame:
    rows = [
        ("Revenue, all months", "SELECT SUM(revenue) FROM telco.mv_customer_month"),
        ("Revenue, Oct 2026", "SELECT revenue FROM telco.v_monthly_kpis WHERE month = DATE '2026-10-01'"),
        ("Active customers, Oct 2026", "SELECT active_customers FROM telco.v_monthly_kpis WHERE month = DATE '2026-10-01'"),
        ("Subscribed base, Oct 2026 (rows in grid)", "SELECT COUNT(*) FROM telco.mv_customer_month WHERE month = DATE '2026-10-01'"),
        ("ARPU, Oct 2026", "SELECT arpu FROM telco.v_monthly_kpis WHERE month = DATE '2026-10-01'"),
        ("Avg monthly churn %, May 2024-Oct 2026", "SELECT ROUND(100.0*SUM(churned)/SUM(opening_base),3) FROM telco.v_monthly_kpis WHERE month >= DATE '2024-05-01'"),
        ("Churn %, prepaid, May 2024-Oct 2026", "SELECT ROUND(100.0*COUNT(*) FILTER (WHERE is_churn_month)/COUNT(*) FILTER (WHERE in_opening_base),3) FROM telco.mv_customer_month WHERE month >= DATE '2024-05-01' AND customer_type='Prepaid'"),
        ("Complaints, all", "SELECT COUNT(*) FROM telco.complaints"),
        ("Avg days to resolve, Network coverage", "SELECT ROUND(AVG(resolution_date-complaint_date),2) FROM telco.complaints WHERE complaint_category='Network coverage'"),
        ("Customers, total", "SELECT COUNT(*) FROM telco.customers"),
    ]
    rec = pd.DataFrame([(k, float(query(engine, s).iloc[0, 0])) for k, s in rows], columns=["kpi", "expected_value"])
    rec.to_csv(PROJECT_ROOT / "powerbi" / "kpi_reconciliation.csv", index=False)
    return rec


if __name__ == "__main__":
    eng = get_engine()
    create_powerbi_schema(eng)
    print(export_csv(eng))
    print(write_reconciliation(eng).to_string(index=False))
