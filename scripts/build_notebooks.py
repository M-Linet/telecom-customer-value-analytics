"""Write and execute the eight analysis notebooks.

    python scripts/build_notebooks.py            # write + execute
    python scripts/build_notebooks.py --no-run
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import nbformat as nbf

NB_DIR = Path(__file__).resolve().parents[1] / "notebooks"
SETUP = """import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path.cwd().parent))
import numpy as np, pandas as pd, matplotlib.pyplot as plt, seaborn as sns
from src.data_loader import get_engine, query, PROJECT_ROOT
from src import analysis as an
an.set_style()
pd.set_option("display.float_format", "{:,.2f}".format); pd.set_option("display.max_columns", 30)
engine = get_engine()
o = an.sql_output"""


def md(s): return nbf.v4.new_markdown_cell(s.strip())
def code(s): return nbf.v4.new_code_cell(s.strip())


NB = {}
NB["01_customer_data_understanding"] = [
    md("""# 01 · Customer data understanding
**Company:** *Jamii Mobile*, a **fictional** Kenyan mobile operator. All subscriber data is **synthetic** (`src/generate_data.py`).
It does not describe Safaricom, Airtel, Telkom or any real customer.

Why synthetic? The usual public option, the IBM Telco Churn dataset, is a single-quarter snapshot of a fictional US company. It has no monthly history, so cohorts, monthly active users and declining activity can't be measured from it, and it has no usage, complaint or campaign data."""),
    code(SETUP),
    code("""counts = query(engine, \"\"\"
SELECT 'customers' t, COUNT(*) n, 'one subscriber (SIM/account)' grain FROM telco.customers
UNION ALL SELECT 'subscriptions', COUNT(*), 'one plan period; open row = current plan' FROM telco.subscriptions
UNION ALL SELECT 'transactions', COUNT(*), 'one purchase: bundle, mobile-money fee or postpaid bill' FROM telco.transactions
UNION ALL SELECT 'reversals', COUNT(*), 'one refunded purchase' FROM telco.reversals
UNION ALL SELECT 'usage_monthly', COUNT(*), 'one customer x calendar month of usage' FROM telco.usage_monthly
UNION ALL SELECT 'complaints', COUNT(*), 'one complaint ticket' FROM telco.complaints
UNION ALL SELECT 'campaigns', COUNT(*), 'one marketing contact' FROM telco.campaigns
UNION ALL SELECT 'mv_customer_month', COUNT(*), 'derived: one row per subscribed customer per month' FROM telco.mv_customer_month\"\"\")
counts"""),
    md("""## Why a customer-month grid?
Retention questions are about months in which **nothing happened**. Transaction and usage tables only hold rows when something *did* happen. `telco.mv_customer_month` creates a row for every month a line was open, from acquisition (or Jan 2024) to closure. A silent month is therefore a row with zero activity, not a missing row. Churn rates, ARPU, cohorts and the engagement trend are all computed from this grid."""),
    code("query(engine, 'SELECT * FROM telco.mv_customer_month ORDER BY customer_id, month LIMIT 8')"),
    code("""query(engine, \"\"\"SELECT customer_type, COUNT(*) customers, MIN(acquisition_date) first_acq, MAX(acquisition_date) last_acq,
  ROUND(100.0*AVG((acquisition_date < DATE '2024-01-01')::int),1) AS pct_acquired_before_window FROM telco.customers GROUP BY 1\"\"\")"""),
    md("""## Key definitions (from `sql/03_views.sql`)
| Term | Definition |
|---|---|
| Active in month | ≥1 purchase **or** any data/voice/SMS usage |
| Churned | line closed by the operator (`subscription_status = 'Churned'`), which happens **90 days after the last activity**, so churn is recorded about 3–4 months after the customer stopped |
| Monthly churn rate | lines closed in month *m* ÷ lines open on the 1st of *m* |
| ARPU | revenue in *m* ÷ active customers in *m* |
| Cohort retention | active in month *c+k* ÷ cohort size (fixed denominator); unobserved cells are blank |

Because of the 90-day closure rule, **no lines close in Jan–Apr 2024**: those customers were still inside their 90 days. Churn rates are therefore summarised from May 2024."""),
]

NB["02_data_quality_and_cleaning"] = [
    md("# 02 · Data quality and cleaning\nProfile the raw staging tables, choose a rule for each problem, apply it in `src/data_cleaning.py`, and prove the result."),
    code(SETUP),
    code("o('dq_a01_row_counts').assign(extra=lambda d: d.raw_rows - d.distinct_keys)"),
    code("o('dq_a02_label_variants').query('field != \"age_group\" or n < 400')"),
    md("Labels such as `data bundle`, `Data bndl` and `DATA BUNDLE` would split *Data Bundle* revenue into several bars. Each is mapped to a canonical list, and the build **stops** if a label can't be mapped, rather than silently creating a new category."),
    code("o('dq_a04_amount_profile')"),
    md("""Legitimate purchases top out around KES 12,300 (large postpaid bills). Everything above 25,000 follows a ×1000 keying pattern. But a single ceiling is not enough: the 15,001–25,000 band holds two rows, and they are **mobile money fees**."""),
    code("o('dq_a04b_amount_by_service')"),
    md("""Mobile money fees follow a tariff and never exceed KES 95, so a KES 13,000 or 22,000 fee is a KES 13–22 fee keyed ×1000. The rule is therefore **per service**: fees above KES 1,000 and anything above KES 25,000 are **quarantined**. My first version used only the 25,000 ceiling and let three of these through; checking each service's range caught them. Negative amounts are **reversals**: they go to `telco.reversals` instead of being netted silently against revenue."""),
    code("pd.concat([o('dq_a05_usage_anomalies'), o('dq_a06_date_logic').set_index('check_name').T.reset_index(drop=True)], axis=1)"),
    md("""| Problem | Rule | Why |
|---|---|---|
| Acquisition year typed as 2062 | replace with the first subscription start date | billing activation is a trusted second source, so this is a certain fix, not a guess |
| Negative or 999,999,999 data readings | set `data_mb` to NULL, keep the row | voice and SMS in the same row are valid; the month still counts as active |
| Resolution date before complaint date | set resolution date to NULL, keep status | resolution time is unknowable, but the complaint itself is real |
| Missing campaign response | `Unknown` | so the share without a response stays visible |
| Missing county (3%) | NULL → reported as *Unknown* | imputing a county would be a guess |"""),
    code("o('dq_b03_exception_log')"),
    md("## Proof: clean-layer checks (all must be 0)"),
    code("""chk = o('dq_b01_integrity_summary'); assert chk.failures.sum() == 0, chk; chk"""),
    code("o('dq_b02_grid_reconciliation')"),
    md("Revenue in the customer-month grid equals revenue in the transactions table to the shilling, and every usage row lands in exactly one grid cell. Downstream ARPU and churn figures therefore rest on complete data."),
]

NB["03_customer_exploration"] = [
    md("# 03 · Customer exploration\nWho the subscribers are, and how spend is distributed."),
    code(SETUP),
    code("""cs = query(engine, "SELECT * FROM telco.v_customer_summary")
for c in ["avg_monthly_revenue", "revenue", "early_monthly_revenue", "avg_data_mb", "avg_voice_minutes"]:
    cs[c] = cs[c].astype(float)
cs.groupby("customer_type").avg_monthly_revenue.describe(percentiles=[.25, .5, .75, .95])"""),
    code("""fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
for t, col in [("Prepaid", an.PRIMARY), ("Postpaid", an.HIGHLIGHT)]:
    d = cs[(cs.customer_type == t) & (cs.avg_monthly_revenue > 0)].avg_monthly_revenue
    ax[0].hist(d, bins=np.logspace(1, 4, 50), color=col, alpha=.75, label=t)
ax[0].set_xscale("log"); ax[0].set_xlabel("Average monthly revenue per customer, KES (log)"); ax[0].set_ylabel("Customers")
ax[0].set_title("Spend is right-skewed; postpaid sits an order of magnitude higher"); ax[0].legend()
v = o("q05_value_segments").query("value_segment != 'Unsegmented (too new)'")
ax[1].bar(v.value_segment.str.split(" ").str[0], v.customer_share_pct, color=an.CONTEXT, width=.4, label="Share of customers", align="edge")
ax[1].bar(v.value_segment.str.split(" ").str[0], v.revenue_share_pct, color=an.PRIMARY, width=-.4, label="Share of revenue", align="edge")
ax[1].set_ylabel("%"); ax[1].set_title("Top 10% of customers bring ~36% of revenue"); ax[1].legend(); ax[1].grid(axis="x", visible=False)
fig.tight_layout(); an.save(fig, "spend_distribution_and_value_concentration");"""),
    code("o('q05_value_segments')"),
    md("""Value segments are deciles of **early** monthly revenue: the first three full months we observe each customer. A segment based on *lifetime* average revenue would be circular, because customers on their way out spend less, so churners would be labelled low-value *because* they churned. Using early behaviour, the segment is something the business could have known in advance."""),
    code("""fig, ax = plt.subplots(figsize=(9, 3.4))
cnt = cs.groupby(["county"]).size().sort_values()
ax.barh(cnt.index, cnt.values, color=an.PRIMARY, height=.6); ax.set_xlabel("Customers"); ax.set_title("Subscribers by county")
ax.grid(axis="y", visible=False); an.save(fig, "customers_by_county");"""),
    code("pd.crosstab(cs.age_group, cs.customer_type, normalize='columns').mul(100).round(1)"),
]

NB["04_revenue_and_usage_analysis"] = [
    md("# 04 · Revenue and usage\nQuestions 1, 2, 4, 5 and 18: where revenue comes from, how ARPU moves, and where usage is growing."),
    code(SETUP),
    code("o('q01_headline_kpis').T"),
    code("""k = o("q02_monthly_kpi_trend"); k["month"] = pd.to_datetime(k.month)
fig, ax = plt.subplots(1, 2, figsize=(12, 3.6))
ax[0].plot(k.month, k.revenue, color=an.PRIMARY); an.kes_axis(ax[0]); ax[0].set_title("Monthly revenue (KES)")
ax[0].axvline(pd.Timestamp("2025-07-01"), color=an.INK_MUTED, ls="--", lw=.8); ax[0].text(pd.Timestamp("2025-07-10"), k.revenue.min(), "bundle price +10%", fontsize=8, color=an.INK_MUTED)
ax[1].plot(k.month, k.arpu, color=an.PRIMARY, label="ARPU (KES per active customer)")
ax[1].set_title("ARPU rises in steps: usage growth plus the July 2025 price change")
ax[1].axvline(pd.Timestamp("2025-07-01"), color=an.INK_MUTED, ls="--", lw=.8)
fig.tight_layout(); an.save(fig, "revenue_and_arpu_trend");"""),
    code("o('q03_revenue_by_service')"),
    md("Postpaid bills are a third of revenue from about 12% of customers. Among prepaid services, **data bundles are the largest and among the fastest growing**. Mobile-money fees grew least: they're a small, fee-based line that depends on transaction counts rather than bundle prices."),
    code("""g = o("q04_value_by_customer_group")
g[g.dim.isin(["customer_type", "plan_type", "age_group"])]"""),
    code("""t = o("q06_value_by_tenure")
fig, ax = plt.subplots(figsize=(8, 3.3))
ax.bar(t.tenure_band.str[3:], t.arpu_kes, color=an.PRIMARY, width=.6); ax.set_ylabel("ARPU (KES)")
ax.set_title("ARPU grows over the first year, then plateaus"); ax.grid(axis="x", visible=False)
an.save(fig, "arpu_by_tenure"); t"""),
    code("o('q24_usage_growth')"),
    md("""**Growth signal:** data per active customer rose by about a quarter year-on-year, while voice and SMS per customer are flat to falling. Data is where engagement is growing, and voice and SMS are mature. This is the growth opportunity behind question 18."""),
]

NB["05_cohort_and_retention_analysis"] = [
    md("# 05 · Cohort and retention analysis\nQuestions 6–11. The SQL matrix (q11) and an independent pandas implementation are computed and compared."),
    code(SETUP),
    code("o('q08_churn_rate_summary').T"),
    code("""k = o("q02_monthly_kpi_trend"); k["month"] = pd.to_datetime(k.month); k = k[k.month >= "2024-05-01"]
fig, ax = plt.subplots(figsize=(10, 3.4))
ax.plot(k.month, k.churn_rate_pct, color=an.CONTEXT, lw=1.2, label="Monthly churn rate")
ax.plot(k.month, k.churn_rate_3m_pct, color=an.PRIMARY, label="3-month rolling")
ax.axvspan(pd.Timestamp("2025-11-01"), pd.Timestamp("2026-02-01"), color=an.HIGHLIGHT, alpha=.12)
ax.text(pd.Timestamp("2025-11-05"), k.churn_rate_pct.max() * .98, "closures from the\\nJul-Oct 2025 exits", fontsize=8, color=an.INK_MUTED)
ax.set_ylabel("% of opening base"); ax.set_title("Churn spiked about four months after the July 2025 price change"); ax.legend(loc="lower left")
an.save(fig, "monthly_churn_rate");"""),
    code("""c = o("q09_churn_by_segment")
fig, axes = plt.subplots(1, 3, figsize=(13, 3.4))
for ax, dim in zip(axes, ["customer_type", "plan_type", "value_segment"]):
    d = c[c.dim == dim].sort_values("monthly_churn_pct")
    ax.barh(d.grp, d.monthly_churn_pct, color=[an.HIGHLIGHT if v == d.monthly_churn_pct.max() else an.PRIMARY for v in d.monthly_churn_pct], height=.6)
    ax.set_title(dim.replace("_", " ").title()); ax.set_xlabel("avg monthly churn %"); ax.grid(axis="y", visible=False)
fig.suptitle("Who churns: prepaid, Prepaid Flex and low early spenders", x=.01, ha="left", fontweight="bold")
fig.tight_layout(); an.save(fig, "churn_by_segment"); c[c.dim == 'county'].head(5)"""),
    md("The three counties with the highest churn (Garissa, Kilifi, Turkana) also have the highest network-complaint rates (notebook 07)."),
    code("""t = o("q10_churn_by_tenure")
fig, ax = plt.subplots(figsize=(9, 3.2))
ax.plot(t.tenure_month_capped_36, t.monthly_churn_pct, color=an.PRIMARY, marker="o", ms=3)
ax.set_xlabel("Tenure at line closure (months; 36 = 36+)"); ax.set_ylabel("monthly churn %")
ax.set_title("Closures peak at 3-12 months of tenure (decisions made in the first months)"); an.save(fig, "churn_by_tenure");"""),
    md("Closures can't happen before month 3–4, because of the 90-day rule. The peak at 3–12 months reflects customers who decided to leave **in their first months**, the classic early-life churn window."),
    md("## Cohort retention: SQL and pandas must agree"),
    code("""sql = o("q11_cohort_retention_matrix").pivot(index="cohort_month", columns="months_since_acquisition", values="retention_pct")
cm = query(engine, "SELECT customer_id, cohort_month, month, is_active FROM telco.mv_customer_month WHERE cohort_month >= DATE '2024-01-01'")
py = an.retention_matrix(cm, max_k=24)
sql.index = pd.to_datetime(sql.index); sql.columns = sql.columns.astype(int)
diff = (sql - py.round(1)).abs().max().max()
print(f"max absolute difference between SQL and pandas retention: {diff:.2f} percentage points")
assert diff < 0.11"""),
    code("""fig, ax = plt.subplots(figsize=(13, 6.5))
show = py.copy(); show.index = show.index.strftime("%Y-%m")
sns.heatmap(show.iloc[:, :25], cmap=sns.color_palette(an.SEQ_BLUES, as_cmap=True), vmin=50, vmax=100, ax=ax,
            cbar_kws={"label": "% of cohort active"}, linewidths=.3, linecolor="white", annot=False)
ax.set_xlabel("Months since acquisition"); ax.set_ylabel("Acquisition cohort")
ax.set_title("Cohort retention: 71-74% of new customers are still active after 12 months")
an.save(fig, "cohort_retention_heatmap");"""),
    code("o('q12_retention_milestones')"),
    md("""**Reading the cohorts.** Retention is steady across cohorts: about 97% active after 1 month, about 90% after 3, about 83% after 6 and 71–74% after 12. The **2025-Q3 cohort** has the weakest 3-month figure. Those customers joined just as bundle prices rose, so their first renewals happened at the higher price."""),
]

NB["06_customer_segmentation"] = [
    md("""# 06 · Customer segmentation
Two approaches, compared:
1. **Business segments** (value deciles of early revenue): simple, explainable, already used in the dashboard.
2. **Optional extension: K-means behavioural clusters** on usage mix and spend. Its purpose is to find *how* customers use the network, which value tiers alone can't show. Clusters are not assumed to be meaningful until they are interpreted."""),
    code(SETUP + "\nfrom sklearn.preprocessing import StandardScaler\nfrom sklearn.cluster import KMeans\nfrom sklearn.metrics import silhouette_score, adjusted_rand_score"),
    code("""cs = query(engine, \"\"\"SELECT customer_id, customer_type, value_segment, avg_monthly_revenue, avg_data_mb, avg_voice_minutes,
       avg_sms, avg_transactions, tenure_months, churned FROM telco.v_customer_summary WHERE active_months >= 4\"\"\")
for c in ["avg_monthly_revenue", "avg_data_mb", "avg_voice_minutes", "avg_sms", "avg_transactions"]:
    cs[c] = cs[c].astype(float)
feat = pd.DataFrame({
    "log_revenue": np.log1p(cs.avg_monthly_revenue),
    "log_data_mb": np.log1p(cs.avg_data_mb),
    "log_voice_min": np.log1p(cs.avg_voice_minutes),
    "log_sms": np.log1p(cs.avg_sms),
    "purchases_per_month": cs.avg_transactions,
})
print(len(feat), "customers with >= 4 active months"); feat.describe().T[["mean", "std", "min", "max"]]"""),
    md("""**Feature choices.** Spend, data, voice and SMS describe *what* a customer uses, and purchase frequency describes *how* they buy. All are log-transformed (they are heavily skewed) and then **standardised**, because K-means uses Euclidean distance: without scaling, data MB, which runs into thousands, would dominate SMS counts. Tenure and churn are deliberately **left out**, so they can be used afterwards to check whether the clusters mean anything."""),
    code("""X = StandardScaler().fit_transform(feat)
rng = np.random.default_rng(0); sample = rng.choice(len(X), 6000, replace=False)
rows = []
for k in range(2, 9):
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    rows.append({"k": k, "inertia": km.inertia_, "silhouette": silhouette_score(X[sample], km.labels_[sample])})
sel = pd.DataFrame(rows)
fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
ax[0].plot(sel.k, sel.inertia, marker="o", color=an.PRIMARY); ax[0].set_title("Elbow: within-cluster sum of squares"); ax[0].set_xlabel("k")
ax[1].plot(sel.k, sel.silhouette, marker="o", color=an.PRIMARY); ax[1].set_title("Silhouette (higher = better separated)"); ax[1].set_xlabel("k")
fig.tight_layout(); an.save(fig, "kmeans_selection"); sel"""),
    code("""# k = 2 scores well only because it splits light users from everyone else, which is too coarse to act on.
# Rule: among k = 3..6 (enough groups to target differently, few enough to explain), take the best silhouette.
cand = sel[sel.k.between(3, 6)]
K = int(cand.loc[cand.silhouette.idxmax(), "k"])
print("chosen k =", K)
km = KMeans(n_clusters=K, n_init=20, random_state=0).fit(X)
cs["cluster"] = km.labels_
prof = cs.assign(**feat).groupby("cluster").agg(customers=("customer_id", "count"), avg_revenue=("avg_monthly_revenue", "median"),
        data_mb=("avg_data_mb", "median"), voice_min=("avg_voice_minutes", "median"), sms=("avg_sms", "median"),
        purchases=("avg_transactions", "median"), postpaid_pct=("customer_type", lambda s: 100 * (s == "Postpaid").mean()),
        churned_pct=("churned", lambda s: 100 * s.mean())).round(1)
prof"""),
    code("""def name(r):
    if r.postpaid_pct > 50: return "Business postpaid"
    if r.data_mb > 4000: return "Data-heavy prepaid"
    if r.voice_min > 250 and r.data_mb < 1000: return "Voice-first prepaid"
    if r.avg_revenue < 200: return "Light / occasional"
    return "Balanced prepaid"
prof["label"] = prof.apply(name, axis=1)
cs["cluster_label"] = cs.cluster.map(prof.label)
prof[["label", "customers", "avg_revenue", "data_mb", "voice_min", "purchases", "postpaid_pct", "churned_pct"]]"""),
    md("Labels are assigned from the medians, with the rules written in the code so anyone can check them. A cluster earns a business name only if its profile clearly differs from the others."),
    code("""ct = pd.crosstab(cs.cluster_label, cs.value_segment, normalize="index").mul(100).round(1)
fig, ax = plt.subplots(figsize=(9, 3.4))
sns.heatmap(ct, annot=True, fmt=".0f", cmap=sns.color_palette(an.SEQ_BLUES, as_cmap=True), cbar=False, ax=ax)
ax.set_title("Behavioural clusters vs business value segments (% of cluster)"); ax.set_xlabel(""); ax.set_ylabel("")
an.save(fig, "clusters_vs_value_segments"); ct"""),
    md("**Clusters vs value segments.** Value tiers say *how much* customers spend, and clusters say *on what*. Data-heavy and voice-first customers can sit in the same value tier but need different offers: data bonuses for one group, voice or combo bundles for the other. That is the business case for keeping both views."),
    code("""truth = pd.read_csv(PROJECT_ROOT / "data/synthetic/raw/_truth_archetypes.csv")
m = cs.merge(truth, on="customer_id")
print("Adjusted Rand Index, clusters vs generator archetypes:", round(adjusted_rand_score(m.archetype, m.cluster), 3))
pd.crosstab(m.cluster_label, m.archetype)"""),
    md("""**Validation (only possible because the data is synthetic).** The generator recorded each customer's hidden behavioural archetype. The Adjusted Rand Index compares the clusters with that truth: 0 would mean random agreement and 1 a perfect match. In real data there is no ground truth, and validation would rely on stability (re-running on samples) and on whether campaigns targeted by cluster perform better.

**Result:** an ARI of about 0.64. Four clusters recover the business, voice-centric and low-value archetypes almost perfectly. *Youth data-heavy* and *mainstream balanced* merge into one data-led cluster: they differ mainly in how much data they use, not in the shape of their usage. A fifth cluster would be justified only if the business wanted different offers for those two groups."""),
    md("## Simple customer lifetime value (where the data supports it)"),
    code("""seg = o("q05_value_segments").query("value_segment != 'Unsegmented (too new)'").set_index("value_segment")
ch = o("q09_churn_by_segment").query("dim == 'value_segment'").set_index("grp").monthly_churn_pct / 100
rows = []
for s in seg.index:
    for margin in (0.45, 0.55, 0.65):
        rows.append({"value_segment": s, "contribution_margin": margin, "monthly_churn": ch[s],
                     "clv_kes": an.simple_clv(seg.loc[s, "avg_monthly_revenue_kes"] * margin, ch[s])})
clv = pd.DataFrame(rows).pivot_table(index="value_segment", columns="contribution_margin", values="clv_kes").round(-2)
clv.columns = [f"CLV @ {int(c*100)}% margin" for c in clv.columns]; clv"""),
    md("""**CLV assumptions, stated plainly:** contribution margin is **not in the data**, so a 45–65% range is shown. Churn is assumed constant at each segment's average monthly rate, and there is a 1% monthly discount rate. The *ranking* (Platinum worth over 20× Bronze) is robust to those assumptions. The absolute shilling values are not, so they shouldn't be quoted without a finance-approved margin."""),
]

NB["07_customer_experience_analysis"] = [
    md("# 07 · Customer experience\nQuestions 12–15: complaint volumes, resolution times, links to churn, and problem areas."),
    code(SETUP),
    code("pd.merge(o('q16_complaints_by_category'), o('q17_resolution_time').drop(columns='complaints'), on='complaint_category')"),
    code("""cp = query(engine, "SELECT complaint_category, resolution_date - complaint_date AS days FROM telco.complaints WHERE resolution_date IS NOT NULL")
order = cp.groupby("complaint_category").days.median().sort_values().index
fig, ax = plt.subplots(figsize=(9, 3.4))
sns.boxplot(data=cp, y="complaint_category", x="days", order=order, color=an.SEQ_BLUES[2], showfliers=False, ax=ax, width=.5)
ax.set_xlabel("Days to resolve (resolved tickets only)"); ax.set_ylabel(""); ax.set_title("Network and data-speed complaints take longest, and 20-30% are never resolved")
an.save(fig, "resolution_time_by_category");"""),
    code("""q = o("q18_complaints_and_churn").dropna(subset=["value_tier"])
fig, ax = plt.subplots(figsize=(9, 3.6))
tiers = q.value_tier.unique(); x = np.arange(4); w = .38
for i, (t, col) in enumerate(zip(tiers, [an.PRIMARY, an.HIGHLIGHT])):
    d = q[q.value_tier == t].sort_values("complaint_experience")
    ax.bar(x + (i - .5) * w, d.churned_pct, w, color=col, label=t)
ax.set_xticks(x, ["No complaint", "Resolved <=7d", "Resolved >7d", "Unresolved /\\nescalated"])
ax.set_ylabel("% of customers churned within ~14 months"); ax.legend(); ax.grid(axis="x", visible=False)
ax.set_title("Unresolved complaints go with higher churn in both value tiers")
an.save(fig, "complaints_vs_churn"); o("q18_complaints_and_churn")"""),
    md("""**How to read this (question 14).** Within each value tier, customers whose complaint was **never resolved** churned at about 1.2–1.5× the rate of customers who didn't complain, and at nearly twice the rate of customers whose complaint *was* resolved.

Two cautions:
- *Confounding:* complainers skew towards higher-value customers, who churn less anyway, so the unsplit row understates the gap. That is why the analysis is split by tier.
- *Exposure:* customers who stay longer have more months in which to complain. That partly explains why "resolved" complainers churn *less* than non-complainers.

This shows **association**, not proof of cause. A controlled test, such as prioritised resolution for a random half of open tickets, would establish the effect."""),
    code("""c = o("q19_complaints_by_county")
fig, ax = plt.subplots(figsize=(9, 3.8))
c = c.sort_values("per_1000_subscriber_months")
ax.barh(c.county, c.network_and_speed_per_1000, color=an.HIGHLIGHT, height=.6, label="Network & data speed")
ax.barh(c.county, c.per_1000_subscriber_months - c.network_and_speed_per_1000, left=c.network_and_speed_per_1000, color=an.CONTEXT, height=.6, label="All other categories")
ax.set_xlabel("Complaints per 1,000 subscriber-months"); ax.legend(loc="lower right"); ax.grid(axis="y", visible=False)
ax.set_title("Turkana, Kilifi and Garissa: about 2x the complaint rate, driven by network issues")
an.save(fig, "complaints_by_county"); o("q19_complaints_by_county")"""),
    code("o('q20_complaints_by_segment')"),
]

NB["08_business_recommendations"] = [
    md("# 08 · Business recommendations\nQuestions 16–19, sized from the analysis."),
    code(SETUP),
    code("o('q15_declining_customers')"),
    code("o('q23_valuable_customers_at_risk').head(10)"),
    code("pd.concat([o('q21_campaign_response').set_index('campaign_type'), ], axis=1)"),
    code("o('q22_winback_effect')"),
    md("""**Win-back caution.** Customers who *accepted* a win-back offer almost all stayed, while those who didn't mostly left. This comparison is **self-selected**: customers who accept were probably less determined to leave. It doesn't prove the offer caused the retention. A holdout group (declining customers deliberately not contacted) would measure the true effect. It is cheap to set up, and it is the first thing to fix in campaign design."""),
    code("""p = o("q25_price_change_churn")
pv = p.pivot_table(index=["customer_type", "value_segment"], columns="period", values="monthly_churn_pct")
pv["after_vs_before"] = (pv.iloc[:, 1] - pv.iloc[:, 0]).round(2); pv.sort_values("after_vs_before", ascending=False)"""),
    md("Closures after the price change rose most among **prepaid Bronze** customers (low early spend). Higher-value and postpaid customers barely moved. The extra closures were concentrated in Nov 2025–Feb 2026, about four months after the change, and churn returned towards its earlier level afterwards."),
    code("""k = o("q01_headline_kpis").iloc[0]
seg = o("q15_declining_customers")
at_risk = seg.annualised_revenue_at_risk_kes.sum()
hv = seg[seg.value_segment.str.startswith(("Platinum", "Gold"))].annualised_revenue_at_risk_kes.sum()
annual_rev = k.revenue * 12
print(f"Declining customers today: {seg.customers.sum():,}; annualised revenue already lost from their decline: KES {at_risk/1e6:.1f}M")
print(f"  of which Platinum/Gold: KES {hv/1e6:.1f}M ({100*hv/at_risk:.0f}%)")
print(f"Run-rate annual revenue (Oct 2026 x 12): KES {annual_rev/1e6:.0f}M")"""),
    md("""## Recommendations

| # | Recommendation | Evidence | Measure |
|---|---|---|---|
| 1 | **Monthly early-warning list**: contact customers flagged *Declining* before the 90-day closure, Platinum/Gold first | Churn is preceded by about 2 months of falling activity; ~700 customers are in decline now, a quarter of them Platinum/Gold, who carry about half the revenue at risk (q15, q23) | Share of flagged customers active again after 60 days |
| 2 | **Fix network complaints first** in Turkana, Kilifi and Garissa, and set a resolution target for network and data-speed tickets | These counties have about 2× the complaint rate and the highest churn; network tickets take about 12 days and 30% are never resolved (q17, q19, q9) | Unresolved network-ticket share; county churn |
| 3 | **Resolve-or-escalate rule** for every complaint over 7 days old | Unresolved complainers churn about 1.2–1.5× more than non-complainers within the same value tier (q18) | % of tickets closed ≤7 days |
| 4 | **Protect low-spend prepaid customers in future price changes** (keep an entry bundle at the old price) | Closures of prepaid Bronze customers rose from about 2.4% to 3.6% a month after the July 2025 rise (q25) | Churn of the low-spend prepaid segment after the next tariff change |
| 5 | **Grow data**: target data-heavy and balanced prepaid users with data and combo upsells; don't push data offers to voice-first users | Data per user up ~25% YoY; voice and SMS flat (q24); behavioural clusters show different needs within each value tier (nb 06) | Data bundle revenue per active customer |
| 6 | **Add a holdout group to win-back campaigns** | The current comparison is self-selected (q22) | Measured incremental retention |

**What the data cannot tell us:** why individual customers leave (no exit survey), competitor offers, network quality measured directly (only complaints), and contribution margin (CLV is shown as a range)."""),
]


def main(run: bool = True) -> None:
    NB_DIR.mkdir(exist_ok=True)
    for name, cells in NB.items():
        nb = nbf.v4.new_notebook(); nb["cells"] = cells
        nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        path = NB_DIR / f"{name}.ipynb"; nbf.write(nb, path)
        if run:
            print("executing", path.name, flush=True)
            subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                            "--ExecutePreprocessor.timeout=1200", str(path)], check=True, capture_output=True)


if __name__ == "__main__":
    main(run="--no-run" not in sys.argv)
