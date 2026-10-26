"""Anthropic S-1 Economics: a standalone, shareable report page (pure Python + Plotly).

Part I answers four questions from the filing's own figures: the margin bridge, compute efficiency, the economics of the
contracted compute (ledger, payment calendar, discount rates, reverse DCF with live assumptions, stress tests) and
customer concentration. Part II (from src/s1_jev_reading.py) explains how TypeSafe's Jev was used to read the filing and shows what the filing
emphasizes. Every filing figure carries its quote; click a chart element or a table row to read the source.

Writes two files: docs/index.html (a complete document; open it locally or serve it with GitHub Pages) and
build/anthropic_s1_dashboard_artifact.html (the same page without the document skeleton, for publishing as a Claude artifact).
Run from the repository root:  python src/s1_dashboard.py
"""
import html
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

import s1_economics as E
from paths import BUILD, DATA_JEV, DOCS, WEB
from s1_filing import filing

HERE = Path(__file__).resolve().parent
F = filing()
esc = html.escape
pct = lambda v, d=0: f"{v * 100:.{d}f}%"
money = lambda v, d=0: f"${v:,.{d}f}B"
SERIES = ["#3b7ddd", "#e0703a", "#22a06b", "#d39b00", "#7b61d9", "#d64545", "#8a94a6", "#1aa3b8"]
VERDICT_COLOR = {"overweighted (more words than facts)": "#e0703a", "underweighted (more facts than words)": "#22a06b", "proportionate": "#3b7ddd",
                 "depends on the evidence base": "#8a94a6", "no evidence outside risk factors": "#b8bfcb"}

# =================================================================== sources for the drawer
SOURCES = {}


def src(sid, title, meta, *texts):
    SOURCES[sid] = {"title": title, "meta": meta, "texts": [t for t in texts if t]}
    return sid


for k, f in E.FACTS.items():
    src(f"fact:{k}", f.label or k, f"{f.section} · p. {f.page} · value {f.value} {f.unit}", f.quote)

# =================================================================== Jev outputs (src/s1_jev_reading.py)
themes = pd.read_csv(DATA_JEV / "risk_themes.csv", index_col=0)
risks = pd.read_csv(DATA_JEV / "risk_factors.csv")
ev = pd.read_csv(DATA_JEV / "evidence_hits.csv", index_col=0)
fin = pd.read_csv(DATA_JEV / "financing.csv")
commits = pd.read_csv(DATA_JEV / "vendor_commitments.csv")
roles_counts = pd.read_csv(DATA_JEV / "counterparty_roles.csv", index_col=0)
role_pass = pd.read_csv(DATA_JEV / "counterparty_role_passages.csv")
manual = pd.read_csv(DATA_JEV / "manual_checks.csv")
manual_ok = int(manual.agrees.sum())
THEMES = list(themes.index)
ROLES = ["investor", "financing_source", "supplier", "lessor", "customer", "distribution_channel", "competitor"]
SECTIONS = [c for c in ["PROSPECTUS SUMMARY", "USE OF PROCEEDS", "CAPITALIZATION", "MD&A", "BUSINESS", "GOVERNANCE", "RELATED PERSON TRANSACTIONS",
                        "DESCRIPTION OF CAPITAL STOCK", "SHARES ELIGIBLE FOR FUTURE SALE", "FINANCIAL STATEMENTS", "PART II"] if c in set(ev.section)]

# per-stage Jev statistics, written by src/s1_jev_reading.py
_rm = pd.read_csv(DATA_JEV / "run_metrics.csv")
STAGES = [{"stage": r.section, "requests": int(r.calls), "judgments": int(r.questions), "median_ms": float(r.median_ms), "cost": float(r.cost_usd)} for r in _rm.itertuples()]
assert STAGES and STAGES[-1]["stage"] == "TOTAL", "run_metrics.csv has no TOTAL row; re-run src/s1_jev_reading.py"
JEV_TOTAL = STAGES[-1]
ROLE_RUN = {"requests": len(role_pass), "judgments": len(role_pass) * len(ROLES)}
STAGE_TEXT = {
    "2 risk typing pass 1": ("Type each of the 88 risk factors", "Choice of 17 themes; Score for specificity and consequence; Noul for already-happened, mitigation, multi-role counterparty; Choice for who controls it"),
    "2 risk typing pass 2": ("Repeat theme and specificity", "A second pass; a theme that flips is flagged and the first kept"),
    "4 evidence": ("Find the facts behind each theme", "17 yes/no questions per passage, one per theme, over every passage outside Risk Factors"),
    "5 peer match": ("Match headings to CoreWeave's S-1", "Choice among the ten closest peer headings (BM25), or none"),
    "7 commitments": ("Read each compute agreement", "Choice of the aggregate amount from regex candidates; Choice of payment basis and cancelability; Noul for true-up and vendor-side dependency"),
    "7 instruments": ("Type each financing instrument", "Choice of kind, status, settlement, security, counterparty; Noul for compute-linked, conditional, converts to equity"),
    "7 roles": ("Map counterparty roles", "Seven yes/no role questions per passage naming a counterparty"),
}

# ---------------------------------------------- drawer sources for Part II
bodies = {r["rid"]: r for r in F.risk_factors()}
for r in risks.itertuples():
    src(f"risk:{r.rid}", f"{r.rid} · {r.heading}", f"{r.group_short} · p. {r.page} · {r.words:,} words · theme {r.theme} · specificity {r.specificity:.2f}/3 · "
        + (f"CoreWeave counterpart: {r.peer_heading}" if r.peer_shared else "no CoreWeave counterpart"), bodies.get(r.rid, {}).get("body", ""))
hits = ev[THEMES] >= 0.7
for th in THEMES:
    rs = risks[risks.theme == th]
    src(f"theme:{th}", f"Theme: {th.replace('_', ' ')}", f"{len(rs)} risk factors", *[f"{x.rid} (p. {x.page}, {x.words:,} words): {x.heading}" for x in rs.itertuples()])
    for sec in SECTIONS:
        pids = list(ev.index[(ev.section == sec) & hits[th]])
        if pids:
            src(f"ev:{th}|{sec}", f"{th.replace('_', ' ')} × {sec}", f"{len(pids)} passages Jev judged to carry a fact for this theme (p ≥ 0.7), highest first",
                *[f"[p. {F.passage_by_pid[pid]['page']} · p={ev.loc[pid, th]:.2f}] " + F.passage_by_pid[pid]["text"] for pid in sorted(pids, key=lambda x: -ev.loc[x, th])])
for name in roles_counts.index:
    d = role_pass[role_pass.counterparty == name]
    for role in ROLES:
        dd = d.sort_values(role, ascending=False)
        src(f"role:{name}|{role}", f"{name} · {role.replace('_', ' ')}", f"{len(dd)} passages naming {name}, ranked by Jev's probability for this role",
            *[f"[{x.section} p. {x.page} · p={getattr(x, role):.2f}] {x.text}" for x in dd.itertuples()])
for v, ptxt in F.agreement_paragraphs().items():
    src(f"agreement:{v}", f"{v}: infrastructure agreement", "MD&A · Liquidity and Capital Resources · Infrastructure Service Arrangements", ptxt)
for b, t in F.liquidity_blocks().items():
    src(f"block:{b}", b, "MD&A · Liquidity and Capital Resources", t)
for l in E.LEDGER:
    src(f"ledger:{l[0]}", l[2], f"{l[1]} · {l[4]} · window {l[6]} ({l[7]})", *[f"[{E.FACTS[k].label} · {E.FACTS[k].section} p. {E.FACTS[k].page}] {E.FACTS[k].quote}" for k in l[8] if k in E.FACTS])
for i, r in E.RECON.iterrows():
    src(f"recon:{i}", r.check, money(r.value_busd, 1) if pd.notna(r.value_busd) else "", r.detail)

# =================================================================== Part II figures (colors themed in the browser)
PYFIGS = []


def pyfig(fid, fig, height):
    fig.update_layout(height=height, margin=dict(l=60, r=24, t=56, b=56), font=dict(family="Public Sans, system-ui, sans-serif", size=12), hoverlabel=dict(font_size=12))
    PYFIGS.append(fid)
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=f"fig-{fid}", config={"displaylogo": False, "responsive": True})


t = themes.copy()
t["hover"] = [(f"<b>{i.replace('_', ' ')}</b><br>{r.factors} factors · {r.words:,} words ({r.word_share:.1%} of the section)<br>fact-bearing passages: {r.evidence_passages} ({r.evidence_share:.1%}); "
               f"operating sections only {r.evidence_share_operating:.1%}<br>index {r.weight_index} · operating {r.weight_index_operating}<br><b>{r.robust_verdict}</b><br>"
               f"specificity {r.specificity:.2f}/3 · peer-shared {r.peer_shared_share:.0%}<br><i>click for its factors</i>") for i, r in t.iterrows()]
sizes = {"peer-shared share": (12 + 40 * t.peer_shared_share.fillna(0)).tolist(), "specificity": (8 + 14 * t.specificity).tolist(), "uniform": [16] * len(t)}
fig = go.Figure()
cats = [c for c in VERDICT_COLOR if c in set(t.robust_verdict)]
pos = {th: i for i, th in enumerate(t.index)}
for c in cats:
    sub = t[t.robust_verdict == c]
    fig.add_trace(go.Scatter(x=sub.evidence_share * 100, y=sub.word_share * 100, mode="markers+text", text=[s.replace("_", " ") for s in sub.index], textposition="top center", textfont=dict(size=10),
                             marker=dict(size=[sizes["peer-shared share"][pos[i]] for i in sub.index], color=VERDICT_COLOR[c], opacity=0.85), name=c, customdata=sub.hover, hovertemplate="%{customdata}<extra></extra>",
                             meta=list(sub.index)))
lim = float(max(t.evidence_share.max(), t.word_share.max(), t.evidence_share_operating.max()) * 100 * 1.15)
for slope, dash, label in ((1, "dash", "words = facts"), (1.5, "dot", "1.5× (over above)"), (1 / 1.5, "dot", "0.67× (under below)")):
    fig.add_trace(go.Scatter(x=[0, lim], y=[0, lim * slope], mode="lines", line=dict(color="#8a94a6", dash=dash, width=1), name=label, hoverinfo="skip"))
idx = {c: [pos[i] for i in t[t.robust_verdict == c].index] for c in cats}
fig.update_layout(xaxis=dict(title="share of fact-bearing passages elsewhere in the filing (%)", range=[0, lim]), yaxis=dict(title="share of Risk Factors words (%)", range=[0, lim]),
                  legend=dict(orientation="h", y=-0.2),
                  updatemenus=[dict(type="buttons", direction="right", x=0, xanchor="left", y=1.12, yanchor="bottom", showactive=True, buttons=[
                      dict(label=f"evidence: {n}", method="restyle", args=[{"x": [(t[col].iloc[idx[c]] * 100).tolist() for c in cats]}, list(range(len(cats)))]) for n, col in (("whole filing", "evidence_share"), ("operating sections", "evidence_share_operating"))]),
                               dict(type="dropdown", x=1, xanchor="right", y=1.12, yanchor="bottom", showactive=True, buttons=[dict(label=f"bubble: {k}", method="restyle", args=[{"marker.size": [[v[i] for i in idx[c]] for c in cats]}, list(range(len(cats)))]) for k, v in sizes.items()])])
FIG_WORDS = pyfig("words", fig, 600)

cnt = pd.DataFrame({th: hits[th].groupby(ev.section).sum() for th in THEMES}).T.reindex(index=THEMES, columns=SECTIONS).fillna(0)
meanp = pd.DataFrame({th: ev[th].groupby(ev.section).mean() for th in THEMES}).T.reindex(index=THEMES, columns=SECTIONS).fillna(0)
share = cnt.div(cnt.sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 100
tl = [s.replace("_", " ") for s in THEMES]
hov = np.array([[f"<b>{th.replace('_', ' ')}</b> × {sec}<br>{int(cnt.loc[th, sec])} passages at p ≥ 0.7 · {share.loc[th, sec]:.0f}% of the theme's evidence<br>mean probability {meanp.loc[th, sec]:.2f}<br><i>click to read them</i>" for sec in SECTIONS] for th in THEMES])
fig = go.Figure(go.Heatmap(z=cnt.values, x=SECTIONS, y=tl, text=cnt.values.astype(int), texttemplate="%{text}", textfont=dict(size=10), customdata=hov, meta=THEMES,
                           hovertemplate="%{customdata}<extra></extra>", colorbar=dict(title=dict(text="passages"), thickness=10), xgap=2, ygap=2))
fig.update_layout(xaxis=dict(tickangle=-30), yaxis=dict(autorange="reversed"),
                  updatemenus=[dict(type="buttons", direction="right", x=0, xanchor="left", y=1.08, yanchor="bottom", showactive=True, buttons=[
                      dict(label="passages", method="restyle", args=[{"z": [cnt.values], "text": [cnt.values.astype(int)], "texttemplate": "%{text}", "zmin": 0, "zmax": float(cnt.values.max()), "colorbar.title.text": "passages", "colorbar.ticksuffix": ""}]),
                      dict(label="share of the theme", method="restyle", args=[{"z": [share.values], "text": [np.round(share.values).astype(int)], "texttemplate": "%{text}%", "zmin": 0, "zmax": 100, "colorbar.title.text": "% of theme", "colorbar.ticksuffix": "%"}]),
                      dict(label="mean probability", method="restyle", args=[{"z": [meanp.values], "text": [np.round(meanp.values, 2)], "texttemplate": "%{text}", "zmin": 0, "zmax": 1, "colorbar.title.text": "mean p", "colorbar.ticksuffix": ""}])])])
FIG_EVIDENCE = pyfig("evidence", fig, 640)

r = risks.copy()
r["short"] = r.heading.str.slice(0, 90) + np.where(r.heading.str.len() > 90, "…", "")
r["hover"] = [(f"<b>{x.rid}</b> · {x.group_short} · p. {x.page}<br>{esc(str(x.heading))[:200]}<br>{x.words:,} words · {x.theme.replace('_', ' ')} · specificity {x.specificity:.2f} · already happened {x.materialized:.2f}<br>"
               f"{'CoreWeave counterpart' if x.peer_shared else 'no CoreWeave counterpart'}<br><i>click to read it</i>") for x in r.itertuples()]
fig = go.Figure(go.Treemap(labels=["Risk Factors"] + THEMES + r.rid.tolist(), parents=[""] + ["Risk Factors"] * len(THEMES) + r.theme.tolist(), values=[0] + [0] * len(THEMES) + r.words.tolist(),
                           text=[""] + [f"{th.replace('_', ' ')}<br>{int(themes.loc[th, 'words']):,} words" for th in THEMES] + r.short.tolist(),
                           customdata=["All 88 risk factors"] + [f"<b>{th.replace('_', ' ')}</b><br>{int(themes.loc[th, 'factors'])} factors · {themes.loc[th, 'robust_verdict']}" for th in THEMES] + r.hover.tolist(),
                           hovertemplate="%{customdata}<extra></extra>", branchvalues="remainder", textinfo="text", pathbar=dict(visible=True), maxdepth=2,
                           marker=dict(colors=[np.nan] + [themes.loc[th, "specificity"] for th in THEMES] + r.specificity.tolist(), cmin=0, cmax=3, colorbar=dict(title=dict(text="specificity"), thickness=10))))
FIG_FACTORS = pyfig("factors", fig, 680)

ts_ = themes.sort_values("words")
fig = go.Figure()
fig.add_trace(go.Bar(y=[s.replace("_", " ") for s in ts_.index], x=ts_.peer_shared_words, orientation="h", name="factors with a CoreWeave counterpart", marker_color="#8a94a6", meta=list(ts_.index), hovertemplate="%{y}: %{x:,} peer-shared words<extra></extra>"))
fig.add_trace(go.Bar(y=[s.replace("_", " ") for s in ts_.index], x=ts_.words - ts_.peer_shared_words, orientation="h", name="factors with no counterpart", marker_color="#3b7ddd", meta=list(ts_.index), hovertemplate="%{y}: %{x:,} distinctive words<extra></extra>"))
fig.update_layout(barmode="stack", xaxis_title="words in the Risk Factors section", legend=dict(orientation="h", y=-0.14))
FIG_GENRE = pyfig("genre", fig, 560)

NAMES = list(roles_counts.index)
maxp = role_pass.groupby("counterparty")[ROLES].max().reindex(NAMES).fillna(0)
meanp_r = role_pass.groupby("counterparty")[ROLES].mean().reindex(NAMES).fillna(0)
n80 = role_pass.groupby("counterparty")[ROLES].apply(lambda d: (d >= 0.8).sum()).reindex(NAMES).fillna(0).astype(int)
nread = role_pass.groupby("counterparty").size().reindex(NAMES).fillna(0).astype(int)
hov = np.array([[f"<b>{n}</b> · {ro.replace('_', ' ')}<br>strongest passage p {maxp.loc[n, ro]:.2f} · mean p {meanp_r.loc[n, ro]:.2f}<br>{n80.loc[n, ro]} of {nread.loc[n]} passages at p ≥ 0.8<br><i>click to read them</i>" for ro in ROLES] for n in NAMES])
T_MAX, T_MEAN, T_CNT = "shade: strongest passage probability · label: passages at p ≥ 0.8", "shade: mean passage probability · label: passages at p ≥ 0.8", "shade and label: passages at p ≥ 0.8"
fig = go.Figure(go.Heatmap(z=maxp.values, x=[x.replace("_", " ") for x in ROLES], y=NAMES, zmin=0, zmax=1, text=np.where(n80.values > 0, n80.values.astype(str), ""), texttemplate="%{text}",
                           customdata=hov, hovertemplate="%{customdata}<extra></extra>", colorbar=dict(title=dict(text="max p"), thickness=10), xgap=2, ygap=2))
fig.update_layout(title=dict(text=T_MAX, x=0.01, font=dict(size=12)), yaxis=dict(autorange="reversed"), updatemenus=[dict(type="buttons", direction="right", x=0, xanchor="left", y=1.1, yanchor="bottom", showactive=True, buttons=[
    dict(label="strongest", method="update", args=[{"z": [maxp.values], "zmax": [1], "colorbar.title.text": "max p"}, {"title.text": T_MAX}]),
    dict(label="mean", method="update", args=[{"z": [meanp_r.values], "zmax": [1], "colorbar.title.text": "mean p"}, {"title.text": T_MEAN}]),
    dict(label="count", method="update", args=[{"z": [n80.values], "zmax": [float(n80.values.max())], "colorbar.title.text": "passages"}, {"title.text": T_CNT}])])])
FIG_ROLES = pyfig("roles", fig, 520)

c = commits.copy()
c["amt"] = c.regex_amount_busd.fillna(c.amount_busd)
fig = go.Figure()
for basis, color in {"fixed_minimum": "#e0703a", "mixed": "#d39b00", "fees_as_delivered": "#22a06b", "no_fixed_amount": "#8a94a6"}.items():
    sub = c[c.basis == basis]
    if len(sub):
        fig.add_trace(go.Bar(x=sub.vendor, y=sub.amt, name=basis.replace("_", " "), marker_color=color, customdata=np.stack([sub.cancelability.str.replace("_", " "), sub.true_up, sub.vendor_dependency], axis=1),
                             hovertemplate="<b>%{x}</b>: $%{y:,.1f}B<br>Jev: %{customdata[0]}<br>true-up p %{customdata[1]:.2f} · vendor-side dependency p %{customdata[2]:.2f}<br><i>click for the agreement</i><extra></extra>"))
fig.update_layout(barmode="group", yaxis_title="$ billions over the term", legend=dict(orientation="h", y=-0.15, title=dict(text="Jev: payment basis  ")))
FIG_VENDORS = pyfig("vendors", fig, 420)

# =================================================================== cross-check: Jev's reading of each agreement vs the ledger's treatment
LEDGER_TREAT = {"Microsoft": ("fixed regardless of usage, non-cancelable", lambda r: r.basis == "fixed_minimum" and r.cancelability == "non_cancelable_breach_only"),
                "Google": ("fixed with a true-up, non-cancelable", lambda r: r.basis in ("fixed_minimum", "mixed") and r.cancelability == "non_cancelable_breach_only" and r.true_up >= 0.5),
                "Amazon": ("fixed with a true-up, non-cancelable", lambda r: r.basis == "fixed_minimum" and r.cancelability == "non_cancelable_breach_only" and r.true_up >= 0.5),
                "SpaceXAI": ("binding through the notice period, cancelable after", lambda r: r.cancelability == "cancelable_on_notice"),
                "Nscale": ("conditional on the vendor's financing and delivery", lambda r: r.vendor_dependency >= 0.5 or r.cancelability == "cancelable_if_financing_or_lease_fails"),
                "Lambda": ("conditional on the vendor securing a facility lease (August agreement)", lambda r: r.vendor_dependency >= 0.5 or r.cancelability == "cancelable_if_financing_or_lease_fails"),
                "AMD": ("estimate outside the commitment figures", lambda r: r.basis == "no_fixed_amount")}
XCHECK = []
for r in commits.itertuples():
    treat, rule = LEDGER_TREAT[r.vendor]
    XCHECK.append({"vendor": r.vendor, "ledger": treat, "basis": r.basis.replace("_", " "), "cancel": r.cancelability.replace("_", " "), "true_up": r.true_up, "dep": r.vendor_dependency, "agrees": bool(rule(r)),
                   "amount_agrees": bool(r.jev_vs_regex_agree)})
XC = pd.DataFrame(XCHECK)

# =================================================================== data for the browser
eff = E.eff
v = lambda k: E.FACTS[k].value
B = E.BRIDGES["H1 2026"]
S0 = E.SCEN.set_index("utilization")
SL = E.SCEN_LOSS.set_index("utilization")
firm = float(E.RECON.loc[E.RECON.check.str.startswith("Of which firm"), "value_busd"].iloc[0])
DATA = {
    "years": E.YEARS,
    "bridges": {p: {**{k: v_ for k, v_ in b.items() if k != "steps"}, "steps": [{"label": s[0], "value": s[1], "kind": s[2], "src": f"fact:{s[3]}_{p}" if s[3] and f"{s[3]}_{p}" in E.FACTS else (f"fact:{s[3]}" if s[3] else None)} for s in b["steps"]]}
                for p, b in E.BRIDGES.items()},
    "cor_floor": E.ASSUMPTIONS["cor_compute_share_floor"]["value"],
    "eff": json.loads(eff.to_json(orient="records")), "releases": E.RELEASES,
    "ledger": [{"id": l[0], "category": l[1], "item": l[2], "status": l[4], "window": l[6], "basis": l[7], "base": l[9], "toggle": l[10],
                "amount": {str(rr): float(dict((x[0], x[3]) for x in E.LEDGERS[rr])[l[0]]) for rr in E.RAMPS},
                "sched": {str(rr): [round(float(x_), 4) for x_ in dict((x[0], x[5]) for x in E.LEDGERS[rr])[l[0]]] for rr in E.RAMPS}} for l in E.LEDGER],
    "ramps": [str(rr) for rr in E.RAMPS], "base": E.BASE, "obs": E.OBS, "assumptions": E.ASSUMPTIONS, "firm_total": firm,
    "observed_h2_2026_compute": E.qt["compute"]["Q2 2026"] * 2 / 1000,
    "cust": {"n10m": v("cust_10m_sep26"), "n1m": v("cust_1m_sep26"), "n100k": v("cust_100k_sep26"), "small_m": v("cust_small_users"), "top5_q3": E.TOP5_Q3,
             "series": [{"date": d_, "n": v(k), "src": f"fact:{k}"} for d_, k in [("2023-12-31", "cust_100k_dec23"), ("2024-12-31", "cust_100k_dec24"), ("2025-03-31", "cust_100k_mar25"), ("2025-06-30", "cust_100k_jun25"),
                                                                            ("2025-09-30", "cust_100k_sep25"), ("2025-12-31", "cust_100k_dec25"), ("2026-06-30", "cust_100k_jun26"), ("2026-09-30", "cust_100k_sep26")]],
             "shares": [{"date": d_, "share": v(k) / 100, "label": lab, "src": f"fact:{k}"} for d_, k, lab in [("2023-07-01", "rev_100k_share_fy23", "FY2023"), ("2024-07-01", "rev_100k_share_fy24", "FY2024"),
                                                                                                         ("2025-04-01", "rev_100k_share_h1_25", "H1 2025"), ("2025-07-01", "rev_100k_share_fy25", "FY2025"), ("2026-04-01", "rev_100k_share_h1_26", "H1 2026")]],
             "top5": [{"label": "Q1 2026", "share": 1 - v("outside_top5_q1_26") / 100, "src": "fact:outside_top5_q1_26"}, {"label": "Nine months to Sep 30, 2026", "share": v("top5_9m26") / 100, "src": "fact:top5_9m26"},
                      {"label": "Q3 2026", "share": 1 - v("outside_top5_q3_26") / 100, "src": "fact:outside_top5_q3_26"}]},
    "pyfigs": PYFIGS,
}

# =================================================================== computed findings and takeaways
over = [s.replace("_", " ") for s in themes.index[themes.robust_verdict.str.startswith("over")]]
under = [s.replace("_", " ") for s in themes.index[themes.robust_verdict.str.startswith("under")]]
dep = [s.replace("_", " ") for s in themes.index[themes.robust_verdict == "depends on the evidence base"]]
peer_share = risks[risks.peer_shared].words.sum() / risks.words.sum()
mat_share = risks[risks.materialized >= 0.5].words.sum() / risks.words.sum()
q1, q5 = eff.iloc[1], eff.iloc[5]
g90 = S0.loc[0.9]
g90L = SL.loc[0.9]
ch_after = (B["revenue"] - B["compute"] - B["channel_floor"]) / B["revenue"]
listj = lambda xs: ", ".join(xs[:-1]) + (" and " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "none"))
fmt_g = lambda g: "not reachable within capacity" if (g is None or (isinstance(g, float) and math.isnan(g))) else f"{g:.0%} a year"
ev_fs = cnt.sum()
top_sec = ev_fs.sort_values(ascending=False)
rp_amz = int((maxp.loc["Amazon"] >= 0.8).sum()); rp_goog = int((maxp.loc["Google"] >= 0.8).sum())
sparse = [n for n in NAMES if nread.loc[n] <= 3]

FINDINGS = [
    ("Gross margin", f"{B['accounting_gm']:.1%} accounting, {B['compute_margin_all_workloads']:.1%} with all compute as cost of goods",
     f"Cost of revenue covers serving compute only. Charging every H1 2026 compute dollar, training included, as cost of goods gives {B['compute_margin_all_workloads']:.1%}. "
     f"After channel-partner fees it is about {ch_after:.0%}, and the operating margin is {B['operating_margin']:.1%}.", "margin"),
    ("Compute efficiency", f"Revenue per compute dollar up {q5.rev_per_compute / q1.rev_per_compute:.1f}× in a year",
     f"From ${q1.rev_per_compute:.2f} in Q2 2025 to ${q5.rev_per_compute:.2f} in Q2 2026. About half of the {q5.revenue / q1.revenue:.0f}× revenue growth came with more compute. "
     "The gains arrived in steps after model releases. The marginal return on new compute fell from Q1 to Q2 2026.", "efficiency"),
    ("Contracted compute", f"Demand must grow about {g90.demand_growth_for_both:.0%} a year to carry the contracts",
     f"{money(E.RECON.iloc[0].value_busd)} is contracted, of which {money(firm)} is firm. If demand fills capacity at H1 2026 economics, NPV is {money(g90.npv_at_observed_busd)}. "
     f"If revenue is limited by demand instead, it must grow about {g90.demand_growth_for_npv:.0%} a year from the ${E.OBS['q2_run_rate']:.0f}B Q2 2026 run-rate for NPV ≥ 0. "
     f"It must grow about {g90.demand_growth_for_covenant:.0%} a year to keep cash above the $5B covenant.", "dcf"),
    ("Customers", f"{v('rev_100k_share_h1_26'):.0f}% of revenue from $100K+ customers; top five down to {E.TOP5_Q3:.0%}",
     f"About {v('cust_10m_sep26'):.0f} customers spend $10M+ a year. The top five fell from {1 - v('outside_top5_q1_26') / 100:.0%} of revenue in Q1 2026 to {E.TOP5_Q3:.0%} in Q3. "
     f"Losing the top five's revenue from 2028 raises the demand growth needed to about {g90L.demand_growth_for_both:.0%} a year.", "customers"),
    ("What the filing emphasizes", f"Risk factors lean on {listj(over[:3])}",
     f"The text says the most about externally driven risks: {listj(over)}. It says least, relative to its own facts, about {listj(under)}. "
     f"Jev made {JEV_TOTAL['judgments']:,} judgments to measure this, for ${JEV_TOTAL['cost']:.2f}.", "emphasis"),
]

TK = {
    "jev": (f"Jev turned questions that need reading into data: {JEV_TOTAL['judgments']:,} typed judgments across every passage of the filing, for ${JEV_TOTAL['cost']:.2f}. "
            f"Themes were stable on all {int((risks.theme == risks.theme_pass2).sum())} risk factors across two passes, and {manual_ok} of {len(manual)} author-read checks agreed. "
            "The value is coverage and traceability: no sampling, a probability on every call, and every count on this page links back to the passages behind it."),
    "margin": (f"Accounting gross margin ({B['accounting_gm']:.1%}) is a serving margin, not a measure of what it costs to produce the product. Counting all compute as cost of goods "
               f"gives {B['compute_margin_all_workloads']:.1%}. After channel fees the figure is about {ch_after:.0%}. The truth for current-period economics lies between, depending on how much "
               f"of the {money(B['rd_compute_lo'] / 1000, 1)}–{money(B['rd_compute_hi'] / 1000, 1)} of non-serving compute you treat as the cost of today's models. FY2025 shows how fast this moved: "
               f"its accounting gross margin was {E.BRIDGES['FY2025']['accounting_gm']:.1%} and its operating margin {E.BRIDGES['FY2025']['operating_margin']:.1%}, including the ${E.BRIDGES['FY2025']['settlement'] / 1000:.1f}B settlement."),
    "efficiency": (f"Efficiency improved sharply: revenue per compute dollar rose {q5.rev_per_compute / q1.rev_per_compute:.2f}× year on year. But it has not compounded smoothly. "
                   f"The quarterly gain went from {eff.efficiency_qoq.iloc[2]:.0%} to {eff.efficiency_qoq.iloc[3]:.0%}, then jumped {eff.efficiency_qoq.iloc[4]:.0%} after Opus 4.5. "
                   f"The incremental return fell from {eff.incremental_ratio.iloc[4]:.2f} to {eff.incremental_ratio.iloc[5]:.2f} revenue dollars per added compute dollar. "
                   "Read the next releases as the test of whether the step pattern continues."),
    "dcf": (f"Capacity is not the constraint; demand is. If demand fills the contracted capacity at H1 2026 revenue per serving dollar, the contracts are worth {money(g90.npv_at_observed_busd)} at the split discount rates. "
            f"If revenue grows only as fast as demand, it must compound at about {g90.demand_growth_for_npv:.0%} a year from today's run-rate just to earn the discount rate. "
            f"It must compound at about {g90.demand_growth_for_covenant:.0%} to stay above the liquidity covenant. That is well below the last year's growth but far above anything sustained by a company this size. "
            "The utilization needed depends on an assumed H1 2026 level and is shown relative to it."),
    "customers": (f"The revenue base broadened through 2026. The top five's share fell from {1 - v('outside_top5_q1_26') / 100:.0%} to {E.TOP5_Q3:.0%} while each top-five customer still set a record. "
                  f"Spending is concentrated: {v('rev_100k_share_h1_26'):.0f}% of H1 2026 revenue came from $100K+ customers. The filing gives counts by spend band but not revenue by band, "
                  "so it does not show how much of revenue the largest 250 hold, or whether they stay. The filing names no customer. A loss of the largest accounts is best treated as a stress, which section 3 runs."),
    "emphasis": (f"The filing spends most of its risk-factor words on {listj(over)}, more than the rest of the document documents. "
                 f"It spends the least, relative to the facts it carries, on {listj(under)}. That is the opposite of where Part I finds the economic exposure. "
                 f"Six themes ({listj(dep)}) change verdict when the share-class and accounting sections are excluded, so only the agreements are called findings."),
    "evidence": (f"Most of the filing's facts sit in the {top_sec.index[0].title()} ({top_sec.iloc[0] / top_sec.sum():.0%} of counted passages) and {top_sec.index[1]} ({top_sec.iloc[1] / top_sec.sum():.0%}). "
                 "Capital access, governance and stock themes draw heavily on the financial statements and capital-stock sections, which is why the index is reported with and without them."),
    "factors": (f"Two thirds of the risk-factor words ({mat_share:.0%}) sit in factors that describe something that has already happened: the settlement, compute shortfalls, conflicts, export restrictions. "
                f"The average factor scores {risks.specificity.mean():.2f} on a 0–3 specificity scale. The most specific factors are about government sales, data collection, safety commitments and compute commitments."),
    "genre": (f"About {peer_share:.0%} of risk-factor words sit in factors with a near-twin in CoreWeave's S-1 from March 2025. The least shared themes, {listj([s.replace('_', ' ') for s in themes.sort_values('peer_shared_share').index[:3]])}, "
              "are where Anthropic's disclosure is its own."),
    "agreements": (f"Jev's reading of each agreement matches the ledger's treatment in {int(XC.agrees.sum())} of {len(XC)} cases, and its amount matches the regex in {int(XC.amount_agrees.sum())} of {len(XC)}. "
                   "Microsoft and Amazon read as fixed regardless of usage, SpaceXAI as cancelable on notice, and Nscale and Lambda as dependent on the vendor's own financing."),
    "roles": (f"Amazon holds {rp_amz} and Google {rp_goog} of the seven roles at p ≥ 0.8: each is an investor, a financing source, a supplier, a customer, a distribution channel and a competitor. "
              f"The filing mentions {listj(sparse)} in only a few passages, so their roles rest on little text."),
    "financing": (f"Only the revolver settles purely in cash. {int((fin.converts_to_equity >= 0.5).sum())} of {len(fin)} instruments can end in shares, and {int((fin.compute_linked >= 0.5).sum())} are tied to compute. "
                  "The supplier-financing facilities from Google, Amazon and Broadcom settle in cash or shares, depending on elections and ownership caps."),
}

# =================================================================== HTML pieces
def primer(q, why, read):
    return (f'<div class="primer"><div class="primer-row"><span class="plabel">The question</span><p>{q}</p></div>'
            f'<div class="primer-row"><span class="plabel">Why it matters</span><p>{why}</p></div>'
            f'<div class="primer-row"><span class="plabel">How to read it</span><p>{read}</p></div></div>')


def takeaway(text, live_id=None):
    return f'<aside class="takeaway"><span class="tlabel">Key takeaway</span><p{f" id={chr(34)}{live_id}{chr(34)}" if live_id else ""}>{text}</p></aside>'


def sec_head(num, title, sid, kicker):
    return f'<header class="sec-head"><span class="sec-num">{num}</span><div><h2 id="h-{sid}">{title}</h2><p class="kicker">{kicker}</p></div></header>'


SETTLE = {"cash": "cash", "shares": "shares", "cash_or_shares": "cash or shares", "services": "rent / fees", "not_stated": "not stated"}
fin_rows = "".join(f'<tr data-src="block:{esc(x.block)}"><td>{esc(x.instrument)}</td><td class="num">{money(x.amount_busd, 1)}</td><td>{x.status.replace("_", " ")}</td><td>{SETTLE.get(x.settlement, x.settlement)}</td>'
                   f'<td>{x.security.replace("_", " ")}</td><td>{x.counterparty}</td><td class="num">{x.compute_linked:.2f}</td><td class="num">{x.converts_to_equity:.2f}</td></tr>' for x in fin.itertuples())
FIN_TABLE = f'<div class="tablewrap"><table class="t"><thead><tr><th>Instrument</th><th class="num">Size</th><th>Status</th><th>Settlement</th><th>Security</th><th>Counterparty</th><th class="num">Compute-linked p</th><th class="num">Can end in shares p</th></tr></thead><tbody>{fin_rows}</tbody></table></div>'
xc_rows = "".join(f'<tr data-src="agreement:{x.vendor}"><td>{x.vendor}</td><td>{esc(x.ledger)}</td><td><span class="tag jev">{x.basis}</span></td><td><span class="tag jev">{x.cancel}</span></td>'
                  f'<td class="num">{x.true_up:.2f}</td><td class="num">{x.dep:.2f}</td><td>{"<span class=ok>agrees</span>" if x.agrees else "<span class=no>differs</span>"}</td></tr>' for x in XC.itertuples())
XC_TABLE = f'<div class="tablewrap"><table class="t"><thead><tr><th>Agreement</th><th>Ledger treatment (section 3)</th><th>Jev: payment basis</th><th>Jev: cancelability</th><th class="num">Jev: true-up p</th><th class="num">Jev: vendor-dependency p</th><th>Check</th></tr></thead><tbody>{xc_rows}</tbody></table></div>'
stage_rows = "".join(f'<tr><td>{esc(STAGE_TEXT[s["stage"]][0])}</td><td>{esc(STAGE_TEXT[s["stage"]][1])}</td><td class="num">{s["requests"]:,}</td><td class="num">{s["judgments"]:,}</td><td class="num">{s["median_ms"]:.0f}</td><td class="num">${s["cost"]:.4f}</td></tr>' for s in STAGES if s["stage"] in STAGE_TEXT)
stage_rows += f'<tr><td>Counterparty role map, deeper pass (dashboard)</td><td>Seven yes/no role questions over up to 60 passages per counterparty, aliases included</td><td class="num">{ROLE_RUN["requests"]}</td><td class="num">{ROLE_RUN["judgments"]:,}</td><td class="num">–</td><td class="num">&lt; $0.01</td></tr>'
stage_rows += f'<tr class="total"><td>Total (s1_jev_reading.py)</td><td></td><td class="num">{JEV_TOTAL["requests"]:,}</td><td class="num">{JEV_TOTAL["judgments"]:,}</td><td class="num">{JEV_TOTAL["median_ms"]:.0f}</td><td class="num">${JEV_TOTAL["cost"]:.4f}</td></tr>'
STAGE_TABLE = f'<div class="tablewrap"><table class="t"><thead><tr><th>Step</th><th>What Jev answered</th><th class="num">Requests</th><th class="num">Judgments</th><th class="num">Median ms</th><th class="num">Cost</th></tr></thead><tbody>{stage_rows}</tbody></table></div>'
H_ = E.HURDLE
peer_rows = "".join(f'<tr><td>{x.name}</td><td>{esc(x.company)}</td><td>{x.group}</td><td class="num">{x.beta_levered:.2f}</td><td class="num">{x.debt_to_equity:.2f}</td><td class="num">{x.beta_unlevered:.2f}</td></tr>' for x in H_["peers"].itertuples())
RATES_HTML = (f'<div class="grid2"><div class="tablewrap"><table class="t"><thead><tr><th>Input</th><th class="num">Value</th><th>Source</th></tr></thead><tbody>'
              f'<tr><td>10-year US Treasury yield, {H_["as_of"]}</td><td class="num">{H_["rf"]:.2%}</td><td>US Treasury par curve via FMP</td></tr>'
              f'<tr><td>US equity risk premium</td><td class="num">{H_["erp"]:.2%}</td><td>FMP country table (undated in source)</td></tr>'
              f'<tr><td>Median unlevered beta, ten listed peers</td><td class="num">{H_["beta_u"]:.2f}</td><td>Platforms {H_["beta_u_by_group"]["AI platforms"]:.2f}; AI software {H_["beta_u_by_group"]["High-growth AI software"]:.2f}</td></tr>'
              f'<tr class="total"><td>Revenue-side rate = Treasury + β × ERP</td><td class="num">{H_["r_rev"]:.2%}</td><td><span class="tag assume">derived</span></td></tr>'
              f'<tr data-src="fact:lease_rate_operating"><td>Operating-lease discount rate, June 30, 2026</td><td class="num">{v("lease_rate_operating")}%</td><td><span class="tag fact">filed</span> Note 7</td></tr>'
              f'<tr data-src="fact:lease_rate_finance"><td>Finance-lease discount rate, June 30, 2026</td><td class="num">{v("lease_rate_finance")}%</td><td><span class="tag fact">filed</span> Note 7</td></tr>'
              f'<tr class="total"><td>Payment-side rate, weighted by lease liabilities</td><td class="num">{H_["r_pay"]:.2%}</td><td><span class="tag assume">derived</span></td></tr></tbody></table></div>'
              f'<div class="tablewrap"><table class="t"><thead><tr><th>Peer</th><th>Company</th><th>Group</th><th class="num">Levered β</th><th class="num">Debt / equity</th><th class="num">Unlevered β</th></tr></thead><tbody>{peer_rows}</tbody></table>'
              f'<p class="note">Five-year monthly betas from FMP, unlevered with Hamada at 21% tax. Balance sheets are each company&#39;s latest annual or quarterly filing. CoreWeave&#39;s beta reflects a short, volatile trading history; without it the median is {H_["peers"][H_["peers"].name != "CRWV"].beta_unlevered.median():.2f}.</p></div></div>')
facts_rows = "".join(f'<tr data-src="fact:{esc(k)}"><td>{esc(f.label or k)}</td><td class="num">{esc(str(f.value))}</td><td>{esc(f.unit)}</td><td>{esc(f.section)} p. {esc(str(f.page))}</td></tr>' for k, f in E.FACTS.items())
assump_rows = "".join(f'<tr><td>{esc(a["label"])}</td><td class="num">{a["value"]}</td><td>{esc(a["why"])}</td></tr>' for a in E.ASSUMPTIONS.values())
LIMITS = [
    "Payment dollars stand in for capacity. The filing gives no physical units (chips, megawatts), so a dollar of compute payment is treated as a dollar of capacity. The model cannot tell new capacity from prepayment or higher prices.",
    "Utilization is identified only relative to H1 2026. The filing shows revenue per serving-compute dollar, not how full the capacity was. Absolute utilization figures assume H1 2026 ran at the level set in the assumptions; the relative figure does not depend on it.",
    "The ledger's categories come from different notes and dates, which does not rule out overlap. Amendments after June 30 may restate amounts already in the June 30 figure. The firm subtotal removes the cancelable and vendor-conditional agreements that can be identified; other amounts 'subject to contractual conditions' cannot be separated.",
    "The payment calendar is shaped by assumptions where the filing is silent: the filing leaves its own aggregate and near-term commitment figures blank. Windows come from the filing where stated; ramp-in and residual spreads are assumptions.",
    "Cash is modeled annually, so a covenant breach inside a year can be missed. Working capital, capital expenditure beyond the leases, interest income, stock compensation (a real cost to shareholders through dilution) and any value after the contracts end are excluded.",
    "Demand growth is a single constant rate from the Q2 2026 run-rate. Revenue is the lower of demand and capacity, so growth beyond capacity adds nothing.",
    "Discount rates are modeled, not externally validated. Peer selection, the treatment of leases as debt-like, and the cash-flow definitions involve judgment. The equity risk premium has no as-of date in its source.",
    "Jev's probabilities describe its answer distribution, not measured accuracy. Thresholds were chosen, not tuned against labels; the author-read checks and the regex agreements are the validation shown.",
]

# =================================================================== table of contents
TOC = [
    ("Overview", None, [("summary", "Key findings"), ("reading", "How to read this report")]),
    ("Part I · The economics", None, [
        ("margin", "1  Gross margin", [("margin-bridge", "Bridge to operating income"), ("margin-charge", "Charging training compute")]),
        ("efficiency", "2  Compute efficiency", [("eff-trend", "Revenue per compute dollar"), ("eff-decomp", "Where growth came from")]),
        ("contracts", "3  Contracted compute", [("ledger", "3.1 Reconciled ledger"), ("calendar", "3.2 Payment calendar"), ("rates", "3.3 Discount rates"), ("dcf", "3.4 Reverse DCF"), ("stress", "3.5 Stress tests")]),
        ("customers", "4  Customer concentration", []),
    ]),
    ("Part II · What the filing emphasizes", None, [
        ("jev", "5  How Jev read the filing", []),
        ("emphasis", "6  Words against facts", []),
        ("evidence", "7  Where the evidence sits", []),
        ("factors", "8  The 88 risk factors", []),
        ("genre", "9  Industry boilerplate", []),
        ("agreements", "10  Reading the agreements", []),
        ("roles", "11  Counterparty roles", []),
        ("financing", "12  Financing instruments", []),
    ]),
    ("Appendix", None, [("limits", "A  Method and limitations"), ("assumptions", "B  Assumptions"), ("figures", "C  Every extracted figure")]),
]


def toc_html():
    out = []
    for part, _, items in TOC:
        out.append(f'<li class="toc-part"><span>{part}</span><ol>')
        for it in items:
            sid, label = it[0], it[1]
            subs = it[2] if len(it) > 2 else []
            out.append(f'<li><a href="#{sid}" data-target="{sid}">{label}</a>' + (('<ol class="toc-sub">' + "".join(f'<li><a href="#{s}" data-target="{s}">{l}</a></li>' for s, l in subs) + "</ol>") if subs else "") + "</li>")
        out.append("</ol></li>")
    return '<ol class="toc-list">' + "".join(out) + "</ol>"


findings_html = "".join(f'<a class="finding" href="#{anchor}"><span class="f-k">{esc(k)}</span><span class="f-h">{esc(h)}</span><span class="f-b">{esc(b)}</span></a>' for k, h, b, anchor in FINDINGS)

# =================================================================== page
CSS = (WEB / "s1_dashboard.css").read_text()
JS = (WEB / "s1_dashboard.js").read_text()
MODEL = (WEB / "s1_model.js").read_text()
dump = lambda o: json.dumps(o, default=lambda x: (None if (isinstance(x, float) and math.isnan(x)) else (x.item() if hasattr(x, "item") else str(x)))).replace("</", "<\\/").replace("NaN", "null")
PLOTLY_CDN = "https://cdnjs.cloudflare.com/ajax/libs/plotly.js/4.1.1/plotly.min.js"

BODY = f"""<title>Anthropic S-1 Economics</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<script src="{PLOTLY_CDN}"></script>
<div class="page">
<header class="masthead">
  <p class="eyebrow">Independent analysis · Anthropic, PBC · Form S-1 filed {E.F.filed}</p>
  <h1>Anthropic S-1 Economics</h1>
  <p class="dek">What the registration statement shows about margins, compute efficiency, the economics of more than $800 billion of contracted compute, and customer concentration, read figure by figure from the filing.</p>
  <p class="meta">Built from the public S-1 on SEC EDGAR (CIK 2130357) · {len(E.FACTS)} figures extracted with their quotes · {JEV_TOTAL['judgments']:,} reading judgments by TypeSafe&#39;s Jev · market inputs as of {H_['as_of']} · not affiliated with or endorsed by Anthropic; not investment advice.</p>
</header>
<div class="layout">
<nav class="toc" aria-label="Contents"><details id="toc-d" open><summary>Contents</summary>{toc_html()}</details></nav>
<main>

<section id="summary" class="sec">
  <h2 class="plain">Key findings</h2>
  <div class="findings">{findings_html}</div>
</section>

<section id="reading" class="sec">
  <h2 class="plain">How to read this report</h2>
  <div class="reading">
    <p>Every number on this page is one of four kinds, and each is tagged where it appears.</p>
    <ul class="kinds">
      <li><span class="tag fact">filed</span> A figure stated in the S-1, extracted by pattern-matching with the sentence that states it and its page.</li>
      <li><span class="tag derived">derived</span> Arithmetic on filed figures: ratios, sums, bounds.</li>
      <li><span class="tag assume">assumption</span> A modeling choice where the filing is silent. Each is listed with its reason in Appendix B and most can be changed in section 3.</li>
      <li><span class="tag jev">Jev</span> A judgment that needs reading: which theme a passage supports, how an agreement can be cancelled, which role a counterparty plays. Jev returns these as typed answers with probabilities (section 5).</li>
    </ul>
    <p><b>Click any chart element or table row to open its source</b> in a side panel: the quoted sentence, the clause, or every passage that was counted. Part I answers four economic questions; Part II shows how the filing distributes its emphasis, and how Jev was used to measure it.</p>
  </div>
</section>

<div class="part-band"><span>Part I</span> The economics</div>

<section id="margin" class="sec">
  {sec_head(1, "Gross margin", "margin", "What does it cost to produce what Anthropic sells?")}
  {primer("How much of each revenue dollar is left after the cost of producing it, when that cost includes the compute used to train the models being sold, not only the compute used to serve them?",
          "Software companies are valued on gross margin. Anthropic's accounting gross margin counts only serving compute, while most of its compute goes to training, research and internal use, which sit in R&D. Where you draw the line decides whether this looks like a software business or an infrastructure business.",
          "The waterfall walks H1 2026 revenue down to operating income using the filing's expenses by function (Note 8). Bars are tagged as filed, a floor, or a bucket the filing does not split. The chart to the right charges a growing share of non-serving compute against revenue; the shaded band is the range the filing allows.")}
  <h3 id="margin-bridge" class="sub">Bridge to operating income</h3>
  <div class="chips" id="period-chips" role="group" aria-label="Period"></div>
  <div class="grid2">
    <figure class="card"><div id="fig-bridge" class="chart" style="height:470px"></div></figure>
    <figure class="card" id="margin-charge"><div id="fig-alpha" class="chart" style="height:380px"></div>
      <div class="ctl"><label for="alpha">Share of non-serving compute charged as cost of goods: <b id="alpha-v"></b></label><input id="alpha" type="range" min="0" max="100" value="50"></div>
      <div class="chips" id="alpha-chips"></div>
      <label class="check"><input type="checkbox" id="incl-channel" checked> Include channel-partner fees (H1 2026: a floor of ${v("channel_increase_h1_2026")}B, the stated increase)</label></figure>
  </div>
  <div id="margin-table" class="tablewrap"></div>
  {takeaway(TK["margin"])}
</section>

<section id="efficiency" class="sec">
  {sec_head(2, "Compute efficiency", "efficiency", "How much of the growth was bought with compute, and is efficiency compounding?")}
  {primer("Is revenue growing faster than compute spending, and is that gap widening quarter after quarter?",
          "If each new compute dollar earns more revenue than the last, the contracts in section 3 get easier to carry. If the improvement came in one-off steps, the contracts depend on the next step arriving.",
          "Bars are quarterly revenue and compute expense; the line is revenue per compute dollar, switchable between same-quarter, rolling, lagged (compute is contracted 12–18 months ahead and expensed as it arrives) and incremental views. Triangles mark model releases. The right chart splits each quarter's revenue growth into growth in compute and growth in revenue per compute dollar. That split is arithmetic, not cause and effect.")}
  <h3 id="eff-trend" class="sub">Revenue per compute dollar</h3>
  <div class="chips" id="ratio-chips"></div>
  <div class="grid2">
    <figure class="card"><div id="fig-eff" class="chart" style="height:460px"></div></figure>
    <figure class="card" id="eff-decomp"><div class="chips" id="lag-chips"></div><div id="fig-decomp" class="chart" style="height:420px"></div></figure>
  </div>
  <div id="eff-table"></div>
  {takeaway(TK["efficiency"])}
</section>

<section id="contracts" class="sec">
  {sec_head(3, "Contracted compute", "contracts", "What revenue and demand do the compute contracts require?")}
  {primer("Anthropic has signed compute and data-center agreements worth hundreds of billions of dollars, most payable whether or not the capacity is used. How much revenue, and how much demand growth, does it take for those contracts to pay for themselves?",
          "These obligations are the largest numbers in the filing, larger than its cash, its equity raised and its revenue run-rate combined. They are the company's real leverage, even with almost no debt.",
          "Five steps. 3.1 reconciles the commitments into one ledger. 3.2 lays out when they are paid. 3.3 sets the discount rates. 3.4 values the contracts and solves for the demand growth they need, with live controls. 3.5 stresses the result.")}

  <h3 id="ledger" class="sub">3.1 Reconciled ledger</h3>
  <p class="note">Commitments come from different notes and dates: purchase commitments at June 30 (Note 13), leases already running and leases not yet started (Note 7), and agreements signed after June 30 (Note 17). Named agreements are mapped into those categories, and estimates the filing excludes are kept apart. The total includes agreements that can be cancelled or that depend on the vendor; the firm subtotal removes the ones that can be identified. The reconciliation checks on the right show where the categories may overlap.</p>
  <div class="grid2"><div id="ledger-table" class="tablewrap scroll"></div><div id="recon-table" class="tablewrap scroll"></div></div>

  <h3 id="calendar" class="sub">3.2 Payment calendar</h3>
  <div class="controls"><div><span class="clabel">Scope</span><div class="chips" id="scope-chips"></div></div><div><span class="clabel">Payment ramp-in from each agreement&#39;s start <b id="ramp-v"></b></span><div class="chips" id="ramp-chips"></div></div></div>
  <figure class="card"><div id="fig-calendar" class="chart" style="height:400px"></div></figure>

  <h3 id="rates" class="sub">3.3 Discount rates</h3>
  <p class="note">The payments are owed whatever happens, so they are debt-like and discounted at Anthropic&#39;s own borrowing rate, which the filing discloses for its leases. Revenue, net of variable costs and tax, carries the business risk and is discounted at an unlevered cost of capital built from listed peers. One equity rate for both sides would shrink the payments too much and flatter the result.</p>
  {RATES_HTML}

  <h3 id="dcf" class="sub">3.4 Reverse DCF</h3>
  <p class="note">Each year, the non-serving share of compute (training, research, internal use) is set aside and the rest is serving capacity. Revenue is the lower of two things. One is capacity × utilization × revenue per used serving dollar, calibrated to H1 2026 with usage-policy revenue removed. The other is demand, if a demand path is switched on. Non-compute operating costs and tax are subtracted; the result is discounted at the revenue rate and the payments at the payment rate. The model solves for the demand growth, and for the price-efficiency, at which NPV reaches zero.</p>
  <div class="controls" id="model-controls"></div>
  <div class="kpis" id="kpis"></div>
  <div class="grid2">
    <figure class="card"><div id="fig-demand" class="chart" style="height:420px"></div></figure>
    <figure class="card"><div id="fig-revenue" class="chart" style="height:420px"></div></figure>
  </div>

  <h3 id="stress" class="sub">3.5 Stress tests</h3>
  <div class="grid2">
    <figure class="card"><div id="fig-surface" class="chart" style="height:420px"></div></figure>
    <figure class="card"><div id="fig-cash" class="chart" style="height:420px"></div></figure>
  </div>
  <div class="card pad"><h4>Utilization scenarios at the current settings</h4><div id="scen-table" class="tablewrap"></div>
  <p class="note">Utilization is absolute only under the H1 2026 level set above; the relative column does not depend on it. Revenue in this model scales with utilization × price-efficiency, so high utilization at too low a price still fails. The demand columns show the growth each scenario needs.</p></div>
  {takeaway(TK["dcf"], "tk-dcf")}
</section>

<section id="customers" class="sec">
  {sec_head(4, "Customer concentration", "customers", "How concentrated is the revenue that has to carry these commitments?")}
  {primer("How much revenue depends on a small number of large customers, and is that dependence rising or falling?",
          "Section 3 needs revenue to compound for years. Revenue concentrated in a few accounts can move quickly in either direction, and the largest AI customers can build or buy their own models.",
          "Counts of customers by annual spend (log scale), the growth and revenue share of $100K+ customers, and the top five's share of revenue. Click any bar or point for its source. The filing does not report revenue by spend band or name any customer.")}
  <div class="grid2"><figure class="card"><div id="fig-tiers" class="chart" style="height:360px"></div></figure><figure class="card"><div id="fig-cohort" class="chart" style="height:360px"></div></figure></div>
  <div class="grid2"><figure class="card"><div id="fig-top5" class="chart" style="height:320px"></div></figure>
  <div class="card pad"><h4>Revenue quality notes from the filing</h4><ul class="plainlist">
    <li data-src="fact:policy_rev_lo">{v("policy_rev_lo"):.0f}–{v("policy_rev_hi"):.0f}% of revenue in the nine months to Sep 30, 2026 came from customers later found violating usage policy or commercial terms. The company expects this to fall after stepped-up enforcement in August and September 2026. The model removes the midpoint.</li>
    <li data-src="fact:new_models_share">Over {v("new_models_share"):.0f}% of Q3 2026 revenue came from model versions released in the prior six months. Revenue follows the release cycle.</li>
    <li data-src="fact:rev_consumption_H1 2026">{E.FACTS["rev_consumption_H1 2026"].value / E.nat["revenue"]["H1 2026"]:.0%} of H1 2026 revenue was consumption-based, which can fall as fast as it rises.</li>
    <li data-src="fact:no_customer_10pct">No single customer exceeded 10% of revenue in the nine months to Sep 30, 2026.</li>
  </ul></div></div>
  {takeaway(TK["customers"])}
</section>

<div class="part-band"><span>Part II</span> What the filing emphasizes</div>

<section id="jev" class="sec">
  {sec_head(5, "How Jev read the filing", "jev", "Reading 300 pages at the level of individual passages, with a probability on every judgment")}
  <div class="jev-intro">
    <div><p><b>What Jev is.</b> Jev is TypeSafe&#39;s System One model. It does not write text. It answers a question about a piece of text with a typed result: one option from a defined list, a yes/no probability, or a position on a described scale. Each result carries a probability. That makes reading behave like a function call, so code can threshold, rank, aggregate and re-run judgments the way it handles any other data.</p>
    <p><b>Why use it here.</b> Questions such as &quot;does this passage state a concrete fact about compute commitments&quot; or &quot;can this agreement be cancelled, and how&quot; need reading, not pattern-matching. They had to be asked of every passage, not a sample: {JEV_TOTAL['judgments']:,} judgments at a median {JEV_TOTAL['median_ms']:.0f} ms per request, for ${JEV_TOTAL['cost']:.2f} in total. Because every answer has a probability, every count on this page can be re-thresholded, and every judgment can be traced to the passage it was made on.</p>
    <p><b>What it did not do.</b> Jev did not produce any number in Part I. Figures were extracted by pattern-matching with their quotes, and all arithmetic is code. Jev typed the agreements and instruments that section 3 builds on, and the cross-check below shows those readings line up with the ledger.</p></div>
    <ol class="pipeline">
      <li><span>1</span><b>Structure in code</b> Pages, sections, 88 risk factors from the HTML, 1,219 passages</li>
      <li><span>2</span><b>Typed questions to Jev</b> Choice, Score and yes/no questions with plain-language criteria</li>
      <li><span>3</span><b>Policy in code</b> Thresholds, shares, indexes, verdicts that must hold under two evidence bases</li>
      <li><span>4</span><b>Checks</b> A second pass for stability, regex agreement, {manual_ok} of {len(manual)} author-read checks agreed</li>
    </ol>
  </div>
  <h3 class="sub">Where Jev was used</h3>
  {STAGE_TABLE}
  {takeaway(TK["jev"])}
</section>

<section id="emphasis" class="sec">
  {sec_head(6, "Words against facts", "emphasis", "Does the filing spend its risk-factor words where its facts are?")}
  {primer("For each risk theme, is the share of risk-factor words in line with the share of concrete facts the rest of the filing carries about it?",
          "Risk factors are written by counsel and cover everything. Comparing their emphasis with the document&#39;s own evidence shows which risks are asserted at length and which are documented but under-discussed.",
          "Each bubble is a theme. Above the dashed line, the theme gets more words than facts; below it, more facts than words. Colour is the verdict that holds whether or not the share-class and accounting sections count as evidence; grey themes depend on that choice. Click a bubble for its factors.")}
  <figure class="card">{FIG_WORDS}</figure>
  {takeaway(TK["emphasis"])}
</section>

<section id="evidence" class="sec">
  {sec_head(7, "Where the evidence sits", "evidence", "Which sections of the filing carry the facts behind each theme?")}
  {primer("In which sections of the filing does Jev find concrete facts for each risk theme?",
          "It shows where to read for each risk, and why the index in section 6 is reported on two evidence bases.",
          "Rows are themes, columns are sections. Switch between counts, each theme&#39;s distribution across sections, and the mean probability (which needs no threshold). Click a cell to read every passage counted.")}
  <figure class="card">{FIG_EVIDENCE}</figure>
  {takeaway(TK["evidence"])}
</section>

<section id="factors" class="sec">
  {sec_head(8, "The 88 risk factors", "factors", "Every risk factor, sized by length and shaded by how specific it is")}
  {primer("Which risk factors are long, and which say something specific to Anthropic rather than generic language?",
          "Length is not importance, but long and specific factors are where the company chose to disclose detail.",
          "Area is word count; shade is Jev&#39;s specificity score from 0 (generic) to 3 (Anthropic figures, dates and counterparties). Click a theme to zoom, then a factor to read it in full.")}
  <figure class="card">{FIG_FACTORS}</figure>
  {takeaway(TK["factors"])}
</section>

<section id="genre" class="sec">
  {sec_head(9, "Industry boilerplate", "genre", "How much of the risk section any AI-infrastructure issuer would write")}
  {primer("Which risk factors have a near-twin in a comparable filing?",
          "Shared language is genre, not signal. What only Anthropic says is where its disclosure carries information.",
          "Jev matched each Anthropic heading against the ten closest headings in CoreWeave&#39;s March 2025 S-1. Grey is words in factors with a match; blue is words in factors without one.")}
  <figure class="card">{FIG_GENRE}</figure>
  {takeaway(TK["genre"])}
</section>

<section id="agreements" class="sec">
  {sec_head(10, "Reading the agreements", "agreements", "How each compute agreement is paid, and how it can end")}
  {primer("For each compute agreement, is the amount fixed regardless of usage, and can Anthropic get out of it?",
          "This sets which commitments belong in the firm subtotal in section 3.1, and which depend on the vendor.",
          "Bars are each agreement&#39;s stated amount, coloured by Jev&#39;s reading of its payment basis. The table compares Jev&#39;s reading with the treatment the ledger in section 3.1 gives the same agreement. Click a bar or row for the full agreement text.")}
  <figure class="card">{FIG_VENDORS}</figure>
  {XC_TABLE}
  {takeaway(TK["agreements"])}
</section>

<section id="roles" class="sec">
  {sec_head(11, "Counterparty roles", "roles", "Who is investor, supplier, customer and competitor at once")}
  {primer("Which roles does each major counterparty hold toward Anthropic, according to the filing&#39;s own text?",
          "The same companies supply the compute, finance it, buy from Anthropic and compete with it. The filing gives this one risk factor; the text documents it in many places.",
          "Shade is the strongest probability any passage reached for that role; the number is how many passages reached 0.8. Switch to mean probability or counts. Click a cell to read every passage, ranked.")}
  <figure class="card">{FIG_ROLES}</figure>
  {takeaway(TK["roles"])}
</section>

<section id="financing" class="sec">
  {sec_head(12, "Financing instruments", "financing", "How the company is funded, instrument by instrument")}
  {primer("What financing does Anthropic have, how does each instrument settle, and what is it tied to?",
          "The company has almost no debt, but most of its committed financing is conditional, comes from suppliers, and can end in shares.",
          "Each row is typed by Jev from the instrument&#39;s paragraph; sizes are extracted figures. Click a row for the filing text.")}
  {FIN_TABLE}
  {takeaway(TK["financing"])}
</section>

<div class="part-band"><span>Appendix</span></div>
<section id="limits" class="sec"><h2 class="plain">A  Method and limitations</h2><ol class="limits">{"".join(f"<li>{esc(x)}</li>" for x in LIMITS)}</ol></section>
<section id="assumptions" class="sec"><h2 class="plain">B  Assumptions</h2><div class="tablewrap"><table class="t"><thead><tr><th>Assumption</th><th class="num">Base value</th><th>Why</th></tr></thead><tbody>{assump_rows}</tbody></table></div></section>
<section id="figures" class="sec"><h2 class="plain">C  Every extracted figure</h2><p class="note">{len(E.FACTS)} figures, each with the sentence that states it. Click a row to read it.</p><div class="tablewrap scroll tall"><table class="t"><thead><tr><th>Figure</th><th class="num">Value</th><th>Unit</th><th>Where</th></tr></thead><tbody>{facts_rows}</tbody></table></div></section>
<footer class="foot">Source: SEC EDGAR, Anthropic, PBC Form S-1 (CIK 2130357), filed {E.F.filed}; peer headings from CoreWeave, Inc. Form S-1 (March 3, 2025); market inputs via Financial Modeling Prep. Reading judgments by TypeSafe&#39;s Jev. This is an independent analysis of a public filing. It is not affiliated with or endorsed by Anthropic and is not investment advice.</footer>
</main></div></div>
<div id="drawer" role="dialog" aria-label="Source" aria-hidden="true"><div class="d-head"><button class="x" id="d-close" aria-label="Close source panel">×</button><div id="d-title"></div><div id="d-meta"></div></div><div class="d-body" id="d-body"></div></div>
<script>{MODEL}</script>
<script>const DATA = {dump(DATA)};
const SOURCES = {dump(SOURCES)};</script>
<script>{JS}</script>
"""
(BUILD / "anthropic_s1_dashboard_artifact.html").write_text(BODY)
FULL = '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + BODY.replace("<div class=\"page\">", "</head><body>\n<div class=\"page\">", 1) + "\n</body></html>"
(DOCS / "index.html").write_text(FULL)
print(f"wrote docs/index.html ({len(FULL) / 1e6:.1f} MB) and build/anthropic_s1_dashboard_artifact.html; {len(SOURCES)} sources, {len(E.FACTS)} facts")
