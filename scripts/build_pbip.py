"""Generate the complete Power BI project (PBIP: TMDL semantic model + PBIR report) for Jamii Mobile.

    python scripts/build_pbip.py --data-folder "C:\\path\\to\\data\\processed\\powerbi\\"

Writes powerbi/JamiiMobile.pbip, powerbi/JamiiMobile.SemanticModel/ and powerbi/JamiiMobile.Report/.
Open the .pbip in Power BI Desktop and click Refresh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PB = ROOT / "powerbi"
NAME = "JamiiMobile"
SM = PB / f"{NAME}.SemanticModel"
RP = PB / f"{NAME}.Report"
NS = uuid.UUID("2b0c8a52-6f0e-4d6b-9a77-1f0d3c2e5a10")
tag = lambda s: str(uuid.uuid5(NS, s))
hid = lambda *p: hashlib.sha1("|".join(map(str, p)).encode()).hexdigest()[:20]

# ------------------------------------------------------------------------------------------------
# Semantic model
# ------------------------------------------------------------------------------------------------
T, I, D, C, DT, B = "string", "int64", "double", "decimal", "dateTime", "boolean"
MT = {T: "type text", I: "Int64.Type", D: "type number", C: "Currency.Type", DT: "type date", B: "type logical"}
TABLES = {
    "dim_date": [("date", DT), ("year", I), ("month_number", I), ("month_short", T), ("year_month", T), ("month_start", DT)],
    "dim_customer": [("customer_id", T), ("customer_type", T), ("age_group", T), ("county", T), ("plan_type", T),
                     ("cohort_month", DT), ("cohort_label", T), ("acquired_in_window", B), ("value_segment", T),
                     ("engagement_status", T), ("churned", B), ("tenure_months", I), ("avg_monthly_revenue", C),
                     ("rev_may_jul_2026", C), ("rev_aug_oct_2026", C), ("complaints", I), ("open_complaints", I)],
    "fact_customer_month": [("customer_id", T), ("month", DT), ("tenure_months", I), ("tenure_band", T), ("tenure_band_order", I),
                            ("revenue", C), ("transactions", I), ("data_mb", D), ("voice_minutes", D), ("sms_count", I),
                            ("is_active", B), ("in_opening_base", B), ("is_churn_month", B), ("is_new_customer_month", B)],
    "fact_service_revenue": [("customer_id", T), ("month", DT), ("service_type", T), ("revenue", C), ("transactions", I)],
    "fact_complaints": [("complaint_id", T), ("customer_id", T), ("month", DT), ("complaint_category", T),
                        ("resolution_status", T), ("days_to_resolve", D)],
    "fact_campaigns": [("campaign_id", T), ("customer_id", T), ("month", DT), ("campaign_type", T), ("campaign_response", T)],
    "cohort_retention": [("cohort_month", DT), ("cohort_size", I), ("months_since_acquisition", I), ("retention_pct", D), ("cohort_label", T)],
    "complaint_churn_link": [("value_tier", T), ("complaint_experience", T), ("customers", I), ("churned", I), ("churned_pct", D)],
}
HIDDEN = {"fact_customer_month": {"customer_id", "month", "tenure_band_order"}, "fact_service_revenue": {"customer_id", "month"},
          "fact_complaints": {"customer_id", "month"}, "fact_campaigns": {"customer_id", "month"}}
SORT_BY = {("dim_date", "month_short"): "month_number", ("fact_customer_month", "tenure_band"): "tenure_band_order"}
SUM_COLS = {"revenue", "transactions", "data_mb", "voice_minutes", "sms_count", "customers", "churned"}
RELS = [("fact_customer_month.month", "dim_date.date"), ("fact_customer_month.customer_id", "dim_customer.customer_id"),
        ("fact_service_revenue.month", "dim_date.date"), ("fact_service_revenue.customer_id", "dim_customer.customer_id"),
        ("fact_complaints.month", "dim_date.date"), ("fact_complaints.customer_id", "dim_customer.customer_id"),
        ("fact_campaigns.month", "dim_date.date"), ("fact_campaigns.customer_id", "dim_customer.customer_id")]

KES, PCT2, NUM, DEC1 = "#,0", "0.00%", "#,0", "#,0.0"
FCM = "fact_customer_month"
MEASURES = [
    ("Revenue", f"SUM ( {FCM}[revenue] )", KES, "1 Value"),
    ("Active Customer Months", f"CALCULATE ( COUNTROWS ( {FCM} ), {FCM}[is_active] = TRUE () )", NUM, "1 Value"),
    ("ARPU", "DIVIDE ( [Revenue], [Active Customer Months] )", KES, "1 Value"),
    ("Active Customers", f"CALCULATE ( DISTINCTCOUNT ( {FCM}[customer_id] ), {FCM}[is_active] = TRUE () )", NUM, "1 Value"),
    ("Latest Month", f"MAX ( {FCM}[month] )", "mmm yyyy", "1 Value"),
    ("Subscribers (latest month)", f"VAR m = [Latest Month] RETURN CALCULATE ( COUNTROWS ( {FCM} ), {FCM}[month] = m )", NUM, "1 Value"),
    ("Active Customers (latest month)", f"VAR m = [Latest Month] RETURN CALCULATE ( [Active Customers], {FCM}[month] = m )", NUM, "1 Value"),
    ("Revenue (latest month)", f"VAR m = [Latest Month] RETURN CALCULATE ( [Revenue], {FCM}[month] = m )", KES, "1 Value"),
    ("ARPU (latest month)", f"VAR m = [Latest Month] RETURN CALCULATE ( [ARPU], {FCM}[month] = m )", KES, "1 Value"),
    ("New Customers", f"CALCULATE ( COUNTROWS ( {FCM} ), {FCM}[is_new_customer_month] = TRUE () )", NUM, "1 Value"),
    ("Data MB per Active Customer", f"DIVIDE ( SUM ( {FCM}[data_mb] ), [Active Customer Months] )", NUM, "1 Value"),
    ("Voice Min per Active Customer", f"DIVIDE ( SUM ( {FCM}[voice_minutes] ), [Active Customer Months] )", NUM, "1 Value"),
    ("Service Revenue", "SUM ( fact_service_revenue[revenue] )", KES, "1 Value"),
    ("Revenue Share of Selection", "DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALLSELECTED ( dim_customer ) ) )", "0.0%", "1 Value"),
    ("Customer Share of Selection", "DIVIDE ( DISTINCTCOUNT ( dim_customer[customer_id] ), CALCULATE ( DISTINCTCOUNT ( dim_customer[customer_id] ), ALLSELECTED ( dim_customer ) ) )", "0.0%", "1 Value"),
    ("Revenue PY", "CALCULATE ( [Revenue], DATEADD ( dim_date[date], -1, YEAR ) )", KES, "1 Value"),
    ("Revenue YoY %", "IF ( NOT ISBLANK ( [Revenue PY] ), DIVIDE ( [Revenue] - [Revenue PY], [Revenue PY] ) )", "+0.0%;-0.0%;0.0%", "1 Value"),
    ("Opening Base", f"CALCULATE ( COUNTROWS ( {FCM} ), {FCM}[in_opening_base] = TRUE () )", NUM, "2 Retention"),
    ("Churned Customers", f"CALCULATE ( COUNTROWS ( {FCM} ), {FCM}[is_churn_month] = TRUE () )", NUM, "2 Retention"),
    ("Churn Rate %", "DIVIDE ( [Churned Customers], [Opening Base] )", PCT2, "2 Retention"),
    ("Avg Monthly Churn % (from May 2024)",
     "CALCULATE ( [Churn Rate %], KEEPFILTERS ( dim_date[date] >= DATE ( 2024, 5, 1 ) ) )", PCT2, "2 Retention"),
    ("Annualised Churn %", "1 - POWER ( 1 - [Avg Monthly Churn % (from May 2024)], 12 )", "0.0%", "2 Retention"),
    ("Retention %", "DIVIDE ( AVERAGE ( cohort_retention[retention_pct] ), 100 )", "0.0%", "2 Retention"),
    ("Retention Colour",
     "VAR r = AVERAGE ( cohort_retention[retention_pct] )\nRETURN SWITCH ( TRUE (), ISBLANK ( r ), BLANK (), r >= 95, \"#0d366b\", r >= 90, \"#184f95\", r >= 85, \"#256abf\", r >= 80, \"#3987e5\", r >= 75, \"#6da7ec\", r >= 70, \"#9ec5f4\", \"#cde2fb\" )",
     None, "2 Retention"),
    ("Retention Font Colour", "IF ( AVERAGE ( cohort_retention[retention_pct] ) >= 80, \"#ffffff\", \"#2b2b29\" )", None, "2 Retention"),
    ("Declining Customers",
     "CALCULATE ( DISTINCTCOUNT ( dim_customer[customer_id] ), dim_customer[engagement_status] IN { \"Declining (>50% revenue drop)\", \"Silent (no activity Aug-Oct)\" } )",
     NUM, "2 Retention"),
    ("Revenue at Risk (annualised)",
     "CALCULATE ( SUMX ( dim_customer, ( dim_customer[rev_may_jul_2026] - dim_customer[rev_aug_oct_2026] ) / 3 * 12 ), dim_customer[engagement_status] IN { \"Declining (>50% revenue drop)\", \"Silent (no activity Aug-Oct)\" } )",
     KES, "2 Retention"),
    ("Complaints", "COUNTROWS ( fact_complaints )", NUM, "3 Experience"),
    ("Complaints per 1,000 Subscriber-Months", f"DIVIDE ( [Complaints], COUNTROWS ( {FCM} ) ) * 1000", DEC1, "3 Experience"),
    ("Avg Days to Resolve", "AVERAGE ( fact_complaints[days_to_resolve] )", DEC1, "3 Experience"),
    ("Unresolved Complaint %", "DIVIDE ( CALCULATE ( [Complaints], fact_complaints[resolution_status] <> \"Resolved\" ), [Complaints] )", "0.0%", "3 Experience"),
    ("Campaign Contacts", "COUNTROWS ( fact_campaigns )", NUM, "3 Experience"),
    ("Campaign Acceptance %", "DIVIDE ( CALCULATE ( [Campaign Contacts], fact_campaigns[campaign_response] = \"Accepted\" ), [Campaign Contacts] )", "0.0%", "3 Experience"),
    ("Churned % (complaint link)", "DIVIDE ( SUM ( complaint_churn_link[churned] ), SUM ( complaint_churn_link[customers] ) )", "0.0%", "3 Experience"),
]

# ---- editorial styling measures (KPI deltas, status, highlight colours) ----
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import pbi_editorial as ed  # noqa: E402

FOCUS, PROBLEM, CONTEXT = "#3987e5", "#d95926", "#5f6773"
MEASURES += [
    ("Δ Revenue", ed.growth_dax("Revenue"), None, "9 Formatting"),
    ("Δ Active Customers", ed.growth_dax("Active Customers"), None, "9 Formatting"),
    ("Δ ARPU", ed.growth_dax("ARPU"), None, "9 Formatting"),
    ("Monthly Churn Text", 'FORMAT ( [Avg Monthly Churn % (from May 2024)], "0.00%" ) & " of the base closes each month"', None, "9 Formatting"),
    ("Risk Share Text", 'FORMAT ( DIVIDE ( CALCULATE ( [Revenue at Risk (annualised)], dim_customer[value_segment] IN { "Platinum (top 10%)", "Gold (next 20%)" } ), [Revenue at Risk (annualised)] ), "0%" ) & " of it from Platinum and Gold"', None, "9 Formatting"),
    ("County Status", 'VAR r = [Complaints per 1,000 Subscriber-Months] RETURN IF ( ISBLANK ( r ), BLANK (), IF ( r >= 25, "▲ Watch", "● Normal" ) )', None, "9 Formatting"),
    ("Colour County Status", f'IF ( [Complaints per 1,000 Subscriber-Months] >= 25, "{PROBLEM}", "#c3c2b7" )', None, "9 Formatting"),
    ("Colour Segment Churn", f'IF ( SELECTEDVALUE ( dim_customer[value_segment] ) = "Bronze (bottom 40%)", "{PROBLEM}", "{CONTEXT}" )', None, "9 Formatting"),
    ("Colour Complaint Category", f'IF ( SELECTEDVALUE ( fact_complaints[complaint_category] ) IN {{ "Network coverage", "Data speed" }}, "{PROBLEM}", "{CONTEXT}" )', None, "9 Formatting"),
    ("Colour Plan Churn", f'IF ( SELECTEDVALUE ( dim_customer[plan_type] ) = "Prepaid Flex", "{PROBLEM}", "{CONTEXT}" )', None, "9 Formatting"),
]


def q(n: str) -> str:
    return n if n.replace("_", "").isalnum() else "'" + n.replace("'", "''") + "'"


def m_source(table, cols):
    types = ", ".join(f'{{"{c}", {MT[t]}}}' for c, t in cols)
    return ["let",
            f'    Source = Csv.Document(File.Contents(DataFolder & "{table}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
            "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
            f'    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")', "in", "    Typed"]


def table_tmdl(name, cols):
    out = [f"table {name}", f"\tlineageTag: {tag(name)}"] + (["\tdataCategory: Time"] if name == "dim_date" else []) + [""]
    for c, t in cols:
        out += [f"\tcolumn {q(c)}", f"\t\tdataType: {t}"]
        if name == "dim_date" and c == "date":
            out.append("\t\tisKey")
        out.append({DT: "\t\tformatString: dd mmm yyyy", C: "\t\tformatString: #,0", I: "\t\tformatString: 0"}.get(t, "") or None)
        if c in HIDDEN.get(name, set()):
            out.append("\t\tisHidden")
        summ = "sum" if (c in SUM_COLS and t in (I, D, C)) else "none"
        out += [f"\t\tlineageTag: {tag(name + '.' + c)}", f"\t\tsummarizeBy: {summ}", f"\t\tsourceColumn: {c}"]
        if (name, c) in SORT_BY:
            out.append(f"\t\tsortByColumn: {SORT_BY[(name, c)]}")
        out.append("")
    out += [f"\tpartition {name} = m", "\t\tmode: import", "\t\tsource ="] + ["\t\t\t\t" + l for l in m_source(name, cols)] + [""]
    return "\n".join(l for l in out if l is not None) + "\n"


def measures_tmdl():
    out = ["table _Measures", f"\tlineageTag: {tag('_Measures')}", ""]
    for name, expr, fmt, folder in MEASURES:
        lines = expr.splitlines()
        if len(lines) == 1:
            out.append(f"\tmeasure {q(name)} = {expr}")
        else:
            out.append(f"\tmeasure {q(name)} =")
            out += ["\t\t\t" + l for l in lines]
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out += [f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {tag('m.' + name)}", ""]
    out += ["\tcolumn Dummy", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {tag('_Measures.Dummy')}",
            "\t\tsummarizeBy: none", "\t\tsourceColumn: Dummy", "", "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
            "\t\t\t\tlet", "\t\t\t\t    Source = #table(type table [Dummy = text], {})", "\t\t\t\tin", "\t\t\t\t    Source", ""]
    return "\n".join(out) + "\n"


def write_model(data_folder: str):
    d = SM / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (d / "cultures").mkdir(exist_ok=True)
    for n, cols in TABLES.items():
        (d / "tables" / f"{n}.tmdl").write_text(table_tmdl(n, cols), encoding="utf-8")
    (d / "tables" / "_Measures.tmdl").write_text(measures_tmdl(), encoding="utf-8")
    (d / "relationships.tmdl").write_text("\n".join(f"relationship {tag(a + b)}\n\tfromColumn: {a}\n\ttoColumn: {b}\n" for a, b in RELS), encoding="utf-8")
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{data_folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
        f"\tlineageTag: {tag('DataFolder')}\n\n\tannotation PBI_ResultType = Text\n", encoding="utf-8")
    refs = "\n".join(f"ref table {n}" for n in ["_Measures", *TABLES])
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\n"
                                  "annotation __PBI_TimeIntelligenceEnabled = 0\n\nannotation PBI_ProTooling = [\"DevMode\"]\n\n"
                                  f"{refs}\n\nref cultureInfo en-US\n", encoding="utf-8")
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1550\n\n", encoding="utf-8")
    (d / "cultures" / "en-US.tmdl").write_text('cultureInfo en-US\n\n\tlinguisticMetadata =\n\t\t\t{\n\t\t\t  "Version": "1.0.0",\n\t\t\t  "Language": "en-US"\n\t\t\t}\n\t\tcontentType: json\n\n', encoding="utf-8")
    (SM / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2), encoding="utf-8")
    (SM / ".platform").write_text(json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                                              "metadata": {"type": "SemanticModel", "displayName": NAME},
                                              "config": {"version": "2.0", "logicalId": tag("sm-logical")}}, indent=2), encoding="utf-8")


# ------------------------------------------------------------------------------------------------
# Report (PBIR)
# ------------------------------------------------------------------------------------------------
BRAND = ed.Brand(
    name="JAMII MOBILE", tagline="Customer value & retention · Jan 2024 – Oct 2026", disclaimer="fictional operator · synthetic data",
    masthead="#0b0e12", accent="#2ec4a0", accent_text="#0b0e12", tab="#1f2630", tab_hover="#2a3340",
    paper="#11151a", panel="#1b2027", panel_alt="#20262e", ink="#f0efec", ink2="#a9b0ba", hairline="#2c333d", grid="#2a3038",
    kicker="#2ec4a0", headline="#f0efec", number="#f0efec", focus=FOCUS, problem=PROBLEM, context=CONTEXT,
    strip="signal_strip.png", todo_bg="#0f3a33", todo_ink="#e6f4f0", todo_head="#2ec4a0", shadow=False)
ed.configure(BRAND, {
    "month_start": "Month", "customer_type": "Type", "county": "County", "value_segment": "Segment", "date": "Date",
    "plan_type": "Plan", "cohort_label": "Cohort", "engagement_status": "Status", "months_since_acquisition": "Months since joining",
    "Declining Customers": "Customers", "Revenue at Risk (annualised)": "At risk (KES/yr)", "service_type": "Service",
    "Churn Rate %": "Monthly churn", "value_tier": "Value tier", "complaint_experience": "Complaint outcome",
    "Customer Share of Selection": "Share of customers", "Revenue Share of Selection": "Share of revenue",
    "Complaints per 1,000 Subscriber-Months": "Per 1,000", "County Status": "Status", "Avg Days to Resolve": "Avg days",
    "Churned % (complaint link)": "Churned"}, seed=NAME)
Ms, Co, lit, col = ed.Ms, ed.Co, ed.lit, ed.col
visual, tile, todo, story, xline = ed.visual, ed.tile, ed.todo, ed.story, ed.xline
HERO, LOW1, LOW2 = ed.HERO, ed.LOW1, ed.LOW2


def masthead(p):
    return ed.masthead(p, [("s_date", Co("dim_date", "date"), 236, False), ("s_type", Co("dim_customer", "customer_type"), 104, True),
                           ("s_seg", Co("dim_customer", "value_segment"), 116, True)])


def build_pages():
    pages = []
    # page ids keep the original names so existing page folders are reused
    MS = Co("dim_date", "month_start")
    p = hid("p1")
    v = masthead(p)
    v.append(story(p, "Overview", "Revenue up 19% a year, but 1 in 6 customers still leaves",
                   "October 2026 revenue was KES 17.9M from 19,182 active customers. ARPU rose 7.6%, helped by the July 2025 price rise, "
                   "while about 1.5% of the base closes its line every month."))
    v.append(visual(p, "rev", "lineChart", HERO, roles={"Category": [MS], "Y": [Ms("Revenue")]},
                    title="Monthly revenue (KES)", subtitle="All customers · dashed line marks the bundle price change",
                    sort=(MS, "Ascending"), objects={**ed.measure_series_fill({"Revenue": FOCUS}),
                                                    "xAxisReferenceLine": [xline("2025-07-01", "Bundle prices +10%", 1, PROBLEM)]}))
    v.append(visual(p, "svc", "clusteredBarChart", LOW1, roles={"Category": [Co("fact_service_revenue", "service_type")], "Y": [Ms("Service Revenue")]},
                    title="Postpaid bills and data lead", subtitle="Revenue by service, KES",
                    sort=(Ms("Service Revenue"), "Descending"), objects=ed.measure_series_fill({"Service Revenue": FOCUS})))
    v.append(visual(p, "act", "lineChart", LOW2, roles={"Category": [MS], "Y": [Ms("Active Customers")]},
                    title="Active customers per month", sort=(MS, "Ascending"), objects=ed.measure_series_fill({"Active Customers": FOCUS})))
    v += [tile(p, "Revenue (latest month)", 90, "Revenue, Oct 2026 (KES millions)", sub_measure="Δ Revenue", units=(1000000, 1)),
          tile(p, "Active Customers (latest month)", 192, "Active customers, Oct 2026", sub_measure="Δ Active Customers"),
          tile(p, "ARPU (latest month)", 294, "ARPU, Oct 2026 (KES)", sub_measure="Δ ARPU"),
          tile(p, "Annualised Churn %", 396, "Customers lost per year", sub_measure="Monthly Churn Text"),
          todo(p, ["Call the declining Platinum and Gold customers first",
                   "Fix network complaints in Garissa, Kilifi and Turkana",
                   "Protect entry-level bundles in the next price change"], 498, 214)]
    pages.append((p, "Overview", v))

    p = hid("p2")
    v = masthead(p)
    v.append(story(p, "Segmentation", "The top 10% of customers bring 36% of revenue",
                   "Segments are set on early spend, before anyone leaves. A Platinum customer is worth about 20 times a Bronze customer "
                   "over a lifetime, and 72% of Platinum customers are postpaid."))
    v.append(visual(p, "seg", "clusteredBarChart", HERO,
                    roles={"Category": [Co("dim_customer", "value_segment")], "Y": [Ms("Customer Share of Selection"), Ms("Revenue Share of Selection")]},
                    title="Share of customers vs share of revenue", subtitle="Grey: share of customers · blue: share of revenue",
                    sort=(Ms("Revenue Share of Selection"), "Descending"),
                    objects=ed.measure_series_fill({"Customer Share of Selection": CONTEXT, "Revenue Share of Selection": FOCUS})))
    v.append(visual(p, "tenure", "clusteredColumnChart", LOW1, roles={"Category": [Co("fact_customer_month", "tenure_band")], "Y": [Ms("ARPU")]},
                    title="Spend grows with tenure", subtitle="ARPU by tenure, KES", sort=(Co("fact_customer_month", "tenure_band"), "Ascending"),
                    objects=ed.measure_series_fill({"ARPU": FOCUS})))
    v.append(visual(p, "county", "clusteredBarChart", LOW2, roles={"Category": [Co("dim_customer", "county")], "Y": [Ms("Revenue")]},
                    title="Nairobi brings a quarter of revenue", subtitle="Revenue by county, KES", sort=(Ms("Revenue"), "Descending"),
                    objects=ed.measure_series_fill({"Revenue": FOCUS})))
    v += [tile(p, "Revenue", 90, "Revenue in period (KES millions)", sub_measure="Δ Revenue", units=(1000000, 1)),
          tile(p, "ARPU", 192, "ARPU in period (KES)", sub="revenue per active customer-month"),
          tile(p, "Data MB per Active Customer", 294, "Data per active customer (MB)", sub="per month · +25% year on year"),
          tile(p, "Voice Min per Active Customer", 396, "Voice per active customer (min)", sub="per month · flat year on year"),
          todo(p, ["Give Platinum and Gold an account manager or priority line",
                   "Sell data bundles to the voice-first prepaid group",
                   "Track segments on early spend, not lifetime spend"], 498, 214)]
    pages.append((p, "Segmentation", v))

    p = hid("p3")
    v = masthead(p)
    v.append(story(p, "Retention", "Customers leave in months 4–6, cheap prepaid first",
                   "About 90% of each cohort is active after 3 months and 71–74% after a year. Bronze customers churn six times faster than "
                   "Platinum, and the July 2025 price rise pushed prepaid Bronze churn to 3.6% a month."))
    cf = {"values": [{"properties": {"backColor": {"solid": {"color": {"expr": ed.fld(Ms("Retention Colour"))}}},
                                     "fontColor": {"solid": {"color": {"expr": ed.fld(Ms("Retention Font Colour"))}}}},
                      "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "_Measures.Retention %"}}],
          "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}]}
    v.append(visual(p, "cohort", "pivotTable", HERO,
                    roles={"Rows": [Co("cohort_retention", "cohort_label")], "Columns": [Co("cohort_retention", "months_since_acquisition")],
                           "Values": [Ms("Retention %")]},
                    title="Cohort retention: % of each month's new customers still active k months later",
                    subtitle="Darker = more retained · numbers in every cell", objects=cf))
    v.append(visual(p, "churn", "lineChart", LOW1, roles={"Category": [MS], "Y": [Ms("Churn Rate %")]},
                    title="Monthly churn, % of opening base", sort=(MS, "Ascending"),
                    objects={**ed.measure_series_fill({"Churn Rate %": FOCUS}),
                             "xAxisReferenceLine": [xline("2025-07-01", "Price rise", 1, PROBLEM)]}))
    v.append(visual(p, "churn_seg", "clusteredBarChart", LOW2, roles={"Category": [Co("dim_customer", "value_segment")], "Y": [Ms("Churn Rate %")]},
                    title="Bronze churns six times faster", subtitle="Monthly churn by value segment", sort=(Ms("Churn Rate %"), "Descending"),
                    objects=ed.measure_fill("Colour Segment Churn")))
    risk = visual(p, "risk", "tableEx", (880, 294, 380, 196),
                  roles={"Values": [Co("dim_customer", "value_segment"), Ms("Declining Customers"), Ms("Revenue at Risk (annualised)")]},
                  title="Watch list: declining customers", subtitle="Spend down more than half, Aug–Oct 2026",
                  sort=(Ms("Revenue at Risk (annualised)"), "Descending"),
                  filters=[{"name": ed.hid("f_eng"), "field": ed.fld(Co("dim_customer", "engagement_status")), "type": "Categorical",
                            "filter": {"Version": 2, "From": [{"Name": "c", "Entity": "dim_customer", "Type": 0}],
                                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": "engagement_status"}}],
                                                                      "Values": [[{"Literal": {"Value": "'Declining (>50% revenue drop)'"}}], [{"Literal": {"Value": "'Silent (no activity Aug-Oct)'"}}]]}}}]}}])
    v += [tile(p, "Avg Monthly Churn % (from May 2024)", 90, "Average monthly churn", sub="lines closed ÷ lines open at month start"),
          tile(p, "Revenue at Risk (annualised)", 192, "Revenue at risk (KES millions a year)", sub_measure="Risk Share Text", units=(1000000, 1)),
          risk,
          todo(p, ["Call the 173 declining Platinum and Gold customers this month",
                   "Usage check at day 45, before the 90-day closure clock",
                   "Keep an entry bundle at the old price"], 498, 214)]
    pages.append((p, "Retention", v))

    p = hid("p4")
    v = masthead(p)
    v.append(story(p, "Customer experience", "Unresolved complaints are where customers are lost",
                   "Within each value tier, customers whose complaint was never resolved churned 1.2–1.5× more than those who never complained, "
                   "while resolved complainers churned less. Network tickets take 12.8 days on average."))
    v.append(visual(p, "link", "clusteredColumnChart", HERO,
                    roles={"Category": [Co("complaint_churn_link", "complaint_experience")], "Series": [Co("complaint_churn_link", "value_tier")],
                           "Y": [Ms("Churned % (complaint link)")]},
                    title="Churn within 14 months, by complaint outcome", subtitle="Customers subscribed in Jan 2025 · blue: Platinum/Gold · grey: Silver/Bronze",
                    sort=(Co("complaint_churn_link", "complaint_experience"), "Ascending"),
                    objects=ed.series_fill("complaint_churn_link", "value_tier",
                                           {"Higher value (Platinum/Gold)": FOCUS, "Lower value (Silver/Bronze)": CONTEXT}, CONTEXT,
                                           ["Higher value (Platinum/Gold)", "Lower value (Silver/Bronze)"])))
    v.append(visual(p, "cat", "clusteredBarChart", LOW1, roles={"Category": [Co("fact_complaints", "complaint_category")], "Y": [Ms("Complaints")]},
                    title="Network and data speed lead", subtitle="Complaints by category", sort=(Ms("Complaints"), "Descending"),
                    objects=ed.measure_fill("Colour Complaint Category")))
    v.append(visual(p, "days", "clusteredBarChart", LOW2, roles={"Category": [Co("fact_complaints", "complaint_category")], "Y": [Ms("Avg Days to Resolve")]},
                    title="...and take longest to fix", subtitle="Average days to resolve", sort=(Ms("Avg Days to Resolve"), "Descending"),
                    objects=ed.measure_fill("Colour Complaint Category")))
    status = visual(p, "county_status", "tableEx", (880, 90, 380, 226),
                    roles={"Values": [Co("dim_customer", "county"), Ms("Complaints per 1,000 Subscriber-Months"), Ms("County Status")]},
                    title="Network status by county", subtitle="Watch = 25+ complaints per 1,000 subscriber-months",
                    sort=(Ms("Complaints per 1,000 Subscriber-Months"), "Descending"),
                    objects={"values": [{"properties": {"fontColor": ed.mcol("Colour County Status")}, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "_Measures.County Status"}}],
                             "total": [{"properties": {"totals": lit("false")}}]})
    v += [status,
          tile(p, "Unresolved Complaint %", 324, "Complaints never resolved", sub="unresolved or escalated"),
          todo(p, ["7-day target for network and data-speed tickets",
                   "Escalate to network engineering in Garissa, Kilifi, Turkana",
                   "Callback for any high-value complaint open 7+ days"], 428, 284)]
    pages.append((p, "Experience", v))
    return pages


def write_report():
    d = RP / "definition"
    if (d / "pages").exists():
        shutil.rmtree(d / "pages")
    (d / "pages").mkdir(parents=True)
    tpl = PB / "_template"
    shutil.copytree(tpl / "StaticResources", RP / "StaticResources", dirs_exist_ok=True)
    (RP / "StaticResources" / "RegisteredResources").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PB / "theme.json", RP / "StaticResources" / "RegisteredResources" / "theme.json")
    shutil.copyfile(PB / "signal_strip.png", RP / "StaticResources" / "RegisteredResources" / "signal_strip.png")
    shutil.copyfile(tpl / "version.json", d / "version.json")
    report = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.2.0/schema.json",
              "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.60", "type": "SharedResources"},
                                  "customTheme": {"name": "theme.json", "reportVersionAtImport": "5.60", "type": "RegisteredResources"}},
              "layoutOptimization": "None",
              "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                                    "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
                                   {"name": "RegisteredResources", "type": "RegisteredResources",
                                    "items": [{"name": "theme.json", "path": "theme.json", "type": "CustomTheme"},
                                              {"name": "signal_strip.png", "path": "signal_strip.png", "type": "Image"}]}],
              "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                           "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}}
    (d / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pages = build_pages()
    for p, disp, vs in pages:
        pd_ = d / "pages" / p
        (pd_ / "visuals").mkdir(parents=True)
        (pd_ / "page.json").write_text(json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.2.0/schema.json",
                                                   "name": p, "displayName": disp, "displayOption": "FitToPage", "height": 720, "width": 1280,
                                                   "objects": ed.page_objects()}, indent=2), encoding="utf-8")
        for i, vj in enumerate(vs):
            vj["position"]["tabOrder"] = i; vj["position"]["z"] = i
            (pd_ / "visuals" / vj["name"]).mkdir()
            (pd_ / "visuals" / vj["name"] / "visual.json").write_text(json.dumps(vj, indent=2), encoding="utf-8")
    (d / "pages" / "pages.json").write_text(json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
                                                        "pageOrder": [p for p, _, _ in pages], "activePageName": pages[0][0]}, indent=2), encoding="utf-8")
    (RP / "definition.pbir").write_text(json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}, "byConnection": None}}, indent=2), encoding="utf-8")
    (RP / ".platform").write_text(json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                                              "metadata": {"type": "Report", "displayName": NAME},
                                              "config": {"version": "2.0", "logicalId": tag("rp-logical")}}, indent=2), encoding="utf-8")
    (PB / f"{NAME}.pbip").write_text(json.dumps({"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                                  "settings": {"enableAutoRecovery": True}}, indent=2), encoding="utf-8")
    return sum(len(v) for _, _, v in pages), len(pages)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-folder", default=str(ROOT / "data" / "processed" / "powerbi") + "\\")
    a = ap.parse_args()
    write_model(a.data_folder)
    nv, np_ = write_report()
    print(f"model: {len(TABLES) + 1} tables, {len(RELS)} relationships, {len(MEASURES)} measures; report: {np_} pages, {nv} visuals")
