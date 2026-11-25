"""Database connection and bulk-loading helpers.

Credentials come from environment variables (see .env.example), never from code.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "synthetic" / "raw"
SQL_DIR = PROJECT_ROOT / "sql"
TABLES = ["customers", "subscriptions", "transactions", "usage_monthly", "complaints", "campaigns"]


def _load_dotenv() -> None:
    """Minimal .env reader so python-dotenv is not a required dependency."""
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_engine(database: str | None = None) -> Engine:
    _load_dotenv()
    user = os.getenv("PGUSER", "postgres")
    pwd = os.getenv("PGPASSWORD", "")
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    db = database or os.getenv("PGDATABASE", "telecom_cva")
    auth = f"{user}:{pwd}@" if pwd else f"{user}@"
    return create_engine(f"postgresql+psycopg2://{auth}{host}:{port}/{db}")


def run_sql_file(engine: Engine, path: Path) -> None:
    """Execute a SQL script containing several statements."""
    sql = Path(path).read_text()
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(sql)
        raw.commit()
    finally:
        raw.close()


def copy_dataframe(engine: Engine, df: pd.DataFrame, table: str, columns: list[str] | None = None) -> int:
    """Fast bulk insert using PostgreSQL COPY (much faster than DataFrame.to_sql for ~1M rows)."""
    columns = columns or list(df.columns)
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(
                f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
        raw.commit()
    finally:
        raw.close()
    return len(df)


def load_raw_to_staging(engine: Engine, raw_dir: Path = RAW_DIR) -> dict[str, int]:
    """COPY every raw CSV into the TEXT-typed staging schema unchanged."""
    counts = {}
    for t in TABLES:
        df = pd.read_csv(raw_dir / f"{t}.csv", dtype=str, keep_default_na=False, na_values=[""])
        counts[t] = copy_dataframe(engine, df, f"staging.{t}")
    return counts


def read_table(engine: Engine, table: str) -> pd.DataFrame:
    return pd.read_sql(text(f"SELECT * FROM {table}"), engine)


def query(engine: Engine, sql: str, **params) -> pd.DataFrame:
    return pd.read_sql(text(sql), engine, params=params)
