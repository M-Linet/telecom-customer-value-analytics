"""End-to-end build: raw CSV -> staging -> cleaning -> telco model -> views.

    python -m src.generate_data   # synthetic raw data
    python -m src.pipeline        # build PostgreSQL database
    python -m src.run_sql         # run the SQL analysis library
"""
from __future__ import annotations

import json
import time

import pandas as pd
import psycopg2
from sqlalchemy import text

from src import data_cleaning as dc
from src.data_loader import PROJECT_ROOT, SQL_DIR, copy_dataframe, get_engine, load_raw_to_staging, read_table, run_sql_file


def create_database() -> None:
    url = get_engine("postgres").url
    conn = psycopg2.connect(host=url.host, port=url.port, user=url.username, password=url.password or None, dbname="postgres")
    conn.autocommit = True
    with conn.cursor() as cur:
        for stmt in (SQL_DIR / "00_create_database.sql").read_text().split(";"):
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if body:
                cur.execute(body)
    conn.close()


def build() -> dict:
    t0 = time.time()
    create_database()
    eng = get_engine()
    run_sql_file(eng, SQL_DIR / "01_create_tables.sql")
    staged = load_raw_to_staging(eng)
    raw = {t: read_table(eng, f"staging.{t}") for t in staged}
    exc: list = []
    cust, e = dc.clean_customers(raw["customers"], raw["subscriptions"]); exc += e
    ids = set(cust["customer_id"])
    subs, e = dc.clean_subscriptions(raw["subscriptions"], ids); exc += e
    tx, rev, tx_q, e = dc.clean_transactions(raw["transactions"], ids); exc += e
    usage, e = dc.clean_usage(raw["usage_monthly"], ids); exc += e
    comp, e = dc.clean_complaints(raw["complaints"], ids); exc += e
    camp, e = dc.clean_campaigns(raw["campaigns"], ids); exc += e

    copy_dataframe(eng, cust, "telco.customers")
    copy_dataframe(eng, subs, "telco.subscriptions")
    copy_dataframe(eng, tx, "telco.transactions")
    copy_dataframe(eng, rev, "telco.reversals")
    copy_dataframe(eng, usage, "telco.usage_monthly")
    copy_dataframe(eng, comp, "telco.complaints")
    copy_dataframe(eng, camp, "telco.campaigns")
    exc_df = pd.DataFrame(exc, columns=["source_table", "record_key", "issue", "action_taken"])
    copy_dataframe(eng, exc_df, "telco.dq_exceptions")
    run_sql_file(eng, SQL_DIR / "03_views.sql")
    with eng.connect() as c:
        c.execute(text("ANALYZE"))
    summary = {"staged_rows": staged,
               "clean_rows": {"customers": len(cust), "subscriptions": len(subs), "transactions": len(tx), "reversals": len(rev),
                              "usage_monthly": len(usage), "complaints": len(comp), "campaigns": len(camp)},
               "quarantined_transactions": len(tx_q),
               "exceptions_by_issue": exc_df.groupby(["source_table", "issue"]).size().rename("n").reset_index().to_dict("records"),
               "seconds": round(time.time() - t0, 1)}
    out = PROJECT_ROOT / "data" / "processed" / "build_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    s = build()
    print(json.dumps({k: v for k, v in s.items() if k != "exceptions_by_issue"}, indent=2))
    for r in s["exceptions_by_issue"]:
        print(f"  {r['source_table']:<15} {r['issue']:<60} {r['n']:>6}")
