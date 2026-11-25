"""
Synthetic data generator for *Jamii Mobile*, a FICTIONAL Kenyan mobile network operator.

Nothing here describes Safaricom, Airtel, Telkom or any real operator or subscriber. Public telco
datasets were reviewed first (see reports/methodology.md): IBM Telco Customer Churn is a one-quarter
snapshot of a fictional US company, with no monthly history, usage, complaints or campaigns, so it
cannot support cohort or declining-activity analysis.

The simulation runs month by month (Jan 2024 - Oct 2026) over every subscriber:
- Five hidden behavioural archetypes drive usage, spend, service mix and baseline churn risk. They are
  NOT exported to the database; they are written to data/synthetic/raw/_truth_archetypes.csv only to
  evaluate whether the clustering extension recovers real structure.
- Churn is a process, not an event: a subscriber who decides to leave first reduces usage
  (2 months), then goes silent (3 months), and the subscription is closed after 90 days of
  inactivity. This makes "declining activity" a genuine early-warning signal.
- Unresolved complaints, slow resolutions, poor-coverage counties, early tenure and a July 2025
  bundle price increase raise churn risk; accepted win-back offers lower it.
- Controlled data-quality defects are injected into the raw export and counted in a manifest.

    python -m src.generate_data --seed 2027
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "raw"
WINDOW_START = pd.Timestamp("2024-01-01")
N_MONTHS = 34                                   # Jan 2024 .. Oct 2026
MONTHS = pd.date_range(WINDOW_START, periods=N_MONTHS, freq="MS")
PRICE_RISE_MONTH = 18                           # Jul 2025: bundle prices +10%

ARCH = ["Youth data-heavy", "Voice-centric", "Mainstream balanced", "Business", "Low-value occasional"]
ARCH_SHARE = [0.22, 0.20, 0.30, 0.08, 0.20]
#                     data_mb voice  sms  spend  base_hazard  bundles_lambda  dormancy
ARCH_PARAMS = np.array([
    [6000,  60,  30,  650, 0.020, 1.8, 0.02],
    [400,  380,  60,  420, 0.015, 1.2, 0.02],
    [2500, 170,  40,  520, 0.017, 1.5, 0.02],
    [9000, 600,  50, 2400, 0.007, 0.4, 0.01],
    [150,   40,  20,  110, 0.040, 0.6, 0.10],
])
AGE_GROUPS = ["18-24", "25-34", "35-44", "45-54", "55+"]
AGE_BY_ARCH = np.array([
    [0.55, 0.35, 0.07, 0.02, 0.01],
    [0.05, 0.15, 0.25, 0.30, 0.25],
    [0.15, 0.35, 0.28, 0.15, 0.07],
    [0.02, 0.30, 0.38, 0.22, 0.08],
    [0.25, 0.25, 0.20, 0.15, 0.15],
])
COUNTIES = ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Kiambu", "Machakos", "Kakamega",
            "Uasin Gishu", "Kilifi", "Nyeri", "Turkana", "Garissa"]
COUNTY_SHARE = np.array([0.24, 0.10, 0.08, 0.08, 0.10, 0.07, 0.07, 0.06, 0.06, 0.05, 0.045, 0.045])
POOR_COVERAGE = {"Turkana", "Garissa", "Kilifi"}
SERVICES = ["Data Bundle", "Voice Bundle", "SMS Bundle", "Combo Bundle"]
SERVICE_MIX = np.array([
    [0.70, 0.05, 0.03, 0.22],
    [0.10, 0.55, 0.10, 0.25],
    [0.40, 0.20, 0.05, 0.35],
    [0.50, 0.20, 0.00, 0.30],
    [0.30, 0.40, 0.15, 0.15],
])
COMPLAINT_CATS = ["Network coverage", "Data speed", "Billing", "Mobile money", "Customer service", "SIM & device"]
CAT_SHARE = np.array([0.20, 0.20, 0.18, 0.15, 0.15, 0.12])
RESOLVE_DAYS = np.array([12, 7, 2, 5, 3, 2])            # mean days to resolve
UNRESOLVED_P = np.array([0.30, 0.20, 0.06, 0.08, 0.08, 0.05])


def plan_for(arch: int, ctype: str, rng) -> str:
    if ctype == "Postpaid":
        return "Postpaid Business" if arch == 3 else ("Postpaid Premium" if rng.random() < 0.3 else "Postpaid Basic")
    return "Prepaid Data Plus" if arch == 0 or (arch == 2 and rng.random() < 0.4) else "Prepaid Flex"


def build_customers(rng):
    # existing base (acquired 2019-2023, still active on 1 Jan 2024) + monthly acquisitions in the window
    n0 = 13000
    acq_existing = WINDOW_START - pd.to_timedelta(rng.integers(1, 5 * 365, n0), unit="D")
    new_per_month = (430 * np.array([1.0 + (0.35 if m.month == 12 else 0) + (0.15 if m.month in (1, 8) else 0)
                                     for m in MONTHS])).astype(int)
    new_per_month = rng.poisson(new_per_month)
    acq_new = np.concatenate([m + pd.to_timedelta(rng.integers(0, m.days_in_month, k), unit="D")
                              for m, k in zip(MONTHS, new_per_month)])
    acq = pd.DatetimeIndex(np.concatenate([acq_existing.values, acq_new.astype("datetime64[ns]")]))
    n = len(acq)
    arch = rng.choice(5, n, p=ARCH_SHARE)
    ctype = np.where(arch == 3, np.where(rng.random(n) < 0.9, "Postpaid", "Prepaid"),
                     np.where(rng.random(n) < 0.05, "Postpaid", "Prepaid"))
    age = np.array([rng.choice(AGE_GROUPS, p=AGE_BY_ARCH[a]) for a in arch])
    county = rng.choice(COUNTIES, n, p=COUNTY_SHARE / COUNTY_SHARE.sum())
    acq_t = ((acq.year - 2024) * 12 + acq.month - 1).to_numpy()   # month index relative to Jan 2024 (negative = before window)
    df = pd.DataFrame({"customer_id": [f"C{i:06d}" for i in range(1, n + 1)], "acquisition_date": acq.normalize(),
                       "customer_type": ctype, "age_group": age, "county": county, "arch": arch, "acq_t": acq_t,
                       "cust_factor": rng.lognormal(0, 0.35, n)})
    df["plan"] = [plan_for(a, c, rng) for a, c in zip(arch, ctype)]
    return df


def simulate(rng, cust):
    n = len(cust)
    arch = cust["arch"].to_numpy()
    acq_t = cust["acq_t"].to_numpy()
    prepaid = (cust["customer_type"] == "Prepaid").to_numpy()
    poor = cust["county"].isin(POOR_COVERAGE).to_numpy()
    cf = cust["cust_factor"].to_numpy()
    acq_dom = (cust["acquisition_date"].dt.day - 1).to_numpy()
    P = ARCH_PARAMS[arch]

    alive = np.ones(n, bool)
    decline_start = np.full(n, -99)
    churn_t = np.full(n, -1)
    unresolved_until = np.full(n, -1)
    slow_until = np.full(n, -1)
    winback_until = np.full(n, -1)
    upsell_until = np.full(n, -1)

    usage_rows, tx_rows, comp_rows, camp_rows = [], [], [], []
    for t, month in enumerate(MONTHS):
        days = month.days_in_month
        present = alive & (acq_t <= t)
        tenure = t - acq_t
        # ---- churn decision for customers not already leaving ----------------------------------
        h = P[:, 4].copy()
        h *= np.select([tenure < 3, tenure < 12, tenure > 24], [2.0, 1.3, 0.7], 1.0)
        h *= np.where(~prepaid, 0.6, 1.0)
        h *= np.where(unresolved_until >= t, 3.0, 1.0)
        h *= np.where(slow_until >= t, 1.6, 1.0)
        h *= np.where(poor, 1.35, 1.0)
        shock = (t >= PRICE_RISE_MONTH) & (t < PRICE_RISE_MONTH + 4) & prepaid & np.isin(arch, [1, 4])
        h *= np.where(shock, 1.9, 1.0)
        h *= np.where(winback_until >= t, 0.5, 1.0)
        start = present & (decline_start < 0) & (rng.random(n) < h)
        decline_start[start] = t
        d = t - decline_start
        leaving = present & (decline_start >= 0)
        # win-back offers to customers in the first two decline months
        wb = leaving & (d <= 1) & (rng.random(n) < 0.35)
        wb_accept = wb & (rng.random(n) < 0.30)
        for i in np.where(wb)[0]:
            camp_rows.append((cust.customer_id.iat[i], month + pd.Timedelta(days=int(rng.integers(acq_dom[i] if acq_t[i] == t else 0, days))),
                              "Win-back offer", "Accepted" if wb_accept[i] else rng.choice(["Ignored", "Opted out"], p=[0.85, 0.15])))
        decline_start[wb_accept] = -99
        winback_until[wb_accept] = t + 3
        d = np.where(decline_start >= 0, t - decline_start, -1)
        mult = np.select([d == 0, d == 1, d >= 2], [0.6, 0.25, 0.0], 1.0)
        closes = present & (d == 4)
        churn_t[closes] = t
        alive[closes] = False
        # ---- activity -------------------------------------------------------------------------
        dormant = present & (decline_start < 0) & (rng.random(n) < P[:, 6])
        first_month = acq_t == t
        frac = np.where(first_month, 0.6, 1.0)
        act = present & (mult > 0) & ~dormant
        idx = np.where(act)[0]
        k = len(idx)
        m = mult[idx] * frac[idx]
        data = P[idx, 0] * cf[idx] * 1.015 ** t * rng.lognormal(0, 0.35, k) * m
        voice = P[idx, 1] * cf[idx] * 0.995 ** t * rng.lognormal(0, 0.35, k) * m
        sms = P[idx, 2] * cf[idx] ** 0.5 * 0.99 ** t * rng.lognormal(0, 0.4, k) * m
        price = 1.10 if t >= PRICE_RISE_MONTH else 1.0
        spend = P[idx, 3] * cf[idx] ** 0.7 * rng.lognormal(0, 0.25, k) * m ** 0.8 * price * 1.004 ** t
        spend *= np.where(upsell_until[idx] >= t, 1.15, 1.0)
        usage_rows.append(pd.DataFrame({"customer_id": cust.customer_id.to_numpy()[idx], "usage_month": month,
                                        "data_mb": np.round(data, 1), "voice_minutes": np.round(voice, 1),
                                        "sms_count": np.round(sms).astype(int)}))
        # ---- transactions ---------------------------------------------------------------------
        ids = cust.customer_id.to_numpy()[idx]
        is_pre = prepaid[idx]
        nb = np.where(is_pre, 1 + rng.poisson(P[idx, 5]), 1)
        rep = np.repeat(np.arange(k), nb)
        share = rng.gamma(2.0, 1.0, len(rep))
        share = share / np.bincount(rep, weights=share)[rep]
        amt = np.round(spend[rep] * share, 0)
        svc = np.array([SERVICES[rng.choice(4, p=SERVICE_MIX[a])] for a in arch[idx][rep]])
        svc = np.where(is_pre[rep], svc, "Postpaid Bill")
        acq_day = acq_dom[idx]                       # first possible day in the month (0 unless acquired this month)
        lo = np.where(first_month[idx], acq_day, 0)
        tx_rows.append(pd.DataFrame({"customer_id": ids[rep],
                                     "transaction_date": month + pd.to_timedelta(lo[rep] + (rng.random(len(rep)) * (days - lo[rep])).astype(int), unit="D"),
                                     "transaction_amount": np.maximum(amt, 5), "service_type": svc}))
        nm = rng.poisson(np.where(arch[idx] == 4, 0.4, 1.1))
        rep2 = np.repeat(np.arange(k), nm)
        tx_rows.append(pd.DataFrame({"customer_id": ids[rep2],
                                     "transaction_date": month + pd.to_timedelta(lo[rep2] + (rng.random(len(rep2)) * (days - lo[rep2])).astype(int), unit="D"),
                                     "transaction_amount": np.round(rng.uniform(12, 95, len(rep2)), 0),
                                     "service_type": "Mobile Money Fees"}))
        # ---- complaints -----------------------------------------------------------------------
        pc = 0.016 * np.where(poor[idx], 1.8, 1.0) * np.where(arch[idx] == 3, 1.5, 1.0)
        cidx = idx[rng.random(k) < pc]
        for i in cidx:
            w = CAT_SHARE * (np.array([2.2, 1.6, 1, 1, 1, 1]) if poor[i] else 1)
            c = rng.choice(6, p=w / w.sum())
            cdate = month + pd.Timedelta(days=int(rng.integers(acq_dom[i] if acq_t[i] == t else 0, days)))
            r = rng.random()
            if r < UNRESOLVED_P[c]:
                status, rdate = ("Escalated" if rng.random() < 0.25 else "Unresolved"), pd.NaT
                unresolved_until[i] = t + 4
            else:
                status = "Resolved"
                dd = int(np.ceil(rng.gamma(1.5, RESOLVE_DAYS[c] / 1.5)))
                rdate = cdate + pd.Timedelta(days=dd)
                if dd > 10:
                    slow_until[i] = t + 3
            comp_rows.append((cust.customer_id.iat[i], cdate, COMPLAINT_CATS[c], status, rdate))
        # ---- marketing campaigns ---------------------------------------------------------------
        midx = idx[rng.random(k) < 0.05]
        for i in midx:
            ctyp = rng.choice(["Data bonus offer", "Bundle upsell", "Loyalty points"], p=[0.4, 0.35, 0.25])
            pacc = {"Data bonus offer": 0.25, "Bundle upsell": 0.12, "Loyalty points": 0.35}[ctyp]
            acc = rng.random() < pacc
            if acc and ctyp == "Bundle upsell":
                upsell_until[i] = t + 2
            camp_rows.append((cust.customer_id.iat[i], month + pd.Timedelta(days=int(rng.integers(acq_dom[i] if acq_t[i] == t else 0, days))), ctyp,
                              "Accepted" if acc else rng.choice(["Ignored", "Opted out"], p=[0.9, 0.1])))

    usage = pd.concat(usage_rows, ignore_index=True)
    tx = pd.concat(tx_rows, ignore_index=True).sort_values("transaction_date").reset_index(drop=True)
    tx.insert(0, "transaction_id", [f"T{i:08d}" for i in range(1, len(tx) + 1)])
    usage.insert(0, "usage_id", np.arange(1, len(usage) + 1))
    comp = pd.DataFrame(comp_rows, columns=["customer_id", "complaint_date", "complaint_category", "resolution_status", "resolution_date"])
    comp = comp.sort_values("complaint_date").reset_index(drop=True)
    comp.insert(0, "complaint_id", [f"CP{i:06d}" for i in range(1, len(comp) + 1)])
    camp = pd.DataFrame(camp_rows, columns=["customer_id", "campaign_date", "campaign_type", "campaign_response"])
    camp = camp.sort_values("campaign_date").reset_index(drop=True)
    camp.insert(0, "campaign_id", [f"CA{i:06d}" for i in range(1, len(camp) + 1)])
    return usage, tx, comp, camp, churn_t


def build_subscriptions(rng, cust, churn_t, usage):
    last_active = usage.groupby("customer_id")["usage_month"].max()
    rows = []
    sid = 1
    alt = {"Prepaid Flex": "Prepaid Data Plus", "Prepaid Data Plus": "Prepaid Flex",
           "Postpaid Basic": "Postpaid Premium", "Postpaid Premium": "Postpaid Basic", "Postpaid Business": "Postpaid Business"}
    for c, start, plan, ct, at in zip(cust.customer_id, cust.acquisition_date, cust.plan, churn_t, cust.acq_t):
        end_final = None
        if ct >= 0:
            la = last_active.get(c, MONTHS[max(ct - 4, 0)])
            # last activity falls somewhere in the last active month; the line is closed 90 days later
            end_final = (la + pd.Timedelta(days=int(rng.integers(0, 28))) + pd.Timedelta(days=90)).normalize()
            end_final = min(end_final, MONTHS[-1] + pd.offsets.MonthEnd(0))
        cur_start, cur_plan = start, plan
        # plan changes inside the window (about 7% of subscribers a year)
        first_t, last_t = max(at, 0), (ct if ct >= 0 else N_MONTHS - 1)
        for t in range(first_t + 1, last_t):
            if rng.random() < 0.006 and alt[cur_plan] != cur_plan:
                chg = MONTHS[t] + pd.Timedelta(days=int(rng.integers(0, 28)))
                rows.append((f"S{sid:07d}", c, cur_plan, "Plan Changed", cur_start, chg - pd.Timedelta(days=1)))
                sid += 1
                cur_start, cur_plan = chg, alt[cur_plan]
        rows.append((f"S{sid:07d}", c, cur_plan, "Churned" if end_final is not None else "Active", cur_start, end_final))
        sid += 1
    return pd.DataFrame(rows, columns=["subscription_id", "customer_id", "plan_type", "subscription_status", "start_date", "end_date"])


def inject_issues(rng, cust, subs, tx, usage, comp, camp):
    m = {}
    c = cust.copy()
    idx = rng.choice(c.index, int(0.03 * len(c)), replace=False); c.loc[idx, "county"] = None; m["customers_missing_county"] = len(idx)
    idx = rng.choice(c.index, 300, replace=False)
    c.loc[idx, "age_group"] = c.loc[idx, "age_group"].str.replace("-", " - ", regex=False); m["customers_age_label_variants"] = 300
    idx = rng.choice(c.index, 250, replace=False)
    c.loc[idx, "customer_type"] = c.loc[idx, "customer_type"].map(lambda s: rng.choice([s.upper(), s.lower(), s + " "])); m["customers_type_label_variants"] = 250
    c["acquisition_date"] = c["acquisition_date"].dt.strftime("%Y-%m-%d")
    idx = rng.choice(c.index[c.acquisition_date.str.startswith("2026")], 12, replace=False)
    c.loc[idx, "acquisition_date"] = c.loc[idx, "acquisition_date"].str.replace("2026", "2062", n=1); m["customers_future_acquisition_typo"] = 12
    dup = c.sample(80, random_state=1); c = pd.concat([c, dup], ignore_index=True); m["customers_exact_duplicates"] = 80

    x = tx.copy()
    variants = {"Data Bundle": ["data bundle", "DATA BUNDLE", "Data bndl"], "Voice Bundle": ["voice bundle", "VOICE"],
                "Combo Bundle": ["combo", "Combo bundle"], "Mobile Money Fees": ["M-Money fees", "mobile money fees"]}
    idx = rng.choice(x.index, int(0.02 * len(x)), replace=False)
    x.loc[idx, "service_type"] = [rng.choice(variants.get(s, [s])) for s in x.loc[idx, "service_type"]]; m["transactions_service_label_variants"] = len(idx)
    idx = rng.choice(x.index, 30, replace=False); x.loc[idx, "transaction_amount"] *= 1000; m["transactions_amount_x1000"] = 30
    idx = rng.choice(x.index, 45, replace=False); x.loc[idx, "customer_id"] = [f"C99{i:04d}" for i in range(45)]; m["transactions_orphan_customer"] = 45
    rev = x.sample(int(0.002 * len(x)), random_state=2).copy()
    rev["transaction_amount"] = -rev["transaction_amount"]
    rev["transaction_id"] = [f"R{i:08d}" for i in range(1, len(rev) + 1)]
    x = pd.concat([x, rev], ignore_index=True); m["transactions_reversals"] = len(rev)
    dup = x.sample(int(0.003 * len(x)), random_state=3); x = pd.concat([x, dup], ignore_index=True); m["transactions_exact_duplicates"] = len(dup)

    u = usage.copy()
    idx = rng.choice(u.index, 25, replace=False); u.loc[idx, "data_mb"] = -u.loc[idx, "data_mb"]; m["usage_negative_data"] = 25
    idx = rng.choice(u.index, 20, replace=False); u.loc[idx, "data_mb"] = 999999999; m["usage_meter_sentinel"] = 20
    dup = u.sample(int(0.002 * len(u)), random_state=4); u = pd.concat([u, dup], ignore_index=True); m["usage_exact_duplicates"] = len(dup)

    cp = comp.copy()
    res = cp.index[cp.resolution_date.notna()]
    idx = rng.choice(res, 30, replace=False)
    cp.loc[idx, "resolution_date"] = cp.loc[idx, "complaint_date"] - pd.to_timedelta(rng.integers(1, 5, 30), unit="D"); m["complaints_resolution_before_complaint"] = 30
    idx = rng.choice(cp.index, 120, replace=False)
    cp.loc[idx, "complaint_category"] = cp.loc[idx, "complaint_category"].str.lower(); m["complaints_category_case"] = 120
    idx = rng.choice(cp.index, 90, replace=False)
    cp.loc[idx, "resolution_status"] = cp.loc[idx, "resolution_status"].str.upper(); m["complaints_status_case"] = 90

    ca = camp.copy()
    idx = rng.choice(ca.index, int(0.02 * len(ca)), replace=False); ca.loc[idx, "campaign_response"] = None; m["campaigns_missing_response"] = len(idx)
    return c, subs, x, u, cp, ca, m


def main(seed: int = 2027) -> dict:
    rng = np.random.default_rng(seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cust = build_customers(rng)
    usage, tx, comp, camp, churn_t = simulate(rng, cust)
    subs = build_subscriptions(rng, cust, churn_t, usage)
    cust[["customer_id", "arch"]].assign(archetype=lambda d: d.arch.map(dict(enumerate(ARCH)))).drop(columns="arch") \
        .to_csv(OUT_DIR / "_truth_archetypes.csv", index=False)
    cust_out = cust[["customer_id", "age_group", "county", "acquisition_date", "customer_type"]]
    c, s, x, u, cp, ca, manifest = inject_issues(rng, cust_out, subs, tx, usage, comp, camp)
    c.to_csv(OUT_DIR / "customers.csv", index=False)
    s.to_csv(OUT_DIR / "subscriptions.csv", index=False, date_format="%Y-%m-%d")
    x.to_csv(OUT_DIR / "transactions.csv", index=False, date_format="%Y-%m-%d")
    u.to_csv(OUT_DIR / "usage_monthly.csv", index=False, date_format="%Y-%m-%d")
    cp.to_csv(OUT_DIR / "complaints.csv", index=False, date_format="%Y-%m-%d")
    ca.to_csv(OUT_DIR / "campaigns.csv", index=False, date_format="%Y-%m-%d")
    manifest.update({"seed": seed, "window": [str(MONTHS[0].date()), str(MONTHS[-1].date())],
                     "clean_row_counts": {"customers": len(cust), "subscriptions": len(subs), "transactions": len(tx),
                                          "usage_monthly": len(usage), "complaints": len(comp), "campaigns": len(camp)},
                     "churned_in_window": int((churn_t >= 0).sum()),
                     "note": "Synthetic data for a fictional operator. Counts above describe injected issues."})
    (OUT_DIR / "injection_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2027)
    out = main(ap.parse_args().seed)
    print(json.dumps(out["clean_row_counts"], indent=2), "churned:", out["churned_in_window"])
