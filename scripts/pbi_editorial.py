"""Editorial report style for Power BI PBIR, shared by the report generator.

Pages read like a business newspaper: a masthead with page tabs and slicers, a patterned brand strip,
a kicker + serif headline + standfirst, one hero chart, two supporting charts, a column of big-number
tiles and a "What we'd do" box.

Colour rules (validated for colour-vision deficiency; see powerbi/README.md):
  focus = blue, problem = orange, context = grey. Colour is never the only cue: bars carry data labels,
  subtitles say what the colours mean, status uses symbol + text, and deltas use arrows.

Call configure(...) once, then use the builders. Every builder returns a PBIR visual.json dict.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

VC = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.4.0/schema.json"


@dataclass
class Brand:
    name: str                 # wordmark, e.g. "JAMII MOBILE"
    tagline: str              # second masthead line
    disclaimer: str           # e.g. "fictional operator · synthetic data"
    masthead: str             # masthead background
    accent: str               # wordmark / selected tab / tile rule
    accent_text: str          # text colour on the accent (selected tab)
    tab: str                  # unselected tab fill
    tab_hover: str
    paper: str                # page background
    panel: str                # panel background
    panel_alt: str            # alternate table row
    ink: str                  # primary text
    ink2: str                 # secondary text
    hairline: str             # panel border
    grid: str                 # chart gridlines
    kicker: str               # small section label above the headline
    headline: str             # headline colour
    number: str               # tile number colour
    focus: str                # data: focus series
    problem: str              # data: problem series
    context: str              # data: context series
    strip: str                # registered image name for the brand strip
    todo_bg: str              # "What we'd do" box
    todo_ink: str
    todo_head: str
    shadow: bool = True
    serif: str = "Georgia"
    numbers: str = "Segoe UI Semibold"


B: Brand = None
LABELS: dict = {}
MTABLE = "_Measures"
SEED = "report"


def configure(brand: Brand, labels: dict, seed: str, measure_table: str = "_Measures"):
    global B, LABELS, SEED, MTABLE
    B, LABELS, SEED, MTABLE = brand, labels, seed, measure_table


def hid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, (SEED,) + parts)).encode()).hexdigest()[:20]


lit = lambda v: {"expr": {"Literal": {"Value": v}}}
Ms = lambda n: ("Measure", MTABLE, n)
Co = lambda t, c: ("Column", t, c)
fld = lambda r: {r[0]: {"Expression": {"SourceRef": {"Entity": r[1]}}, "Property": r[2]}}
col = lambda c: {"solid": {"color": lit(f"'{c}'")}}
mcol = lambda m: {"solid": {"color": {"expr": fld(Ms(m))}}}


def proj(r, active=False):
    p = {"field": fld(r), "queryRef": f"{r[1]}.{r[2]}", "nativeQueryRef": r[2]}
    if r[2] in LABELS:
        p["displayName"] = LABELS[r[2]]
    if active:
        p["active"] = True
    return p


def panel(title=None, subtitle=None, subtitle_measure=None, title_size=13, title_colour=None, shadow=None, bg=None):
    sh = B.shadow if shadow is None else shadow
    o = {"background": [{"properties": {"show": lit("true"), "color": col(bg or B.panel), "transparency": lit("0D")}}],
         "border": [{"properties": {"show": lit("true"), "color": col(B.hairline), "radius": lit("12D")}}],
         "dropShadow": [{"properties": {"show": lit("true" if sh else "false"), "preset": lit("'BottomRight'"),
                                        "color": col("#000000"), "transparency": lit("88D")}}],
         "padding": [{"properties": {"top": lit("8D"), "bottom": lit("6D"), "left": lit("12D"), "right": lit("10D")}}]}
    if title:
        o["title"] = [{"properties": {"show": lit("true"), "text": lit(f"'{title}'"), "fontColor": col(title_colour or B.headline),
                                      "fontSize": lit(f"{title_size}D"), "bold": lit("true"), "titleWrap": lit("true")}}]
    else:
        o["title"] = [{"properties": {"show": lit("false")}}]
    if subtitle or subtitle_measure:
        text = {"expr": fld(Ms(subtitle_measure))} if subtitle_measure else lit(f"'{subtitle}'")
        o["subTitle"] = [{"properties": {"show": lit("true"), "text": text, "fontColor": col(B.ink2), "fontSize": lit("10D")}}]
    return o


def table_objects():
    return {"columnHeaders": [{"properties": {"fontColor": col(B.headline), "backColor": col(B.panel), "bold": lit("true")}}],
            "values": [{"properties": {"fontColorPrimary": col(B.ink), "backColorPrimary": col(B.panel),
                                       "fontColorSecondary": col(B.ink), "backColorSecondary": col(B.panel_alt)}}],
            "total": [{"properties": {"fontColor": col(B.ink), "backColor": col(B.panel)}}],
            "grid": [{"properties": {"gridHorizontalColor": col(B.hairline), "gridVerticalColor": col(B.hairline),
                                     "outlineColor": col(B.hairline)}}],
            "rowHeaders": [{"properties": {"fontColor": col(B.ink), "backColor": col(B.panel)}}]}


def visual(page, key, vtype, pos, roles=None, title=None, sort=None, objects=None, filters=None, subtitle=None, container=None):
    x, y, w, h = pos
    v = {"visualType": vtype}
    if roles:
        v["query"] = {"queryState": {r: {"projections": [proj(f, active=(r in ("Category", "Rows") and i == 0 and vtype != "scatterChart"))
                                                         for i, f in enumerate(fs)]} for r, fs in roles.items()}}
        if sort:
            v["query"]["sortDefinition"] = {"sort": [{"field": fld(sort[0]), "direction": sort[1]}], "isDefaultSort": False}
    objects = dict(objects or {})
    if vtype in ("lineChart", "clusteredBarChart", "clusteredColumnChart", "scatterChart"):
        cat = {"showAxisTitle": lit("false"), "labelColor": col(B.ink2), "gridlineColor": col(B.grid)}
        if vtype == "clusteredBarChart":
            cat["maxMarginFactor"] = lit("40L")
        val = {"showAxisTitle": lit("false"), "labelColor": col(B.ink2), "gridlineColor": col(B.grid)}
        if vtype == "clusteredBarChart":
            val["show"] = lit("false")
        objects = {"legend": [{"properties": {"position": lit("'Top'"), "labelColor": col(B.ink2)}}], **objects,
                   "categoryAxis": [{"properties": cat}], "valueAxis": [{"properties": val}]}
        if vtype in ("clusteredBarChart", "clusteredColumnChart"):
            objects.setdefault("labels", [{"properties": {"show": lit("true"), "color": col(B.ink), "fontSize": lit("9D")}}])
        if vtype == "lineChart":
            objects.setdefault("lineStyles", [{"properties": {"strokeWidth": lit("3L")}}])
    if vtype in ("tableEx", "pivotTable"):
        objects = {**table_objects(), **objects}
    if objects:
        v["objects"] = objects
    if vtype != "textbox":
        v["visualContainerObjects"] = container or panel(title, subtitle)
    v["drillFilterOtherVisuals"] = True
    out = {"$schema": VC, "name": hid(page, key), "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0}, "visual": v}
    if filters:
        out["filterConfig"] = {"filters": filters}
    return out


def measure_fill(measure):
    return {"dataPoint": [{"properties": {"fill": mcol(measure)}, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]}


def series_fill(entity, column, mapping, default, values):
    return {"dataPoint": [{"properties": {"fill": col(mapping.get(v_, default))},
                           "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0,
                                        "Left": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": column}},
                                        "Right": {"Literal": {"Value": f"'{v_}'"}}}}}]}} for v_ in values]}


def measure_series_fill(mapping):
    return {"dataPoint": [{"properties": {"fill": col(c)}, "selector": {"metadata": f"{MTABLE}.{m}"}} for m, c in mapping.items()]}


def para(*runs):
    return [{"value": t, "textStyle": {"fontSize": f"{sz}pt", "color": c, **({"fontWeight": "bold"} if b else {}),
                                       **({"fontFamily": f} if f else {})}} for t, sz, c, b, f in runs]


def rich_text(page, key, paragraphs, pos, bg=None, pad=(4, 4, 0, 0)):
    v = visual(page, key, "textbox", pos, objects={"general": [{"properties": {"paragraphs": [{"textRuns": r} for r in paragraphs]}}]})
    vc = {"border": [{"properties": {"show": lit("false")}}],
          "padding": [{"properties": {"top": lit(f"{pad[0]}D"), "bottom": lit(f"{pad[1]}D"), "left": lit(f"{pad[2]}D"), "right": lit(f"{pad[3]}D")}}],
          "background": [{"properties": {"show": lit("true" if bg else "false"), **({"color": col(bg), "transparency": lit("0D")} if bg else {})}}]}
    v["visual"]["visualContainerObjects"] = vc
    return v


def image(page, key, item, pos):
    return visual(page, key, "image", pos,
                  objects={"general": [{"properties": {"imageUrl": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1, "ItemName": item}}}}}],
                           "imageScaling": [{"properties": {"imageScalingType": lit("'Fill'")}}]},
                  container={"background": [{"properties": {"show": lit("false")}}], "border": [{"properties": {"show": lit("false")}}],
                             "title": [{"properties": {"show": lit("false")}}],
                             "padding": [{"properties": {"top": lit("0D"), "bottom": lit("0D"), "left": lit("0D"), "right": lit("0D")}}]})


def slicer(page, key, ref, pos, dropdown=True):
    cont = panel(shadow=False)
    cont["padding"] = [{"properties": {"top": lit("2D"), "bottom": lit("2D"), "left": lit("8D"), "right": lit("8D")}}]
    objs = {"header": [{"properties": {"fontColor": col(B.headline), "textSize": lit("9D")}}],
            "items": [{"properties": {"fontColor": col(B.ink), "background": col(B.panel)}}]}
    if dropdown:
        objs["data"] = [{"properties": {"mode": lit("'Dropdown'")}}]
    return visual(page, key, "slicer", pos, roles={"Values": [ref]}, objects=objs, container=cont)


def masthead(page, slicers):
    """slicers: list of (key, column ref, width, dropdown) placed right-aligned in the masthead."""
    band = rich_text(page, "band", [para((B.name, 12, B.accent, True, "Bahnschrift"), ("    " + B.disclaimer, 9, B.ink2 if B.masthead == B.paper else "#b8c4da", False, None)),
                                    para((B.tagline, 9, "#dbe3f0", False, None))], (0, 0, 1280, 72), bg=B.masthead, pad=(12, 4, 20, 0))
    state = lambda i, fill: [{"properties": {"show": lit("true"), "fillColor": col(fill), "transparency": lit("0D")}, "selector": {"id": i}}]
    nav_objs = {"fill": state("default", B.tab) + state("hover", B.tab_hover) + state("selected", B.accent),
                "text": [{"properties": {"fontColor": col("#ffffff"), "fontSize": lit("10D")}, "selector": {"id": "default"}},
                         {"properties": {"fontColor": col(B.accent_text), "fontSize": lit("10D"), "bold": lit("true")}, "selector": {"id": "selected"}}],
                "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}},
                            {"properties": {"show": lit("false")}, "selector": {"id": "selected"}}]}
    nav = visual(page, "nav", "pageNavigator", (380, 18, 400, 36), objects=nav_objs,
                 container={"background": [{"properties": {"show": lit("false")}}], "border": [{"properties": {"show": lit("false")}}],
                            "title": [{"properties": {"show": lit("false")}}]})
    out = [band, nav]
    x = 1272
    for key, ref, w, dd in reversed(slicers):
        x -= w
        out.append(slicer(page, key, ref, (x, 7, w, 58), dropdown=dd))
        x -= 6
    out.append(image(page, "strip", B.strip, (0, 72, 1280, 10)))
    return out


def story(page, kicker, headline, standfirst):
    return rich_text(page, "story", [para((kicker.upper(), 9, B.kicker, True, None)),
                                     para((headline, 22, B.headline, True, B.serif)),
                                     para((standfirst, 10.5, B.ink2, False, None))], (20, 90, 840, 104), pad=(2, 2, 0, 0))


def tile(page, m, y, label, sub=None, sub_measure=None, units=None, h=96):
    cont = panel(label, subtitle=sub, subtitle_measure=sub_measure, title_size=10, title_colour=B.ink2, shadow=False)
    cont["divider"] = [{"properties": {"show": lit("true"), "color": col(B.accent), "width": lit("2D")}}]
    cont["padding"] = [{"properties": {"top": lit("6D"), "bottom": lit("0D"), "left": lit("12D"), "right": lit("10D")}}]
    u = {"labelDisplayUnits": lit(f"{units[0]}D"), "labelPrecision": lit(f"{units[1]}L")} if units else {"labelDisplayUnits": lit("1D")}
    return visual(page, "tile_" + m, "card", (880, y, 380, h), roles={"Values": [Ms(m)]},
                  objects={"categoryLabels": [{"properties": {"show": lit("false")}}],
                           "labels": [{"properties": {"fontSize": lit("24D"), "color": col(B.number), "fontFamily": lit(f"'{B.numbers}'"), **u}}]},
                  container=cont)


def todo(page, items, y, h):
    paras = [para(("WHAT WE'D DO", 10, B.todo_head, True, "Bahnschrift"))] + [para(("›  " + t, 11, B.todo_ink, False, None)) for t in items]
    return rich_text(page, "todo", paras, (880, y, 380, h), bg=B.todo_bg, pad=(14, 10, 16, 12))


def xline(day, label, idx, colour):
    return {"properties": {"show": lit("true"), "displayName": lit(f"'{label}'"),
                           "value": {"expr": {"Literal": {"Value": f"datetime'{day}T00:00:00'"}}},
                           "lineColor": col(colour), "style": lit("'dashed'"), "transparency": lit("20D"), "position": lit("'front'"),
                           "dataLabelShow": lit("true"), "dataLabelColor": col(colour), "dataLabelText": lit("'Name'"),
                           "dataLabelHorizontalPosition": lit("'right'"), "dataLabelVerticalPosition": lit("'above'")},
            "selector": {"id": str(idx)}}


def page_objects():
    return {"background": [{"properties": {"color": col(B.paper), "transparency": lit("0D")}}],
            "outspace": [{"properties": {"color": col(B.paper), "transparency": lit("0D")}}]}


HERO, LOW1, LOW2 = (20, 200, 840, 268), (20, 478, 414, 234), (446, 478, 414, 234)


def growth_dax(m, pct=True):
    fmt = '"▲ 0%;▼ 0%;0%"' if pct else '"▲ 0.0 pts;▼ 0.0 pts;0.0 pts"'
    diff = "DIVIDE ( b - a, a )" if pct else "( b - a ) * 100"
    return ("VAR f = MIN ( dim_date[month_start] )\nVAR l = MAX ( dim_date[month_start] )\n"
            f"VAR a = CALCULATE ( [{m}], dim_date[month_start] = f )\nVAR b = CALCULATE ( [{m}], dim_date[month_start] = l )\n"
            f"RETURN IF ( NOT ISBLANK ( a ) && a <> 0, FORMAT ( {diff}, {fmt} ) & \"  \" & FORMAT ( f, \"mmm yy\" ) & \" → \" & FORMAT ( l, \"mmm yy\" ) )")
