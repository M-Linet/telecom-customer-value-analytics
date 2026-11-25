"""Unit tests for the cleaning rules and metric definitions. No database needed."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import analysis as A  # noqa: E402
from src import data_cleaning as dc  # noqa: E402


# ---------------------------------------------------------------- labels
@pytest.mark.parametrize("raw,expected", [
    ("Data Bundle", "Data Bundle"), ("  data   bundle ", "Data Bundle"), ("DATA BUNDLE", "Data Bundle"),
    ("data bndl", "Data Bundle"), ("voice", "Voice Bundle"), ("combo", "Combo Bundle"),
])
def test_service_label_normalisation(raw, expected):
    assert dc.normalise_label(raw, dc.SERVICE_TYPES, dc.SERVICE_ALIASES) == expected


def test_unknown_label_returns_none():
    assert dc.normalise_label("Roaming Pack", dc.SERVICE_TYPES, dc.SERVICE_ALIASES) is None
    assert dc.normalise_label(np.nan, dc.SERVICE_TYPES) is None


# ---------------------------------------------------------------- customers
def _customers():
    raw = pd.DataFrame({
        "customer_id": ["C1", "C2", "C3", "C3"],
        "customer_type": ["prepaid", "POSTPAID", "Prepaid", "Prepaid"],
        "age_group": ["18 - 24", "25-34", "35-44", "35-44"],
        "county": ["Nairobi", None, "Kisumu", "Kisumu"],
        "acquisition_date": ["2024-03-05", "2062-01-10", "2025-07-01", "2025-07-01"],
    })
    subs = pd.DataFrame({"customer_id": ["C1", "C2", "C3"], "start_date": ["2024-03-05", "2026-01-10", "2025-07-01"]})
    return dc.clean_customers(raw, subs)


def test_customer_duplicates_removed_and_labels_standardised():
    df, exc = _customers()
    assert list(df["customer_id"]) == ["C1", "C2", "C3"]
    assert set(df["customer_type"]) == {"Prepaid", "Postpaid"}
    assert df.loc[df.customer_id == "C1", "age_group"].item() == "18-24"
    assert any(e[2] == "exact duplicate row" for e in exc)


def test_acquisition_year_typo_replaced_by_first_subscription():
    df, exc = _customers()
    row = df[df.customer_id == "C2"].iloc[0]
    assert str(row["acquisition_date"]) == "2026-01-10"
    assert bool(row["acquisition_date_corrected"]) is True
    assert not df.loc[df.customer_id != "C2", "acquisition_date_corrected"].any()


def test_missing_county_kept_null_and_logged():
    df, exc = _customers()
    assert df.loc[df.customer_id == "C2", "county"].isna().item()
    assert any(e[1] == "C2" and e[2] == "missing county" for e in exc)


# ---------------------------------------------------------------- transactions
def test_transactions_split_into_purchases_reversals_quarantine():
    raw = pd.DataFrame({
        "transaction_id": ["T1", "T2", "T3", "T4", "T4"],
        "customer_id": ["C1", "C1", "C9", "C1", "C1"],
        "transaction_date": ["2025-01-02"] * 5,
        "service_type": ["data bndl", "Voice Bundle", "SMS Bundle", "Combo Bundle", "Combo Bundle"],
        "transaction_amount": ["250", "-100", "50", "199000", "199000"],
    })
    ok, rev, q, exc = dc.clean_transactions(raw, {"C1"})
    assert list(ok["transaction_id"]) == ["T1"]
    assert ok["service_type"].item() == "Data Bundle"
    assert rev["reversal_amount"].item() == 100          # stored positive in telco.reversals
    assert set(q["transaction_id"]) == {"T3", "T4"}      # orphan customer + x1000 keying error
    assert sum(e[2] == "exact duplicate row" for e in exc) == 1


def test_amount_threshold_is_inclusive_of_real_postpaid_bills():
    raw = pd.DataFrame({"transaction_id": ["T1"], "customer_id": ["C1"], "transaction_date": ["2025-01-02"],
                        "service_type": ["Postpaid Bill"], "transaction_amount": [str(dc.MAX_PLAUSIBLE_AMOUNT)]})
    ok, _, q, _ = dc.clean_transactions(raw, {"C1"})
    assert len(ok) == 1 and q.empty


def test_mobile_money_fee_keying_error_caught_by_service_limit():
    raw = pd.DataFrame({"transaction_id": ["T1", "T2"], "customer_id": ["C1", "C1"], "transaction_date": ["2025-01-02"] * 2,
                        "service_type": ["Mobile Money Fees", "Voice Bundle"], "transaction_amount": ["13000", "13000"]})
    ok, _, q, _ = dc.clean_transactions(raw, {"C1"})
    assert list(q["transaction_id"]) == ["T1"] and list(ok["transaction_id"]) == ["T2"]


# ---------------------------------------------------------------- usage & complaints & campaigns
def test_usage_sentinel_and_negative_set_to_null_row_kept():
    raw = pd.DataFrame({"usage_id": ["1", "2", "3", "4"], "customer_id": ["C1", "C1", "C1", "C1"],
                        "usage_month": ["2025-01-01", "2025-02-01", "2025-03-01", "2025-03-01"],
                        "data_mb": ["4000", "999999999", "-20", "-20"], "voice_minutes": ["100", "90", "80", "80"],
                        "sms_count": ["10", "11", "12", "12"]})
    df, exc = dc.clean_usage(raw, {"C1"})
    assert len(df) == 3
    assert df["data_mb"].isna().sum() == 2
    assert df["voice_minutes"].notna().all()


def test_resolution_before_complaint_is_nulled():
    raw = pd.DataFrame({"complaint_id": ["K1", "K2"], "customer_id": ["C1", "C1"],
                        "complaint_date": ["2025-05-10", "2025-05-10"], "resolution_date": ["2025-05-08", "2025-05-12"],
                        "complaint_category": ["network coverage", "Billing"], "resolution_status": ["RESOLVED", "Resolved"]})
    df, exc = dc.clean_complaints(raw, {"C1"})
    assert pd.isna(df.loc[df.complaint_id == "K1", "resolution_date"].item())
    assert df.loc[df.complaint_id == "K1", "complaint_category"].item() == "Network coverage"
    assert set(df["resolution_status"]) == {"Resolved"}


def test_missing_campaign_response_becomes_unknown():
    raw = pd.DataFrame({"campaign_id": ["P1", "P2"], "customer_id": ["C1", "C1"], "campaign_date": ["2025-01-01"] * 2,
                        "campaign_type": ["Bundle upsell"] * 2, "campaign_response": ["Accepted", None]})
    df, exc = dc.clean_campaigns(raw, {"C1"})
    assert list(df["campaign_response"]) == ["Accepted", "Unknown"]


# ---------------------------------------------------------------- metrics
def test_churn_rate_and_arpu():
    assert A.churn_rate(15, 1000) == pytest.approx(0.015)
    assert np.isnan(A.churn_rate(3, 0))
    assert A.arpu(93_453, 100) == pytest.approx(934.53)
    assert np.isnan(A.arpu(10, 0))


def test_simple_clv_formula():
    # m * (1 + d) / (d + churn): 100 * 1.01 / 0.03
    assert A.simple_clv(100, 0.02, 0.01) == pytest.approx(3366.67, rel=1e-4)
    assert A.simple_clv(100, 0.01) > A.simple_clv(100, 0.02)  # lower churn => higher value


def test_retention_matrix_fixed_denominator_and_unobserved_cells():
    cm = pd.DataFrame({
        "customer_id": ["A", "A", "A", "B", "B", "B", "C"],
        "cohort_month": ["2026-08-01"] * 6 + ["2026-10-01"],
        "month": ["2026-08-01", "2026-09-01", "2026-10-01", "2026-08-01", "2026-09-01", "2026-10-01", "2026-10-01"],
        "is_active": [True, True, True, True, False, False, True],
    })
    m = A.retention_matrix(cm, max_k=3, last_month="2026-10-01")
    aug = m.loc[pd.Timestamp("2026-08-01")]
    assert aug[0] == 100 and aug[1] == 50 and aug[2] == 50      # B leaving does not shrink the denominator
    assert np.isnan(aug[3])                                    # Nov 2026 not observed -> NaN, not 0
    assert np.isnan(m.loc[pd.Timestamp("2026-10-01"), 1])
