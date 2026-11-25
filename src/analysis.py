"""Reusable analysis helpers: chart style, data access and telecom metric definitions.

Metric functions mirror sql/03_views.sql; tests/test_transformations.py checks them.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.data_loader import PROJECT_ROOT, get_engine, query

FIG_DIR = PROJECT_ROOT / "reports" / "figures"

# Colour roles (validated categorical palette, light mode). Charts use colour sparingly:
# one primary series, one highlight for "the thing the chart is about", grey for context.
PRIMARY = "#2a78d6"     # blue
HIGHLIGHT = "#eb6834"   # orange
SECOND = "#1baf7a"      # aqua
CONTEXT = "#b9b8b0"     # grey for de-emphasised marks
INK = "#2b2b29"
INK_MUTED = "#6b6a64"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ_BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def set_style() -> None:
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.labelcolor": INK_MUTED, "axes.edgecolor": "#d8d7d0", "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#ecebe6", "grid.linewidth": 0.8, "axes.axisbelow": True,
        "xtick.color": INK_MUTED, "ytick.color": INK_MUTED, "text.color": INK,
        "axes.prop_cycle": mpl.cycler(color=SERIES), "lines.linewidth": 2,
        "legend.frameon": False,
    })


def kes(x: float, digits: int = 1) -> str:
    """Human-readable KES amount: 489.6M, 1.7K."""
    for div, suf in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(x) >= div:
            return f"KES {x / div:.{digits}f}{suf}"
    return f"KES {x:,.0f}"


def kes_axis(ax, axis: str = "y", unit: str = "M") -> None:
    div = {"M": 1e6, "K": 1e3}[unit]
    fmt = mpl.ticker.FuncFormatter(lambda v, _: f"{v / div:,.0f}{unit}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def save(fig, name: str) -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / f"{name}.png"
    fig.savefig(path)
    return path


# ---------------------------------------------------------------------------
# Metric definitions (same as the SQL semantic layer)
# ---------------------------------------------------------------------------
def churn_rate(churned: float, opening_base: float) -> float:
    """Monthly churn rate = lines closed in the month / lines open on day 1 of the month."""
    return np.nan if opening_base == 0 else churned / opening_base


def arpu(revenue: float, active_customers: float) -> float:
    """ARPU = revenue in the period / active customers in the period."""
    return np.nan if active_customers == 0 else revenue / active_customers


def retention_matrix(customer_months: pd.DataFrame, max_k: int = 24, last_month: str = "2026-10-01") -> pd.DataFrame:
    """Cohort x months-since-acquisition retention (%), fixed denominator = cohort size.

    customer_months needs columns customer_id, cohort_month, month, is_active (one row per customer-month).
    Cells whose calendar month falls after `last_month` are NaN (not observed), never 0.
    """
    cm = customer_months.copy()
    cm["cohort_month"] = pd.to_datetime(cm["cohort_month"]); cm["month"] = pd.to_datetime(cm["month"])
    cm["k"] = (cm["month"].dt.year - cm["cohort_month"].dt.year) * 12 + cm["month"].dt.month - cm["cohort_month"].dt.month
    size = cm.groupby("cohort_month")["customer_id"].nunique()
    act = cm[cm["is_active"]].groupby(["cohort_month", "k"])["customer_id"].nunique().unstack(fill_value=0)
    act = act.reindex(columns=range(max_k + 1), fill_value=0)
    out = act.div(size, axis=0) * 100
    lm = pd.Timestamp(last_month)
    for c in out.index:
        for k in out.columns:
            if c + pd.DateOffset(months=int(k)) > lm:
                out.loc[c, k] = np.nan
    return out


def simple_clv(avg_monthly_margin: float, monthly_churn: float, monthly_discount: float = 0.01) -> float:
    """Simple CLV: margin x expected lifetime, discounted. CLV = m * (1 + d) / (d + churn)."""
    return avg_monthly_margin * (1 + monthly_discount) / (monthly_discount + monthly_churn)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def sql_output(name: str) -> pd.DataFrame:
    """Read a saved SQL result produced by `python -m src.run_sql`."""
    import glob
    hits = glob.glob(str(PROJECT_ROOT / "reports" / "sql_outputs" / f"{name}*.csv"))
    return pd.read_csv(sorted(hits)[0])
