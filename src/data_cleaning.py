"""Cleaning rules for the Jamii Mobile raw export.

Rule of thumb: fix only what can be fixed with certainty (using another trusted field where one
exists), quarantine what would need a guess, and log every action to telco.dq_exceptions.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

WINDOW_END = pd.Timestamp("2026-10-31")
SERVICE_TYPES = ["Data Bundle", "Voice Bundle", "SMS Bundle", "Combo Bundle", "Mobile Money Fees", "Postpaid Bill"]
SERVICE_ALIASES = {"data bndl": "Data Bundle", "voice": "Voice Bundle", "combo": "Combo Bundle",
                   "m-money fees": "Mobile Money Fees"}
COMPLAINT_CATEGORIES = ["Network coverage", "Data speed", "Billing", "Mobile money", "Customer service", "SIM & device"]
# No bundle or postpaid bill in the data exceeds ~13,500 KES; values above this are keying/system errors (x1000 pattern).
MAX_PLAUSIBLE_AMOUNT = 25_000
# Mobile money fees follow a published tariff (highest fee in the data: KES 95), so a much
# lower ceiling applies: a KES 13 fee keyed x1000 is 13,000 and would pass the general limit.
SERVICE_MAX_AMOUNT = {"Mobile Money Fees": 1_000}
METER_SENTINEL = 999_999_999

Exc = list[tuple[str, str, str, str]]


def _key(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def drop_exact_duplicates(df: pd.DataFrame, key: str | list[str], table: str, exc: Exc) -> pd.DataFrame:
    dup = df.duplicated(keep="first")
    keys = df.loc[dup, key] if isinstance(key, str) else df.loc[dup, key].astype(str).agg("|".join, axis=1)
    exc += [(table, str(k), "exact duplicate row", "removed duplicate copy") for k in keys]
    out = df[~dup].copy()
    if out.duplicated(subset=key if isinstance(key, list) else [key], keep=False).any():
        raise ValueError(f"{table}: conflicting rows share a key")
    return out


def normalise_label(value, canonical: list[str], aliases: dict | None = None):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    k = _key(value)
    lookup = {_key(c): c for c in canonical}
    lookup.update(aliases or {})
    return lookup.get(k)


def clean_customers(raw: pd.DataFrame, subs_raw: pd.DataFrame) -> tuple[pd.DataFrame, Exc]:
    exc: Exc = []
    df = drop_exact_duplicates(raw, "customer_id", "customers", exc)
    age = df["age_group"].str.replace(" ", "", regex=False)
    for k in df.loc[age != df["age_group"], "customer_id"]:
        exc.append(("customers", k, "age group label with spaces", "standardised"))
    df["age_group"] = age
    ct = df["customer_type"].map(lambda v: normalise_label(v, ["Prepaid", "Postpaid"]))
    if ct.isna().any():
        raise ValueError("unmapped customer_type")
    for k in df.loc[ct != df["customer_type"], "customer_id"]:
        exc.append(("customers", k, "customer type label variant", "standardised"))
    df["customer_type"] = ct
    acq = pd.to_datetime(df["acquisition_date"], errors="coerce")
    first_sub = pd.to_datetime(subs_raw["start_date"]).groupby(subs_raw["customer_id"]).min()
    bad = acq.isna() | (acq > WINDOW_END)
    # The first subscription start date is the activation date recorded by the billing system,
    # so it is a trustworthy replacement for a mistyped acquisition date.
    acq[bad] = df.loc[bad, "customer_id"].map(first_sub)
    df["acquisition_date_corrected"] = bad
    for k in df.loc[bad, "customer_id"]:
        exc.append(("customers", k, "acquisition date outside data range (year typo)", "replaced with first subscription start"))
    df["acquisition_date"] = acq.dt.date
    for k in df.loc[df["county"].isna(), "customer_id"]:
        exc.append(("customers", k, "missing county", "left NULL (reported as Unknown)"))
    return df, exc


def clean_subscriptions(raw: pd.DataFrame, valid_customers: set) -> tuple[pd.DataFrame, Exc]:
    exc: Exc = []
    df = drop_exact_duplicates(raw, "subscription_id", "subscriptions", exc)
    df = df[df["customer_id"].isin(valid_customers)].copy()
    for c in ["start_date", "end_date"]:
        df[c] = pd.to_datetime(df[c]).dt.date
    return df, exc


def clean_transactions(raw: pd.DataFrame, valid_customers: set) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Exc]:
    """Returns (purchases, reversals, quarantined, exceptions)."""
    exc: Exc = []
    df = drop_exact_duplicates(raw, "transaction_id", "transactions", exc)
    df["transaction_amount"] = pd.to_numeric(df["transaction_amount"])
    df["transaction_date"] = pd.to_datetime(df["transaction_date"]).dt.date
    svc = df["service_type"].map(lambda v: normalise_label(v, SERVICE_TYPES, SERVICE_ALIASES))
    if svc.isna().any():
        raise ValueError(f"unmapped service types: {df.loc[svc.isna(), 'service_type'].unique()[:5]}")
    for k in df.loc[svc != df["service_type"], "transaction_id"]:
        exc.append(("transactions", k, "service type label variant", "mapped to canonical service"))
    df["service_type"] = svc
    orphan = ~df["customer_id"].isin(valid_customers)
    cap = df["service_type"].map(SERVICE_MAX_AMOUNT).fillna(MAX_PLAUSIBLE_AMOUNT)
    too_big = df["transaction_amount"].abs() > cap
    for mask, issue in [(orphan, "customer_id not in customer master"),
                        (too_big, "amount above service plausibility limit (x1000 keying pattern)")]:
        exc += [("transactions", k, issue, "quarantined") for k in df.loc[mask, "transaction_id"]]
    q = df[orphan | too_big]
    df = df[~(orphan | too_big)]
    neg = df["transaction_amount"] < 0
    rev = df[neg].rename(columns={"transaction_amount": "reversal_amount"}).copy()
    rev["reversal_amount"] = -rev["reversal_amount"]
    exc += [("transactions", k, "negative amount (reversal)", "moved to telco.reversals") for k in rev["transaction_id"]]
    return df[~neg].copy(), rev, q, exc


def clean_usage(raw: pd.DataFrame, valid_customers: set) -> tuple[pd.DataFrame, Exc]:
    exc: Exc = []
    df = drop_exact_duplicates(raw, "usage_id", "usage_monthly", exc)
    df = df.drop_duplicates(subset=["customer_id", "usage_month"], keep="first")
    for c in ["data_mb", "voice_minutes"]:
        df[c] = pd.to_numeric(df[c])
    df["sms_count"] = pd.to_numeric(df["sms_count"]).astype(int)
    df["usage_id"] = df["usage_id"].astype(int)
    df["usage_month"] = pd.to_datetime(df["usage_month"]).dt.date
    bad = (df["data_mb"] < 0) | (df["data_mb"] >= METER_SENTINEL)
    for k, v in zip(df.loc[bad, "usage_id"], df.loc[bad, "data_mb"]):
        exc.append(("usage_monthly", str(k), "negative data reading" if v < 0 else "meter sentinel value 999999999",
                    "data_mb set to NULL (row kept: voice/SMS valid)"))
    df.loc[bad, "data_mb"] = np.nan
    return df[df["customer_id"].isin(valid_customers)], exc


def clean_complaints(raw: pd.DataFrame, valid_customers: set) -> tuple[pd.DataFrame, Exc]:
    exc: Exc = []
    df = drop_exact_duplicates(raw, "complaint_id", "complaints", exc)
    cat = df["complaint_category"].map(lambda v: normalise_label(v, COMPLAINT_CATEGORIES))
    st = df["resolution_status"].map(lambda v: normalise_label(v, ["Resolved", "Unresolved", "Escalated"]))
    if cat.isna().any() or st.isna().any():
        raise ValueError("unmapped complaint labels")
    exc += [("complaints", k, "category label case", "standardised") for k in df.loc[cat != df["complaint_category"], "complaint_id"]]
    exc += [("complaints", k, "status label case", "standardised") for k in df.loc[st != df["resolution_status"], "complaint_id"]]
    df["complaint_category"], df["resolution_status"] = cat, st
    cd = pd.to_datetime(df["complaint_date"])
    rd = pd.to_datetime(df["resolution_date"])
    before = rd < cd
    exc += [("complaints", k, "resolution date before complaint date", "resolution_date set to NULL; status kept")
            for k in df.loc[before, "complaint_id"]]
    rd[before] = pd.NaT
    df["complaint_date"], df["resolution_date"] = cd.dt.date, rd.dt.date
    return df[df["customer_id"].isin(valid_customers)], exc


def clean_campaigns(raw: pd.DataFrame, valid_customers: set) -> tuple[pd.DataFrame, Exc]:
    exc: Exc = []
    df = drop_exact_duplicates(raw, "campaign_id", "campaigns", exc)
    miss = df["campaign_response"].isna()
    exc += [("campaigns", k, "missing response", "set to 'Unknown'") for k in df.loc[miss, "campaign_id"]]
    df["campaign_response"] = df["campaign_response"].fillna("Unknown")
    df["campaign_date"] = pd.to_datetime(df["campaign_date"]).dt.date
    return df[df["customer_id"].isin(valid_customers)], exc
