"""Margin bridge, compute efficiency, contract ledger and reverse DCF for Anthropic's S-1.

Every filing figure comes from s1_filing (value + quote + page). Every modeling assumption is in ASSUMPTIONS with a
reason, and is editable in the dashboard. Run directly to write the CSVs:
    ../.venv/bin/python s1_economics.py
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

from s1_filing import filing

HERE = Path(__file__).resolve().parent
F = filing()
FACTS = {}


def fact(key, label, pattern, section, unit, **kw):
    f = F.fact(key, pattern, section, unit, label=label, **kw)
    FACTS[key] = f
    return f.value


def row(key, label, section, anchor, row_label, n, cols, unit="$m", end_anchor=None):
    vals, quote, page = F.table_row(section, anchor, row_label, n, end_anchor)
    for c, v in zip(cols, vals):
        k = f"{key}_{c}"
        FACTS[k] = type(next(iter(FACTS.values())))(k, v, unit, quote, section, page, f"{label}, {c}") if FACTS else None
    return dict(zip(cols, vals))


# a first fact so row() can reuse the Fact class
fact("filed", "S-1 filing date", r"(Prospectus dated)", "COVER", "text", as_text=True, required=False)
FACTS.pop("filed", None)
from s1_filing import Fact  # noqa: E402


def row(key, label, section, anchor, row_label, n, cols, unit="$m", end_anchor=None):  # noqa: F811
    vals, quote, page = F.table_row(section, anchor, row_label, n, end_anchor)
    for c, v in zip(cols, vals):
        FACTS[f"{key}_{c}"] = Fact(f"{key}_{c}", v, unit, quote, section, page, f"{label}, {c}")
    return dict(zip(cols, vals))


# ============================================================== 1. income statement inputs
P5 = ["FY2023", "FY2024", "FY2025", "H1 2025", "H1 2026"]
SUMMARY = "Consolidated Statements of Operations Data"
nat = {k: row(f"nat_{k}", lab, "PROSPECTUS SUMMARY", SUMMARY, lab_row, 5, P5) for k, lab, lab_row in [
    ("revenue", "Revenue", "Revenue"), ("compute", "Compute and infrastructure expense", "Compute and infrastructure"), ("personnel", "Personnel expense", "Personnel"),
    ("sm", "Sales, marketing, and partnerships", "Sales, marketing, and partnerships"), ("other", "Other operating and administrative", "Other operating and administrative"),
    ("opex", "Total operating expenses", "Total operating expenses")]}
FUNC = "Supplemental Operating Expense Information"
fun = {k: row(f"fun_{k}", lab, "FINANCIAL STATEMENTS", FUNC, lab, 5, P5) for k, lab in [
    ("cor", "Cost of revenue"), ("rd", "Research and development"), ("sm", "Sales and marketing"), ("bartz", "Bartz settlement"), ("ga", "General and administrative"), ("opex", "Total operating expenses")]}
fun_notes = F.fact("fun_footnotes", r"(Substantially all of cost of revenue consists of compute and infrastructure costs associated with customer-serving workloads)", "FINANCIAL STATEMENTS", "text", as_text=True)
FACTS["fun_footnotes"] = fun_notes
fun_notes.quote = F.fact("q", r"(Substantially all of cost of revenue.*?non-income-based taxes\.)", "FINANCIAL STATEMENTS", "text", as_text=True).value

Q = ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"]
QA, QE = "Quarterly Consolidated Statements of Operations Three Months Ended", "Quarterly Consolidated Statements of Operations, as a Percentage"
qt = {k: row(f"q_{k}", lab, "MD&A", QA, lab, 6, Q, end_anchor=QE) for k, lab in [
    ("revenue", "Revenue"), ("compute", "Compute and infrastructure"), ("personnel", "Personnel"), ("sm", "Sales, marketing, and partnerships"),
    ("other", "Other operating and administrative"), ("opex", "Total operating expenses"), ("opinc", "Operating income (loss)")]}
qadj = {k: row(f"q_{k}", lab, "MD&A", "Quarterly Adjusted Operating Income (Loss) and Adjusted Operating Margin", lab, 6, Q) for k, lab in [
    ("sbc", "Stock-based compensation expense"), ("charity", "Non-cash charitable contributions")]}
qt.update(qadj)

channel_h1_26 = fact("channel_increase_h1_2026", "Increase in fees paid to channel partners, H1 2026 vs H1 2025", r"driven by a \$([\d.]+) billion increase in fees paid to channel partners", "MD&A", "$B",
                     within="Sales, marketing, and partnerships expenses for the six months ended June 30, 2026")
mkt_h1_26 = fact("marketing_increase_h1_2026", "Increase in marketing and advertising, H1 2026 vs H1 2025", r"a \$(\d+) million increase in marketing and advertising", "MD&A", "$m",
                 within="Sales, marketing, and partnerships expenses for the six months ended June 30, 2026")
fact("compute_lead_time", "Compute procured ahead of availability", r"typically procure 12 to 18 months in advance of availability", "MD&A", "text", group=0, as_text=True)
fact("compute_shared_pool", "Compute is a single shared pool", r"We deploy this committed compute as a single, shared resource across all workloads", "MD&A", "text", group=0, as_text=True)
fact("compute_constrained", "Compute-constrained", r"historically operated in a compute-constrained environment in which demand for compute has exceeded the supply available to us", "MD&A", "text", group=0, as_text=True)
fact("rpo", "Remaining performance obligations, June 30, 2026", r"remaining performance obligations amounted to \$([\d.]+) billion", "FINANCIAL STATEMENTS", "$B")
fact("cost_per_task_opus55", "Opus 5.5 cost per task vs Opus 5", r"Opus 5.5 that same month, we reduced customers’ cost per task by approximately (\d+)%", "BUSINESS", "pct")
fact("cost_per_task_fable51", "Fable 5.1 cost of typical workloads vs Fable 5", r"reduced the cost of typical workloads by approximately (\d+)% compared to Fable 5", "BUSINESS", "pct")

# ============================================================== 2. margin bridge
def bridge(period):
    R, cor, rd, sm, ga, bz = nat["revenue"][period], fun["cor"][period], fun["rd"][period], fun["sm"][period], fun["ga"][period], fun["bartz"][period]
    comp = nat["compute"][period]
    ch_lo = channel_h1_26 * 1000 if period == "H1 2026" else 0.0  # the filing states the H1 2026 increase only; it is a floor for the level
    mkt = mkt_h1_26 if period == "H1 2026" else 0.0
    sm_rest = sm - ch_lo
    free_hi = max(sm - ch_lo - mkt, 0.0)  # free-access compute is inside S&M with marketing and personnel; this is its ceiling
    steps = [("Revenue", R, "fact", "nat_revenue"),
             ("Cost of revenue (customer-serving compute, some personnel and overhead)", -cor, "fact", "fun_cor"),
             ("Accounting gross profit", R - cor, "subtotal", None)]
    if ch_lo:
        steps += [("Channel partner fees (floor: the stated H1 increase)", -ch_lo, "floor", "channel_increase_h1_2026"),
                  ("Rest of S&M: free-access compute, marketing, personnel (not split)", -sm_rest, "unallocated", "fun_sm")]
    else:
        steps += [("Sales and marketing incl. channel fees and free-access compute (not split)", -sm, "unallocated", "fun_sm")]
    steps += [("Contribution after distribution and free access", R - cor - sm, "subtotal", None),
              ("R&D: model development, research, internal-use compute, personnel (not split)", -rd, "unallocated", "fun_rd"),
              ("General and administrative", -ga, "fact", "fun_ga")]
    if bz:
        steps += [("Bartz copyright settlement (one-time)", -bz, "fact", "fun_bartz")]
    steps += [("Operating income (loss)", R - cor - sm - rd - ga - bz, "subtotal", None)]
    assert abs((R - cor - sm - rd - ga - bz) - (R - fun["opex"][period])) < 1, f"{period}: bridge does not tie to total operating expenses"
    # compute split by workload, with bounds
    serving_hi, serving_lo = cor, cor * ASSUMPTIONS["cor_compute_share_floor"]["value"]
    rdc_lo, rdc_hi = comp - serving_hi - free_hi, comp - serving_lo
    return {"period": period, "revenue": R, "cor": cor, "rd": rd, "sm": sm, "ga": ga, "compute": comp, "channel_floor": ch_lo, "free_access_ceiling": free_hi,
            "serving_compute_lo": serving_lo, "serving_compute_hi": serving_hi, "rd_compute_lo": rdc_lo, "rd_compute_hi": rdc_hi,
            "accounting_gm": (R - cor) / R, "contribution_margin": (R - cor - sm) / R, "contribution_margin_channel_only": (R - cor - ch_lo) / R if ch_lo else None,
            "compute_margin_all_workloads": (R - comp) / R, "operating_margin": (R - cor - sm - rd - ga - bz) / R, "settlement": bz, "steps": steps}


ASSUMPTIONS = {
    "cor_compute_share_floor": {"value": 0.90, "label": "Compute share of cost of revenue, floor", "why": "The filing says 'substantially all' of cost of revenue is customer-serving compute; 90% is the floor used for the serving-compute range."},
    "u_obs": {"value": 0.90, "label": "Serving utilization in H1 2026", "why": "The filing says the company has operated compute-constrained, demand exceeding supply. Revenue per serving-compute dollar observed in H1 2026 is scaled up by this to get revenue per fully used dollar."},
    "train_end": {"value": 0.50, "label": "Non-serving share of compute by the ramp year", "why": "H1 2026 non-serving share is derived from the filing (about 73%); where it settles as capacity scales is not disclosed."},
    "ramp_year": {"value": 2030, "label": "Year the non-serving share reaches its end value", "why": "Assumption; linear glide from H1 2026."},
    "k_drift": {"value": 0.0, "label": "Annual change in revenue per used serving-compute dollar", "why": "Price cuts per release (Opus 5.5 −40% cost per task, Fable 5.1 −25%) are stated alongside 'preserving our margins'; 0% means efficiency offsets price."},
    "opex_pct": {"value": None, "label": "Non-compute cash operating costs, % of revenue", "why": "H1 2026, natural classification: personnel less stock compensation, sales/marketing/partnerships (incl. channel fees), other opex less non-cash charitable charges, over revenue."},
    "tax": {"value": 0.21, "label": "Cash tax rate on positive operating profit", "why": "US federal statutory rate; NOLs and credits ignored (conservative)."},
    "rate": {"value": 0.12, "label": "Hurdle rate", "why": "Assumption for an equity-funded, high-growth company; edit to taste."},
    "revolver_in_cash": {"value": False, "label": "Count the undrawn revolver as liquidity", "why": "The $15B revolver is undrawn; off by default."},
}
H = bridge("H1 2026")
ASSUMPTIONS["opex_pct"]["value"] = round((nat["personnel"]["H1 2026"] - qt["sbc"]["Q1 2026"] - qt["sbc"]["Q2 2026"] + nat["sm"]["H1 2026"] + nat["other"]["H1 2026"]
                                          - qt["charity"]["Q1 2026"] - qt["charity"]["Q2 2026"]) / nat["revenue"]["H1 2026"], 4)
BRIDGES = {p: bridge(p) for p in ["H1 2026", "FY2025", "H1 2025", "FY2024"]}

# ============================================================== 3. compute efficiency
eff = pd.DataFrame({"quarter": Q, "revenue": [qt["revenue"][q] for q in Q], "compute": [qt["compute"][q] for q in Q],
                    "personnel": [qt["personnel"][q] for q in Q], "sm": [qt["sm"][q] for q in Q], "opinc": [qt["opinc"][q] for q in Q], "sbc": [qt["sbc"][q] for q in Q]})
eff["rev_per_compute"] = eff.revenue / eff.compute
eff["compute_pct_rev"] = eff.compute / eff.revenue
eff["incremental_ratio"] = eff.revenue.diff() / eff.compute.diff()
eff["rolling_2q_ratio"] = eff.revenue.rolling(2).sum() / eff.compute.rolling(2).sum()
eff["lag1_ratio"] = eff.revenue / eff.compute.shift(1)
eff["lag2_ratio"] = eff.revenue / eff.compute.shift(2)
eff["ln_rev_growth"] = np.log(eff.revenue).diff()
eff["ln_compute_growth"] = np.log(eff.compute).diff()
eff["ln_efficiency_growth"] = np.log(eff.rev_per_compute).diff()
eff["efficiency_qoq"] = eff.rev_per_compute.pct_change()
yoy = {}
for lag in (0, 1, 2):
    c_now, c_then = eff.compute.shift(lag).iloc[5], eff.compute.shift(lag).iloc[1]
    if pd.isna(c_now) or pd.isna(c_then):
        continue
    g_rev, g_c = math.log(eff.revenue.iloc[5] / eff.revenue.iloc[1]), math.log(c_now / c_then)
    yoy[lag] = {"lag_quarters": lag, "revenue_growth_x": eff.revenue.iloc[5] / eff.revenue.iloc[1], "compute_growth_x": c_now / c_then,
                "efficiency_growth_x": (eff.revenue.iloc[5] / c_now) / (eff.revenue.iloc[1] / c_then), "share_from_compute": g_c / g_rev, "share_from_efficiency": 1 - g_c / g_rev}
YOY = pd.DataFrame(yoy.values())

RELEASES = []
for key, label, pat, sec, q in [
    ("rel_claude_code", "Claude Code research preview", r"research preview release in (February 2025)", "PROSPECTUS SUMMARY", "Q1 2025"),
    ("rel_opus45", "Opus 4.5", r"we launched Opus 4.5 in (November 2025)", "BUSINESS", "Q4 2025"),
    ("rel_cowork", "Claude Cowork research preview", r"which we made available as a research preview in (January 2026)", "BUSINESS", "Q1 2026"),
    ("rel_mythos_preview", "Claude Mythos Preview (Project Glasswing)", r"first made the class available in (April 2026) as Claude Mythos Preview", "BUSINESS", "Q2 2026"),
    ("rel_fable5", "Fable 5 GA, Mythos 5", r"made Fable 5 generally available and offered Mythos 5 to Project Glasswing participants in (June 2026)", "BUSINESS", "Q2 2026"),
    ("rel_opus55", "Opus 5.5, Fable 5.1, Mythos 5.1", r"in (September 2026), we launched Opus 5.5", "BUSINESS", "Q3 2026"),
]:
    v = fact(key, label, pat, sec, "date", as_text=True)
    RELEASES.append({"key": key, "label": label, "date": v, "quarter": q})

# ============================================================== 4. contract ledger
FS, MDA, RF = "FINANCIAL STATEMENTS", "MD&A", "RISK FACTORS"
fact("cash", "Cash and cash equivalents, June 30, 2026", r"cash and cash equivalents of \$([\d.]+) billion", MDA, "$B")
fact("sti", "Short-term investments, June 30, 2026", r"\$([\d.]+) billion of short-term investments", MDA, "$B")
fact("revolver", "A&R revolving credit facility", r"\$(\d+) billion senior secured revolving credit facility with the full amount", MDA, "$B")
fact("min_liquidity", "Minimum liquidity covenant", r"of at least \$([\d.]+) billion as of the last day of each fiscal quarter", MDA, "$B")
A_jun = fact("A_purchase_jun30", "Fixed or minimum purchase commitments, June 30, 2026", r"expected future fixed or minimum guaranteed commitments under these agreements were approximately \$([\d.]+) billion", FS, "$B")
A_dec = fact("A_purchase_dec31", "Non-cancelable purchase commitments table total, Dec 31, 2025", r"Total non-cancelable contractual commitments \$ ([\d,]+)", FS, "$m") / 1000
C_dec = fact("C_leases_nc_dec31", "Leases not yet commenced, Dec 31, 2025", r"future undiscounted lease obligations of approximately \$([\d.]+) billion and \$[\d.]+ billion", FS, "$B")
C_jun = fact("C_leases_nc_jun30", "Leases not yet commenced, June 30, 2026", r"future undiscounted lease obligations of approximately \$[\d.]+ billion and \$([\d.]+) billion", FS, "$B")
LM = "Maturities of lease liabilities are as follows"
lease_rows = {y: row(f"B_lease_{y}", f"Lease payments {y}", FS, LM, y, 3, ["op_dec25", "op_jun26", "fin_jun26"]) for y in ["2026", "2027", "2028", "2029", "2030", "Thereafter"]}
B_total = sum(v["op_jun26"] + v["fin_jun26"] for v in lease_rows.values()) / 1000
FSU = "Subsequent Events (Unaudited)"
D_post = fact("D_added_after_jun30", "Minimum commitments added after June 30, 2026", r"subsequent to June 30, 2026[^.]*?aggregate future minimum payment obligations of approximately \$([\d.]+) billion", FS, "$B", within=FSU)
E_short = fact("E_short_term_after_jun30", "Short-term commitments added after June 30, 2026", r"short term in nature with minimum non-cancelable payments under such contracts of approximately \$([\d.]+) billion", FS, "$B", within=FSU)
post_dec = fact("added_after_dec31_audited", "Commitments added after Dec 31, 2025 (audited note, dated June 1, 2026)", r"Subsequent to December 31, 2025[^.]*?aggregate future minimum payment obligations of approximately \$([\d.]+) billion", FS, "$B")
bc_all = fact("broadcom_rent_all", "Broadcom master equipment leases, rent excl. interest", r"rent payments over the life of these leases are equal to an aggregate of approximately \$([\d.]+) billion", MDA, "$B")
bc_2026 = fact("broadcom_rent_2026", "2026 Lease Arrangement rent excl. interest", r"five-year equipment lease are equal to an aggregate of approximately \$([\d.]+) billion", RF, "$B")
P = F.agreement_paragraphs()


def para_fact(key, label, vendor, pattern, unit, group=1, as_text=False):
    import re
    from s1_filing import flat
    p = P[vendor]
    m = re.search(pattern, p)
    if not m:
        raise ValueError(f"{key}: not found in {vendor} paragraph")
    raw = m.group(group)
    val = raw if as_text else float(raw.replace(",", ""))
    FACTS[key] = Fact(key, val, unit, F.sentence_around(p, m.start(), m.end()), MDA, F.page_of(p[m.start():m.start() + 80]), label)
    return val


MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}
dec = lambda s: int(s.split()[1]) + MONTHS[s.split()[0]] / 12  # "May 2033" -> 2033.33

msft = para_fact("msft_amount", "Microsoft minimum spend", "Microsoft", r"at least \$([\d.]+) billion", "$B")
msft_w = (para_fact("msft_from", "Microsoft window start", "Microsoft", r"between ([A-Z][a-z]+ \d{4}) and", "date", as_text=True), para_fact("msft_to", "Microsoft window end", "Microsoft", r"between [A-Z][a-z]+ \d{4} and ([A-Z][a-z]+ \d{4})", "date", as_text=True))
goog = para_fact("google_amount", "Google minimum spend", "Google", r"at least approximately \$([\d.]+) billion", "$B")
goog_w = (para_fact("google_from", "Google window start", "Google", r"between ([A-Z][a-z]+ \d{4}) and [A-Z][a-z]+ \d{4}, regardless", "date", as_text=True), para_fact("google_to", "Google window end", "Google", r"between [A-Z][a-z]+ \d{4} and ([A-Z][a-z]+ \d{4}), regardless", "date", as_text=True))
tpu_lo = para_fact("tpu_low", "Additional TPU compute, estimate low", "Google", r"approximately \$([\d.]+) billion to \$[\d.]+ billion", "$B")
tpu_hi = para_fact("tpu_high", "Additional TPU compute, estimate high", "Google", r"approximately \$[\d.]+ billion to \$([\d.]+) billion", "$B")
tpu_w = (para_fact("tpu_from", "TPU delivery from", "Google", r"delivered between (\d{4}) and \d{4}", "year", as_text=True), para_fact("tpu_to", "TPU delivery to", "Google", r"delivered between \d{4} and (\d{4})", "year", as_text=True))
amzn = para_fact("amazon_amount", "Amazon minimum spend", "Amazon", r"at least \$([\d.]+) billion", "$B")
amzn_w = (para_fact("amazon_from", "Amazon window start", "Amazon", r"between ([A-Z][a-z]+ \d{4}) and", "date", as_text=True), para_fact("amazon_to", "Amazon window end", "Amazon", r"between [A-Z][a-z]+ \d{4} and ([A-Z][a-z]+ \d{4})", "date", as_text=True))
spx = para_fact("spacexai_amount", "SpaceXAI, up to", "SpaceXAI", r"up to\s*\$([\d.]+) billion", "$B")
spx_to = para_fact("spacexai_to", "SpaceXAI terms extend into", "SpaceXAI", r"terms extending into\s*(\d{4})", "year", as_text=True)
spx_m = para_fact("spacexai_monthly", "SpaceXAI per month once delivered", "SpaceXAI", r"approximately\s*\$([\d.]+) billion\s*in the aggregate per month", "$B")
spx_full = para_fact("spacexai_full_delivery", "SpaceXAI full delivery expected", "SpaceXAI", r"which we expect in ([A-Z][a-z]+ \d{4})", "date", as_text=True)
spx_nc = para_fact("spacexai_noncancel_end", "SpaceXAI non-cancelable periods end", "SpaceXAI", r"non-\s*cancelable periods ending in [A-Z][a-z]+ \d{4} and ([A-Z][a-z]+ \d{4})", "date", as_text=True)
spx_notice = para_fact("spacexai_notice_days", "SpaceXAI cancellation notice", "SpaceXAI", r"upon (\d+) days’ advance written notice", "days")
amd = para_fact("amd_amount", "AMD initial tranche, expected expenditure exceeds", "AMD", r"to exceed\s*\$([\d.]+)\s*billion", "$B")
nscale = para_fact("nscale_amount", "Nscale, up to", "Nscale", r"up to approximately \$([\d.]+) billion", "$B")
nscale_to = para_fact("nscale_to", "Nscale terms extend into", "Nscale", r"terms extending into (\d{4})", "year", as_text=True)
lam = para_fact("lambda_amount", "Lambda aggregate", "Lambda", r"aggregate of approximately \$([\d.]+) billion", "$B")
lam_aug = para_fact("lambda_aug_amount", "Lambda August 2026 agreement", "Lambda", r"approximately \$([\d.]+) billion of the aggregate commitment", "$B")
lam_to = para_fact("lambda_to", "Lambda terms extend into", "Lambda", r"terms extending into (\d{4})", "year", as_text=True)

T0 = 2026.5  # June 30, 2026
YEARS = list(range(2026, 2046))


RAMP = [0.0]  # years over which payments ramp linearly from zero at the window start (capacity is delivered in tranches)


def alloc(amount, a, b, ramp=None):
    """Spread `amount` over [a, b] (decimal years) into calendar-year buckets from June 30, 2026. Payments ramp
    linearly over the first `ramp` years of the original window, then run flat; the amount is conserved."""
    ramp = RAMP[0] if ramp is None else ramp
    out = np.zeros(len(YEARS))
    if amount <= 0 or b <= max(a, T0):
        return out
    m = np.arange(max(a, T0), b, 1 / 120) + 1 / 240  # ~3-day steps
    w = np.minimum((m - a) / ramp, 1.0) if ramp > 0 else np.ones_like(m)
    w = w / w.sum() * amount
    idx = np.clip(np.floor(m).astype(int) - YEARS[0], 0, len(YEARS) - 1)
    np.add.at(out, idx, w)
    return out


def remaining(amount, a, b):
    return amount * max(0.0, (b - max(a, T0))) / (b - a)


goog_rem = remaining(goog, dec(goog_w[0]), dec(goog_w[1]) + 1 / 12)
amzn_rem = remaining(amzn, dec(amzn_w[0]), dec(amzn_w[1]) + 1 / 12)
lam_early = lam - lam_aug
A_named = msft + goog_rem + amzn_rem + lam_early
A_resid = max(A_jun - (msft + goog_rem + amzn_rem), 0.0)
spx_from = 2026.75
spx_end = int(spx_to) + 11 / 12
bc_comm = lease_rows["2026"]["fin_jun26"] + lease_rows["2027"]["fin_jun26"] + lease_rows["2028"]["fin_jun26"] + lease_rows["2029"]["fin_jun26"] + lease_rows["2030"]["fin_jun26"] + lease_rows["Thereafter"]["fin_jun26"]
bc_nc = bc_all - bc_comm / 1000
D_named = spx + nscale + lam_aug
D_resid = D_post - D_named  # recomputed below once the SpaceXAI schedule is known

# B schedule exactly from the maturity table; "Thereafter" spread 2031-2040 (assumption)
B_sched = np.zeros(len(YEARS))
for y in ["2026", "2027", "2028", "2029", "2030"]:
    B_sched[YEARS.index(int(y))] = (lease_rows[y]["op_jun26"] + lease_rows[y]["fin_jun26"]) / 1000
B_sched += alloc((lease_rows["Thereafter"]["op_jun26"] + lease_rows["Thereafter"]["fin_jun26"]) / 1000, 2031, 2041)

def build_ledger():
  return [
    # id, category, label, amount ($B), status, schedule (vector), window text, basis of the window, fact keys, include-by-default, toggle group
    ("A_msft", "A. Purchase commitments at 6/30/26 (Note 13)", "Microsoft", msft, "binding: fixed regardless of usage", alloc(msft, dec(msft_w[0]), dec(msft_w[1]) + 1 / 12), f"{msft_w[0]} – {msft_w[1]}", "filing window, straight-line", ["msft_amount", "msft_from", "msft_to"], True, None),
    ("A_google", "A. Purchase commitments at 6/30/26 (Note 13)", "Google (remaining after 6/30)", goog_rem, "binding: fixed, true-up", alloc(goog_rem, T0, dec(goog_w[1]) + 1 / 12), f"{goog_w[0]} – {goog_w[1]}", "filing window, straight-line; remaining share by elapsed time", ["google_amount", "google_from", "google_to"], True, None),
    ("A_amazon", "A. Purchase commitments at 6/30/26 (Note 13)", "Amazon (remaining after 6/30)", amzn_rem, "binding: fixed, true-up", alloc(amzn_rem, T0, dec(amzn_w[1]) + 1 / 12), f"{amzn_w[0]} – {amzn_w[1]}", "filing window, straight-line; remaining share by elapsed time", ["amazon_amount", "amazon_from", "amazon_to"], True, None),
    ("A_resid", "A. Purchase commitments at 6/30/26 (Note 13)", "Other purchase commitments (residual)", A_resid, "binding", alloc(A_resid, T0, 2028.5), "assumed 6/30/26 – 6/30/28", "assumption", ["A_purchase_jun30"], True, None),
    ("B_leases", "B. Recognized leases, undiscounted (Note 7)", "Operating and finance leases already commenced", B_total, "binding", B_sched, "maturity table; 'thereafter' spread 2031–2040", "filing table; tail assumed", ["B_lease_2026_op_jun26"], True, None),
    ("C_broadcom", "C. Leases not yet commenced at 6/30/26 (Note 7)", "Broadcom master equipment leases (not yet commenced part)", bc_nc, "binding once ready for service", alloc(bc_nc, 2027, 2032), "five-year leases; assumed 2027 – 2031", "lease term from filing; start year assumed", ["broadcom_rent_all", "broadcom_rent_2026"], True, None),
    ("C_resid", "C. Leases not yet commenced at 6/30/26 (Note 7)", "Other compute and data center leases (residual)", C_jun - bc_nc, "binding, some subject to conditions", alloc(C_jun - bc_nc, 2027, 2042), "assumed 2027 – 2041", "assumption (terms up to 20 years)", ["C_leases_nc_jun30"], True, None),
    ("D_spacexai_nc", "D. Added after 6/30/26 (Note 17)", "SpaceXAI, through the non-cancelable period plus notice", None, "binding through the notice period", None, f"from Q4 2026 to {spx_nc} + {int(spx_notice)} days", "filing terms; payment ramp assumed straight-line", ["spacexai_amount", "spacexai_noncancel_end", "spacexai_notice_days", "spacexai_monthly"], True, None),
    ("D_spacexai_rest", "D. Added after 6/30/26 (Note 17)", "SpaceXAI, cancelable remainder", None, "cancelable on notice", None, f"to {spx_to}", "filing terms", ["spacexai_amount", "spacexai_to"], True, "spacexai_cancel"),
    ("D_nscale", "D. Added after 6/30/26 (Note 17)", "Nscale (fees as delivered; vendor must secure financing)", nscale, "conditional on vendor financing and delivery", alloc(nscale, 2027, int(nscale_to) + 1), f"2027 – {nscale_to}", "end from filing; start assumed", ["nscale_amount", "nscale_to"], True, "vendor_conditional"),
    ("D_lambda_aug", "D. Added after 6/30/26 (Note 17)", "Lambda August 2026 agreement (terminable if lease not secured)", lam_aug, "conditional on vendor lease", alloc(lam_aug, 2027, int(lam_to) + 1), f"2027 – {lam_to}", "end from filing; start assumed", ["lambda_aug_amount", "lambda_to"], True, "vendor_conditional"),
    ("D_resid", "D. Added after 6/30/26 (Note 17)", "Other additions after 6/30 (residual)", D_resid, "binding, some subject to conditions", alloc(D_resid, 2027, 2037), "assumed 2027 – 2036", "assumption (commencing 2026–2036, terms up to 20 years)", ["D_added_after_jun30"], True, None),
    ("E_short", "E. Short-term commitments after 6/30/26 (Note 17)", "Short-term non-cancelable", E_short, "binding", alloc(E_short, 2026.75, 2027.75), "assumed within 12 months", "assumption", ["E_short_term_after_jun30"], True, None),
    ("F_tpu", "F. Estimates outside every commitment figure", "Additional TPU compute (estimate, midpoint)", (tpu_lo + tpu_hi) / 2, "estimate: no fixed dollar commitment", alloc((tpu_lo + tpu_hi) / 2, int(tpu_w[0]), int(tpu_w[1]) + 1), f"{tpu_w[0]} – {tpu_w[1]}", "filing window, straight-line", ["tpu_low", "tpu_high", "tpu_from", "tpu_to"], False, "estimates"),
    ("F_amd", "F. Estimates outside every commitment figure", "AMD initial tranche (expected to exceed)", amd, "estimate: no fixed dollar commitment", alloc(amd, 2027, 2032), "assumed 2027 – 2031", "assumption", ["amd_amount"], False, "estimates"),
  ]
cut = dec(spx_nc) + 1 / 12 + spx_notice / 365


def spacexai_schedule():
    """Monthly payments: ramp over Oct–Nov 2026 to the stated monthly rate at full delivery (Dec 2026), then that rate
    until the stated total is reached. Returns annual buckets."""
    full_at = dec(spx_full)  # December 2026
    out, paid, m = np.zeros(len(YEARS)), 0.0, spx_from
    while paid < spx - 1e-9 and m < spx_end:  # 'up to' the total, within terms that extend into the stated year
        rate = spx_m * min(max((m + 1 / 12 - spx_from) / (full_at + 1 / 12 - spx_from), 0), 1)
        amt = min(rate, spx - paid)
        out[min(int(m + 1e-9) - YEARS[0], len(YEARS) - 1)] += amt
        paid += amt
        m += 1 / 12
    return out


SPX_SCHEDULED = float(spacexai_schedule().sum())
D_resid = D_post - (SPX_SCHEDULED + nscale + lam_aug)  # the part of SpaceXAI's 'up to' total beyond its term stays in the residual


def finish(L):
    # SpaceXAI: one schedule over its full term, split at the end of the non-cancelable period plus notice
    full = spacexai_schedule()
    yrs = np.array(YEARS, dtype=float)
    share_before = np.clip((cut - np.maximum(yrs, T0)) / (np.minimum(yrs + 1, spx_end) - np.maximum(yrs, T0)), 0, 1)
    nc = full * share_before
    for i, l in enumerate(L):
        if l[0] == "D_spacexai_nc":
            L[i] = l[:3] + (float(nc.sum()), l[4], nc) + l[6:]
        if l[0] == "D_spacexai_rest":
            L[i] = l[:3] + (float((full - nc).sum()), l[4], full - nc) + l[6:]
    return L


RAMPS = [0.0, 1.0, 1.5, 2.0]
LEDGERS = {}
for r in RAMPS:
    RAMP[0] = r
    LEDGERS[r] = finish(build_ledger())
RAMP[0] = 1.0
LEDGER = LEDGERS[1.0]
ASSUMPTIONS["ramp_in"] = {"value": 1.0, "label": "Payment ramp-in, years from each agreement's start", "why": "Capacity arrives in tranches; the filing says expenses are recognized as compute becomes available. Calibrated so the ledger's H2 2026 is closer to the observed Q2 2026 compute run-rate; 0 = straight-line."}
spx_nc_amt = [l for l in LEDGER if l[0] == "D_spacexai_nc"][0][3]
ledger = pd.DataFrame([{"id": l[0], "category": l[1], "item": l[2], "amount_busd": round(l[3], 2), "status": l[4], "window": l[6], "window_basis": l[7],
                        "sources": ", ".join(l[8]), "in_base_case": l[9], "toggle": l[10] or ""} for l in LEDGER])
SCHEDS = {r: pd.DataFrame({l[0]: l[5] for l in L}, index=YEARS).T for r, L in LEDGERS.items()}
SCHED = SCHEDS[1.0]
for r, S_ in SCHEDS.items():
    assert np.allclose(S_.sum(axis=1).values, [l[3] for l in LEDGERS[r]], atol=0.02), f"ramp {r}: schedule does not sum to the ledger amounts"

binding_total = A_jun + B_total + C_jun + D_post + E_short
RECON = pd.DataFrame([
    {"check": "Contracted commitments, A+B+C+D+E (incl. cancelable and conditional)", "value_busd": binding_total, "detail": f"{A_jun} + {B_total:.1f} + {C_jun} + {D_post} + {E_short}. The categories come from different notes and dates; that does not by itself rule out overlap, and amendments after June 30 may restate amounts already in A (see below)."},
    {"check": "Of which firm: excluding the cancelable SpaceXAI tail and the vendor-conditional Nscale and Lambda agreements", "value_busd": None, "detail": ""},
    {"check": "Roll-forward Dec 31, 2025 → June 30, 2026", "value_busd": (A_jun + C_jun) - (A_dec + C_dec + post_dec),
     "detail": f"(A {A_jun} + C {C_jun}) − (A {A_dec:.1f} + C {C_dec} at Dec 31 + {post_dec} added to June 1) = net additions in June less H1 payments; not separately disclosed"},
    {"check": "Named agreements dated before 6/30 vs category A", "value_busd": A_named - A_jun,
     "detail": f"Microsoft {msft} + Google remaining {goog_rem:.1f} + Amazon remaining {amzn_rem:.1f} + Lambda May/June {lam_early:.1f} = {A_named:.1f} vs {A_jun}; a positive gap means some amounts (Google amended May–Aug, Microsoft amended Oct) sit in Note 17 instead"},
    {"check": "Named post-6/30 agreements vs category D", "value_busd": D_post - D_named, "detail": f"SpaceXAI {spx} + Nscale {nscale} + Lambda Aug {lam_aug} = {D_named:.1f} of {D_post}; SpaceXAI is assigned to D because category A has no room for it"},
    {"check": "Broadcom not-yet-commenced leases inside category C", "value_busd": C_jun - bc_nc, "detail": f"{bc_all} rent less {bc_comm/1000:.2f} commenced = {bc_nc:.1f} of C {C_jun}"},
    {"check": "Estimates excluded from the binding total (F)", "value_busd": (tpu_lo + tpu_hi) / 2 + amd, "detail": f"TPU {tpu_lo}–{tpu_hi} midpoint, AMD > {amd}; the filing excludes both from its commitment figures"},
    {"check": "The earlier capital chart's stack", "value_busd": A_jun + D_post + E_short + bc_all + tpu_lo,
     "detail": "A + D + E + all Broadcom rent + TPU low end: double-counts Broadcom (inside C) and adds an estimate; omits the rest of C. Replaced by this ledger"},
])
_amt = {l[0]: l[3] for l in LEDGER}
FIRM_TOTAL = binding_total - _amt["D_spacexai_rest"] - _amt["D_nscale"] - _amt["D_lambda_aug"]
RECON.loc[RECON.check.str.startswith("Of which firm"), ["value_busd", "detail"]] = [FIRM_TOTAL, f"{binding_total:.1f} less SpaceXAI after its notice period ({_amt['D_spacexai_rest']:.1f}), Nscale ({_amt['D_nscale']:.1f}) and Lambda's August agreement ({_amt['D_lambda_aug']:.1f}). Other amounts the filing calls 'subject to certain contractual conditions' cannot be separated and stay in."]


# ============================================================== 4b. discount-rate and customer facts
fact("lease_rate_operating", "Weighted-average discount rate, operating leases, June 30, 2026", r"Weighted-average discount rate - operating leases [\d.]+ % [\d.]+ % ([\d.]+) %", FS, "pct")
fact("lease_rate_finance", "Weighted-average discount rate, finance leases, June 30, 2026", r"Weighted-average discount rate - finance leases \* \* ([\d.]+) %", FS, "pct")
lease_pv = row("lease_pv", "Present value of lease liabilities", FS, LM, "Present value of lease liabilities", 3, ["op_dec25", "op_jun26", "fin_jun26"])
CUST = {}
for key, label, pat, sec in [
    ("cust_100k_dec23", "Customers ≥ $100K TTM, Dec 31, 2023", r"grew from approximately (\d+) as of December 31, 2023, to approximately", "MD&A"),
    ("cust_100k_dec24", "Customers ≥ $100K TTM, Dec 31, 2024", r"to approximately (\d+) as of December 31, 2024, to approximately", "MD&A"),
    ("cust_100k_dec25", "Customers ≥ $100K TTM, Dec 31, 2025", r"to approximately ([\d,]+) as of December 31, 2025, and to more than", "MD&A"),
    ("cust_100k_sep26", "Customers ≥ $100K TTM, Sep 30, 2026", r"and to more than ([\d,]+) as of September 30, 2026", "MD&A"),
    ("cust_100k_mar25", "Customers ≥ $100K TTM, Mar 31, 2025", r"grew from approximately (\d+) as of March 31, 2025", "MD&A"),
    ("cust_100k_jun25", "Customers ≥ $100K TTM, Jun 30, 2025", r"grew from more than (\d+) as of June 30, 2025 to more than", "MD&A"),
    ("cust_100k_sep25", "Customers ≥ $100K TTM, Sep 30, 2025", r"from more than (\d+) as of September 30, 2025", "MD&A"),
    ("cust_100k_jun26", "Customers ≥ $100K TTM, Jun 30, 2026", r"to more than ([\d,]+) as of June 30, 2026", "MD&A"),
    ("cust_1m_sep26", "Customers ≥ $1M TTM, Sep 30, 2026", r"more than ([\d,]+) customers with \$1 million or more of revenue", "MD&A"),
    ("cust_10m_sep26", "Customers ≥ $10M TTM, Sep 30, 2026", r"approximately (\d+) customers with \$10 million or more of revenue", "MD&A"),
    ("cust_small_users", "Customers below $100K TTM (millions), TTM to Sep 30, 2026", r"generated by approximately (\d+) million customers", "MD&A"),
    ("rev_100k_share_fy23", "Revenue share of ≥ $100K customers, FY2023", r"represented (\d+)%, \d+%, \d+%, and", "MD&A"),
    ("rev_100k_share_fy24", "Revenue share of ≥ $100K customers, FY2024", r"represented \d+%, (\d+)%, \d+%, and", "MD&A"),
    ("rev_100k_share_fy25", "Revenue share of ≥ $100K customers, FY2025", r"represented \d+%, \d+%, (\d+)%, and", "MD&A"),
    ("rev_100k_fy25_busd", "Revenue from ≥ $100K customers, FY2025", r"to \$(\d+\.\d) billion to \$ and represented", "MD&A"),
    ("rev_100k_share_h1_25", "Revenue share of ≥ $100K customers, H1 2025", r"represented approximately (\d+)% and \d+% of total revenue for the six months", "MD&A"),
    ("rev_100k_share_h1_26", "Revenue share of ≥ $100K customers, H1 2026", r"represented approximately \d+% and (\d+)% of total revenue for the six months", "MD&A"),
    ("top5_9m26", "Top five customers, share of revenue, 9 months to Sep 30, 2026", r"top five customers represented approximately (\d+)% of our revenue", "RISK FACTORS"),
    ("outside_top5_q3_26", "Revenue outside the top five customers, Q3 2026", r"Approximately (\d+)% of our revenue came from customers outside of our top five customers", "MD&A"),
    ("outside_top5_q1_26", "Revenue outside the top five customers, Q1 2026", r"up from approximately (\d+)% for the three months ended March 31, 2026", "MD&A"),
    ("no_customer_10pct", "No single customer above 10% of revenue", r"No single customer represented more than 10% of our revenue for the nine months ended September 30, 2026", "MD&A"),
    ("policy_rev_lo", "Revenue from usage-policy violators, low estimate, 9M 2026", r"represented approximately (\d+)% to \d+% of our revenue for the nine months", "MD&A"),
    ("policy_rev_hi", "Revenue from usage-policy violators, high estimate, 9M 2026", r"represented approximately \d+% to (\d+)% of our revenue for the nine months", "MD&A"),
    ("new_models_share", "Revenue from model versions released in the prior six months, Q3 2026", r"accounted for over (\d+)% of our revenue for the three months ended September 30, 2026", "MD&A"),
]:
    v = fact(key, label, pat, sec, "count" if key.startswith("cust") else "pct", as_text=(key == "no_customer_10pct"), group=(0 if key == "no_customer_10pct" else 1))
    CUST[key] = v
mix = {k: row(f"rev_{k}", lab, FS, "The following table presents consumption-based and subscription-based rev", lab, 5, P5) for k, lab in [("consumption", "Consumption-based"), ("subscription", "Subscription-based")]}

# ============================================================== 5. reverse DCF
OBS = {"revenue_h1": H["revenue"], "cor_h1": H["cor"], "compute_h1": H["compute"], "k_obs": H["revenue"] / H["cor"], "train_start": 1 - H["cor"] / H["compute"],
       "q2_run_rate": qt["revenue"]["Q2 2026"] * 4 / 1000, "liquidity": FACTS["cash"].value + FACTS["sti"].value, "revolver": FACTS["revolver"].value, "min_liquidity": FACTS["min_liquidity"].value}


def model(p, sched):
    """Annual cash model on the contracted compute. Returns per-year arrays and summary. Mirrored by s1_model.js.
    Split-rate valuation: revenue net of variable costs and tax is discounted at rate_rev; the fixed compute payments at rate_pay."""
    years = np.array(YEARS, dtype=float)
    frac = np.where(years == 2026, 0.5, 1.0)
    mid = np.where(years == 2026, 0.25, years - T0 + 0.5)  # mid-period, years after June 30, 2026
    C = sched.copy()
    t = np.clip((years + np.where(years == 2026, 0.75, 0.5) - T0) / max(p["ramp_year"] + 0.5 - T0, 0.25), 0, 1)
    train = p["train_start"] + (p["train_end"] - p["train_start"]) * t
    S = C * (1 - train)
    k = p["k_obs"] * (1 - p["policy_share"]) / p["u_obs"] * (1 + p["k_drift"]) ** np.maximum(years + 0.5 - T0 - 0.5, 0) * p["k_mult"]
    cap_rev = S * k * p["u"]
    if p.get("demand_on"):
        D = np.array([p["q2_run_rate"] * (1 - p["policy_share"]) * (1 + p["demand_g"]) ** max(y - 2026, 0) * f for y, f in zip(years, frac)])
        R = np.minimum(cap_rev, D)
    else:
        R = cap_rev
    loss = p["loss_share"] * np.clip(years + 1 - p["loss_year"], 0, 1)  # customer loss phased in over its first year
    R = R * (1 - loss)
    util = np.divide(R, S * k, out=np.zeros_like(R), where=S * k > 0)
    opex = p["opex_pct"] * R
    ebit = R - C - opex
    tax = p["tax"] * np.maximum(ebit, 0)
    fcf = ebit - tax
    pv_rev = float(((R - opex - tax) * (1 + p["rate_rev"] + p["rate_premium"]) ** (-mid)).sum())
    pv_pay = float((C * (1 + p["rate_pay"]) ** (-mid)).sum())
    cash = p["liquidity"] + (p["revolver"] if p["revolver_in_cash"] else 0) + np.cumsum(fcf)
    return {"C": C, "train": train, "S": S, "k": k, "R": R, "util": util, "gp_serving": R - S, "fcf": fcf, "cash": cash, "npv": pv_rev - pv_pay, "pv_rev": pv_rev, "pv_pay": pv_pay,
            "min_cash": float(cash.min()), "min_cash_year": int(years[cash.argmin()]), "breakeven_R": C / (1 - p["opex_pct"])}


def solve_mult(p, sched, lo=0.0, hi=20.0):
    """Price-efficiency multiple (of the observed revenue per used serving dollar) at which NPV = 0.
    Returns NaN when no multiple in [lo, hi] reaches NPV = 0 (e.g. revenue is capped by demand), so callers can say 'no break-even'."""
    q = dict(p)
    if model(dict(q, k_mult=hi), sched)["npv"] <= 0:
        return float("nan")
    if model(dict(q, k_mult=lo), sched)["npv"] > 0:
        return lo
    for _ in range(80):
        q["k_mult"] = (lo + hi) / 2
        lo, hi = (lo, q["k_mult"]) if model(q, sched)["npv"] > 0 else (q["k_mult"], hi)
    return (lo + hi) / 2


def solve_demand(p, sched, covenant, lo=-0.5, hi=5.0):
    """Lowest constant annual demand growth from the Q2 2026 run-rate (revenue capped by capacity at p['u']) that gives
    NPV >= 0, and separately cash >= covenant in every year. NaN when even `hi` fails (capacity-bound)."""
    def solve(ok):
        if not ok(hi):
            return float("nan")
        a, b = lo, hi
        if ok(a):
            return a
        for _ in range(60):
            m = (a + b) / 2
            a, b = (a, m) if ok(m) else (m, b)
        return b
    q = dict(p, demand_on=True, k_mult=1.0)
    g_npv = solve(lambda g: model(dict(q, demand_g=g), sched)["npv"] >= 0)
    g_cash = solve(lambda g: model(dict(q, demand_g=g), sched)["min_cash"] >= covenant)
    g_both = float("nan") if (np.isnan(g_npv) or np.isnan(g_cash)) else max(g_npv, g_cash)
    return {"g_npv": g_npv, "g_cash": g_cash, "g_both": g_both}


import s1_hurdle
HURDLE = s1_hurdle.rates({"operating": FACTS["lease_rate_operating"].value / 100, "finance": FACTS["lease_rate_finance"].value / 100},
                         {"operating": lease_pv["op_jun26"], "finance": lease_pv["fin_jun26"]})
ASSUMPTIONS.pop("rate", None)
ASSUMPTIONS["rate_rev"] = {"value": round(HURDLE["r_rev"], 4), "label": "Discount rate on revenue net of variable costs and tax",
                           "why": f"Unlevered cost of capital: 10-year Treasury {HURDLE['rf']:.2%} ({HURDLE['as_of']}) + median unlevered beta {HURDLE['beta_u']:.2f} of ten listed AI peers × US equity risk premium {HURDLE['erp']:.2%}. Unlevered because the fixed payments are valued separately at a debt rate."}
ASSUMPTIONS["rate_pay"] = {"value": round(HURDLE["r_pay"], 4), "label": "Discount rate on fixed compute payments",
                           "why": f"Anthropic's own incremental borrowing rate as disclosed: lease-liability-weighted average of the operating ({FACTS['lease_rate_operating'].value}%) and finance ({FACTS['lease_rate_finance'].value}%) lease discount rates in Note 7."}
ASSUMPTIONS["rate_premium"] = {"value": 0.0, "label": "Extra premium on the revenue-side rate", "why": "Zero in the base case; use it to stress pre-IPO, concentration or model-obsolescence risk beyond what listed peers' betas capture."}
ASSUMPTIONS["policy_share"] = {"value": round((FACTS["policy_rev_lo"].value + FACTS["policy_rev_hi"].value) / 200, 4), "label": "Revenue from usage-policy violators removed from the calibration",
                               "why": f"The filing estimates {FACTS['policy_rev_lo'].value:.0f}–{FACTS['policy_rev_hi'].value:.0f}% of 9M 2026 revenue came from customers violating usage policy or commercial terms and expects it to decline; the midpoint is taken out of revenue per serving dollar."}
ASSUMPTIONS["loss_share"] = {"value": 0.0, "label": "Share of revenue lost to customer churn or in-sourcing", "why": "Zero in the base case. The stress presets use the top-five share the filing gives (Q3 2026) to model the largest customers moving to their own or a competitor's models."}
ASSUMPTIONS["loss_year"] = {"value": 2028, "label": "Year the customer loss starts", "why": "Assumption; phased in over that year."}
BASE = {"u": 0.9, "k_mult": 1.0, "train_start": round(OBS["train_start"], 4), "train_end": ASSUMPTIONS["train_end"]["value"], "ramp_year": ASSUMPTIONS["ramp_year"]["value"],
        "k_obs": round(OBS["k_obs"], 4), "u_obs": ASSUMPTIONS["u_obs"]["value"], "k_drift": ASSUMPTIONS["k_drift"]["value"], "opex_pct": ASSUMPTIONS["opex_pct"]["value"],
        "tax": ASSUMPTIONS["tax"]["value"], "rate_rev": ASSUMPTIONS["rate_rev"]["value"], "rate_pay": ASSUMPTIONS["rate_pay"]["value"], "rate_premium": 0.0,
        "policy_share": ASSUMPTIONS["policy_share"]["value"], "loss_share": 0.0, "loss_year": 2028, "liquidity": round(OBS["liquidity"], 2), "revolver": OBS["revolver"],
        "revolver_in_cash": ASSUMPTIONS["revolver_in_cash"]["value"], "demand_on": False, "demand_g": 0.6, "q2_run_rate": OBS["q2_run_rate"]}


def scope_sched(toggles):
    keep = [l[0] for l in LEDGER if (l[9] or toggles.get(l[10], False)) and not (l[10] in ("spacexai_cancel", "vendor_conditional") and toggles.get(l[10], False))]
    return SCHED.loc[keep].sum().values, keep


def scenarios(toggles=None):
    toggles = toggles or {}
    sched, keep = scope_sched(toggles)
    rows = []
    for u in (0.5, 0.7, 0.9):
        p = dict(BASE, u=u)
        r = model(p, sched)
        m = solve_mult(p, sched)
        req = model(dict(p, k_mult=m if not np.isnan(m) else 1.0), sched)
        if np.isnan(m):
            req = {kk: (np.full(len(YEARS), np.nan) if isinstance(vv, np.ndarray) else vv) for kk, vv in req.items()}
        peak_i = int(np.nanargmax(req["R"])) if not np.isnan(m) else 0
        dem = solve_demand(p, sched, OBS["min_liquidity"])
        rows.append({"utilization": u, "npv_at_observed_busd": r["npv"], "min_cash_busd": r["min_cash"], "min_cash_year": r["min_cash_year"],
                     "revenue_2028_at_observed_busd": r["R"][YEARS.index(2028)], "required_price_efficiency_vs_observed": m,
                     "required_revenue_2027_busd": req["R"][YEARS.index(2027)], "required_revenue_2028_busd": req["R"][YEARS.index(2028)], "required_revenue_2030_busd": req["R"][YEARS.index(2030)],
                     "required_revenue_peak_busd": req["R"][peak_i], "required_peak_year": YEARS[peak_i],
                     "required_cagr_from_q2_run_rate": (req["R"][peak_i] / OBS["q2_run_rate"]) ** (1 / max(YEARS[peak_i] + 0.5 - T0, 0.5)) - 1,
                     "required_utilization_at_observed_price": u * m, "required_load_vs_h1_2026": u * m / p["u_obs"],
                     "demand_growth_for_npv": dem["g_npv"], "demand_growth_for_covenant": dem["g_cash"], "demand_growth_for_both": dem["g_both"]})
    return pd.DataFrame(rows), sched, keep


SCEN, SCHED_BASE, KEEP_BASE = scenarios()
SCEN_STRESS, _, _ = scenarios({"spacexai_cancel": True, "vendor_conditional": True})
TOP5_Q3 = 1 - FACTS["outside_top5_q3_26"].value / 100
_b = dict(BASE)
BASE.update(loss_share=TOP5_Q3, loss_year=2028)
SCEN_LOSS, _, _ = scenarios()
BASE.clear(); BASE.update(_b)

if __name__ == "__main__":
    pd.DataFrame([f.row() for f in FACTS.values()]).to_csv(HERE / "anthropic_s1_filing_facts.csv", index=False)
    pd.DataFrame([{k: v for k, v in b.items() if k != "steps"} for b in BRIDGES.values()]).to_csv(HERE / "anthropic_s1_margin_bridge.csv", index=False)
    eff.to_csv(HERE / "anthropic_s1_quarterly_efficiency.csv", index=False)
    ledger.to_csv(HERE / "anthropic_s1_contract_ledger.csv", index=False)
    pd.concat({f"ramp {r_}y": S_ for r_, S_ in SCHEDS.items()}).round(3).to_csv(HERE / "anthropic_s1_payment_calendar.csv")
    RECON.to_csv(HERE / "anthropic_s1_ledger_reconciliation.csv", index=False)
    pd.concat([SCEN.assign(scope="binding (A-E)"), SCEN_STRESS.assign(scope="SpaceXAI cancelled at notice, vendor-conditional excluded"), SCEN_LOSS.assign(scope=f"binding, top-five revenue ({TOP5_Q3:.0%}) lost from 2028")]).to_csv(HERE / "anthropic_s1_utilization_scenarios.csv", index=False)
    pd.DataFrame([{"key": k, **v} for k, v in ASSUMPTIONS.items()]).to_csv(HERE / "anthropic_s1_model_assumptions.csv", index=False)
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 90)
    print(f"{len(FACTS)} facts extracted")
    for p_, b in BRIDGES.items():
        print(p_, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in b.items() if k not in ("steps", "period")})
    print(eff[["quarter", "revenue", "compute", "rev_per_compute", "incremental_ratio", "rolling_2q_ratio", "lag1_ratio", "lag2_ratio", "efficiency_qoq"]].round(2))
    print(YOY.round(3))
    print(ledger[["id", "amount_busd", "status", "window", "in_base_case", "toggle"]])
    print(RECON.round(1))
    for r_, S_ in SCHEDS.items():
        print(f"ramp {r_}: ledger H2 2026 payments (binding) {S_.loc[KEEP_BASE, 2026].sum():.1f} vs Q2 2026 compute expense x2 {qt['compute']['Q2 2026'] * 2 / 1000:.1f}; 2027 {S_.loc[KEEP_BASE, 2027].sum():.1f}")
    print("payment calendar (binding, $B):", dict(zip(YEARS, SCHED.loc[KEEP_BASE].sum().round(1))))
    print("BASE", BASE)
    print(SCEN.round(3).T)
    print(SCEN_STRESS.round(3).T)
    print(SCEN_LOSS.round(3).T)
    print("HURDLE", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in HURDLE.items() if k != "peers"})
