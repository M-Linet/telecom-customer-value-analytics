"""Database integrity and reconciliation tests. They need the built database
(`python -m src.pipeline`) and are skipped automatically if PostgreSQL is unreachable."""
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_loader import get_engine, query  # noqa: E402


@pytest.fixture(scope="module")
def engine():
    try:
        eng = get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1 FROM telco.transactions LIMIT 1"))
        return eng
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"database not available: {exc}")


def scalar(engine, sql):
    return query(engine, sql).iloc[0, 0]


def named_query(file, name):
    sql = (ROOT / "sql" / file).read_text()
    return sql.split(f"-- @query {name}")[1].split("-- @query")[0].strip().rstrip(";")


@pytest.mark.parametrize("table,key", [
    ("telco.customers", "customer_id"), ("telco.subscriptions", "subscription_id"),
    ("telco.transactions", "transaction_id"), ("telco.usage_monthly", "usage_id"),
    ("telco.complaints", "complaint_id"), ("telco.campaigns", "campaign_id"),
])
def test_primary_keys_unique(engine, table, key):
    assert scalar(engine, f"SELECT COUNT(*) - COUNT(DISTINCT {key}) FROM {table}") == 0


def test_integrity_checks_all_zero(engine):
    df = query(engine, named_query("02_data_quality_checks.sql", "dq_b01_integrity_summary"))
    assert len(df) >= 8
    assert (df["failures"] == 0).all(), df[df["failures"] != 0]


def test_grid_reconciles_with_transactions_and_usage(engine):
    r = query(engine, named_query("02_data_quality_checks.sql", "dq_b02_grid_reconciliation")).iloc[0]
    assert float(r["revenue_in_transactions"]) == pytest.approx(float(r["revenue_in_grid"]))
    assert r["usage_rows"] == r["usage_rows_matched_in_grid"]


def test_no_raw_defects_survive(engine):
    assert scalar(engine, "SELECT COUNT(*) FROM telco.transactions WHERE transaction_amount <= 0 OR transaction_amount > 25000") == 0
    assert scalar(engine, "SELECT COUNT(*) FROM telco.usage_monthly WHERE data_mb < 0 OR data_mb >= 999999999") == 0
    assert scalar(engine, "SELECT COUNT(*) FROM telco.complaints WHERE resolution_date < complaint_date") == 0
    assert scalar(engine, "SELECT COUNT(*) FROM telco.customers WHERE acquisition_date > DATE '2026-10-31'") == 0
    assert scalar(engine, "SELECT COUNT(DISTINCT service_type) FROM telco.transactions") == 6


def test_status_and_end_date_agree(engine):
    assert scalar(engine, """SELECT COUNT(*) FROM telco.subscriptions
                             WHERE (subscription_status = 'Active') <> (end_date IS NULL)""") == 0


def test_every_exception_is_logged_once_per_issue(engine):
    df = query(engine, "SELECT source_table, record_key, issue, COUNT(*) n FROM telco.dq_exceptions GROUP BY 1,2,3 HAVING COUNT(*) > 1")
    # exact-duplicate rows may legitimately repeat a key; everything else must be unique
    assert df[df["issue"] != "exact duplicate row"].empty


def test_monthly_kpis_view_matches_grid(engine):
    v = query(engine, "SELECT month, active_customers, revenue, churned FROM telco.v_monthly_kpis WHERE month = DATE '2026-10-01'").iloc[0]
    g = query(engine, """SELECT COUNT(*) FILTER (WHERE is_active) a, SUM(revenue) r, COUNT(*) FILTER (WHERE is_churn_month) c
                         FROM telco.mv_customer_month WHERE month = DATE '2026-10-01'""").iloc[0]
    assert v["active_customers"] == g["a"] and float(v["revenue"]) == pytest.approx(float(g["r"])) and v["churned"] == g["c"]


def test_value_segments_partition_the_base(engine):
    df = query(engine, "SELECT value_segment, COUNT(*) n FROM telco.v_customer_summary GROUP BY 1")
    total = scalar(engine, "SELECT COUNT(*) FROM telco.customers")
    assert df["n"].sum() == total
    seg = df.set_index("value_segment")["n"]
    scored = seg.drop(labels=[s for s in seg.index if s.startswith("Unsegmented")]).sum()
    assert seg["Platinum (top 10%)"] / scored == pytest.approx(0.10, abs=0.005)
    assert seg["Bronze (bottom 40%)"] / scored == pytest.approx(0.40, abs=0.005)


def test_powerbi_export_reconciles(engine):
    path = ROOT / "data" / "processed" / "powerbi" / "fact_customer_month.csv"
    if not path.exists():
        pytest.skip("run python -m src.export_powerbi first")
    fcm = pd.read_csv(path, usecols=["revenue"])
    assert fcm["revenue"].sum() == pytest.approx(float(scalar(engine, "SELECT SUM(transaction_amount) FROM telco.transactions")), rel=1e-9)
