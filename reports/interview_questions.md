# Interview preparation: Telecom Customer Value & Retention Analytics

Practise answering aloud in under two minutes each. The "covers" notes are what an interviewer listens for, not a script.

## Business questions

1. **Walk me through this project in two minutes.**
   *Covers:* fictional Kenyan operator, growing but not knowing who creates value or why customers leave → synthetic data and why → PostgreSQL pipeline with a customer-month grid → headline numbers (top 10% = 36% of revenue; 1.53% monthly churn; unresolved complaints linked to 1.2–1.5× churn; 702 declining customers, KES 3.5M a year) → six recommendations → limitations.

2. **Why synthetic data? Couldn't you use the IBM Telco dataset?**
   *Covers:* IBM Telco is one snapshot with a churn flag and no history, so no cohorts, no MAU and no declining-activity analysis; no usage, complaints or campaigns; US home products; no clear licence. I built a month-by-month simulation with documented mechanisms and injected data-quality problems. The value is in showing the method recovers and sizes the mechanisms correctly, and the injection manifest lets me *verify* the cleaning.

3. **How do you define churn for a prepaid customer who never cancels?**
   *Covers:* the operator closes the line after 90 days without activity, so churn month = closure month. That creates a lag of about three months between disengagement and recorded churn, which is why I track *declining* customers as an early-warning signal and why price effects appear in closures about four months later.

4. **What's your churn rate, and how did you calculate it?**
   *Covers:* closures in the month ÷ lines open on day 1 of the month, averaged customer-month weighted from May 2024 (no closures can appear before then): 1.53% a month. Annualised by compounding, 1 − (1 − 0.0153)^12 = 16.9%, not 1.53 × 12.

5. **Which customers matter most, and how would you protect them?**
   *Covers:* Platinum = top 10% by early spend, 36% of revenue, CLV roughly 20× Bronze, 72% postpaid. They churn least (0.41%) but complain most; an unresolved complaint is their biggest risk. Recommendation: account-manager contact for the 173 declining Platinum/Gold customers and a callback rule for high-value complaints open more than 7 days.

6. **Your data says complaints cause churn. How do you know?**
   *Covers:* I don't claim cause. It is an association from observational data. I fixed the population (customers subscribed on 1 Jan 2025), measured exposure before outcome, and stratified by value tier, because unstratified results were misleading. The causal test would be an experiment, for example faster resolution in some regions first.

7. **The win-back acceptors almost never left. Should we spend more on win-back?**
   *Covers:* no, not on this evidence: acceptance is self-selected; customers willing to stay accept the offer. I'd recommend a random hold-out group in the next campaign to measure incremental retention.

8. **What would you do about the three high-complaint counties?**
   *Covers:* the excess is network and data-speed tickets with slow resolution; I'd involve network engineering and set a 7-day target, then check whether churn falls toward the national rate. I'd also want network-quality data (outages, dropped calls) to confirm the coverage explanation.

## SQL questions

9. **Why build a customer-month grid instead of querying transactions directly?**
   *Covers:* churn, ARPU and retention need a row for months with *no* activity; a transaction table can't show absence. `generate_series` creates one row per subscribed month; flags (`is_active`, `in_opening_base`, `is_churn_month`) make every rate a simple `SUM/COUNT`. `dq_b02` proves revenue in the grid equals revenue in transactions.

10. **How did you build the cohort retention matrix, and what's the most common mistake?**
    *Covers:* cohort = acquisition month; k = months since acquisition; retention = active in c + k ÷ cohort size (fixed denominator). Mistakes: using the surviving base as the denominator (retention can rise), and showing unobserved cells as 0 instead of NULL.

11. **How did you assign value segments, and why not lifetime revenue?**
    *Covers:* `NTILE(10)` over early monthly revenue, partitioned so customers too new to have an early value are excluded. Lifetime average would rank churners low because they spent nothing while leaving: reverse causality.

12. **Show me a window function you used.**
    *Covers:* `RANK() OVER (PARTITION BY county ORDER BY revenue DESC)` for top customers per county; `LAG(…, 12)` for year-over-year; a 3-month rolling churn rate with `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW`; `ROW_NUMBER` to rank at-risk customers.

13. **What does `ROLLUP` add in q18?**
    *Covers:* it produces the stratified rows and the overall total in one query, so the reader sees the unstratified comparison next to the stratified one and understands why stratifying matters.

## Python and data-quality questions

14. **What data-quality problems did you find, and how did you decide what to fix?**
    *Covers:* duplicates, label variants, a 2062 acquisition year, × 1000 amounts, orphan IDs, negative and sentinel meter readings, resolution before complaint, missing responses. Rule: fix what is certain (the first subscription date is a trusted source for the acquisition date), quarantine what would be a guess, log everything, impute nothing. Every exception is reconciled against the injection manifest.

15. **Tell me about a mistake you caught.**
    *Covers:* a single KES 25,000 ceiling missed three mobile-money fees keyed × 1000 (KES 13 → 13,000). Profiling the range per service showed fees never exceed KES 95, so the rule became service-specific. Also: lifetime-spend segments (circular), and K-means choosing *k* = 2.

16. **Why K-means, and how did you choose *k*?**
    *Covers:* optional extension, to see whether behaviour adds something to spend-based segments. Log-transformed, standardised features; silhouette preferred *k* = 2, but that only split business postpaid from everyone, so I restricted *k* to 3–6 → 4 clusters. Validated against the hidden archetypes (ARI 0.64) and compared with value segments: Data-heavy and Voice-first customers spend similarly but need different offers.

17. **How did you calculate CLV, and how much do you trust it?**
    *Covers:* m × (1 + d) / (d + churn), with segment churn and a 1% monthly discount; margin is unknown, so a 45–65% range. It is a ranking tool (Platinum ≈ 20× Bronze), not a valuation.

18. **How do you know the dashboard is right?**
    *Covers:* the SQL views are the single definition; `export_powerbi.py` writes `kpi_reconciliation.csv`; I ran a DAX query in Power BI and compared; tests check the export reconciles with the database.

## Power BI questions

19. **Explain your data model.**
    *Covers:* customer dimension and marked date table; customer-month fact (grid), service revenue, complaints and campaign facts; single-direction relationships; two small pre-aggregated tables for the cohort heatmap and the complaint–churn chart, because those calculations are clearer in SQL.

20. **Write the churn-rate measure.**
    *Covers:* `DIVIDE([Churned Customers], [Opening Base])`, where both count rows in the customer-month fact with a flag, so the measure works under any slicer combination. Latest-month cards use `VAR m = MAX(month) RETURN CALCULATE(…, month = m)`.

## Behavioural questions

21. **What would you do differently with real data?**
    *Covers:* agree the churn and active definitions with finance and the network team first; check event latency (when does a top-up appear?); get cost data for margin-based CLV; plan a hold-out experiment from the start.

22. **What was the hardest part?**
    *Covers:* definitions, not code. Getting the denominators, the closure lag and the reverse-causality issue right mattered more than any single query.
