"""Generate jev_anthropic_s1.ipynb: Anthropic's S-1 (filed 2026-10-26) read with Jev for (1) risk-factor weighting and (2) financing structure."""
import nbformat as nbf
from pathlib import Path
import re as _re

nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(_re.sub(r"(?<!\\)\$", r"\\$", s.strip("\n"))))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))

md(r"""
# Jev × EDGAR: Anthropic's S-1 — what the risk factors weigh, and how the company is financed

Anthropic, PBC filed its Form S-1 on October 26, 2026 (CIK 2130357, proposed ticker ANT). This notebook reads the
registration statement the way the earlier CoreWeave notebooks read credit agreements and 10-Qs: code recovers the
document's structure, Jev supplies the judgments that need reading, and arithmetic stays in pandas. It asks two
questions.

**1. Which risks does the filing name, and does it weight them in proportion to its own facts?** The Risk Factors
section is about 95 pages. Each risk factor is extracted from the HTML (the bold-italic headings are the unit),
typed by Jev (theme, specificity, whether the risk has already materialized, the strength of the consequence
language, who controls it), and then weighed three ways: by the share of risk-factor words it receives, by how much
concrete evidence the rest of the filing carries for that theme (Jev reads every passage of the Summary, MD&A,
Business, Governance, Related-Party and Financial Statement sections for theme-bearing facts), and by whether a
near-identical heading appears in a peer S-1 (CoreWeave, March 2025), which separates industry boilerplate from
Anthropic-specific disclosure. "Overweighted" here means more words than facts; "underweighted" means more facts
than words. It is a measure of emphasis against the document's own evidence, not a probability of loss.

**2. What does the financing structure look like?** The Liquidity section, the notes to the financial statements and
the related-party section are split into instrument blocks. Figures are pulled by regex from the specific sentences
and tables that state them; Jev types each instrument (what it is, drawn or contingent, cash- or share-settled,
secured or not, tied to compute or not) and each compute commitment (fixed regardless of usage, fees as delivered,
cancelable how). A counterparty role map asks, for every passage that names Amazon, Google, Microsoft, Broadcom, AMD
and the GPU-cloud vendors, which of seven roles the passage establishes: investor, financing source, supplier,
lessor, customer, distribution channel, competitor.

**Three things to know before reading the results**

* The S-1 is the first public filing and the price range is not yet set: the capitalization, dilution and
  contractual-obligations tables carry blanks. Everything here comes from the figures the filing does state, with
  the quoted sentence next to each one. There is no secondary source in this notebook.
* The weighting method is relative. A theme can be "proportionate" and still be the most important risk in the
  document; the index only says whether the words and the facts line up.
* Jev's confidence is a property of its probability distribution, not measured accuracy. Author-read checks sit in a
  separate table at the end, and every number in the generated summary is produced by the run.

Requirements: `TYPESAFE_API_KEY` (environment, `.env.local`, or Colab secret) and optionally `EDGAR_IDENTITY`.
""")

md("## 0. Setup")
code(r"""
import importlib, subprocess, sys

for pkg, mod in [("typesafe-sdk", "typesafe_sdk"), ("pandas", "pandas"), ("requests", "requests"),
                 ("matplotlib", "matplotlib"), ("python-dotenv", "dotenv"), ("beautifulsoup4", "bs4"), ("lxml", "lxml")]:
    if importlib.util.find_spec(mod) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
""")
code(r"""
import os
from pathlib import Path

from dotenv import load_dotenv

for env_file in (Path(".env.local"), Path("../.env.local")):
    if env_file.exists():
        load_dotenv(env_file)
        break


def secret(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if not value:
        try:
            from google.colab import userdata  # type: ignore

            value = userdata.get(name)
        except Exception:
            value = None
    if not value and default is not None:
        return default
    if not value:
        raise RuntimeError(f"Set {name} in the environment, in .env.local, or as a Colab secret")
    return value


TYPESAFE_API_KEY = secret("TYPESAFE_API_KEY")
EDGAR_IDENTITY = secret("EDGAR_IDENTITY", default="Example user@example.com")
print("keys loaded; EDGAR identity:", EDGAR_IDENTITY)
""")
code(r"""
import json
import math
import re
import threading
import time
import warnings
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from IPython.display import Markdown, display
from typesafe_sdk import Choice, Noul, NoulCriteria, Score, TypeSafeClient

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
pd.set_option("display.max_colwidth", 120)
pd.set_option("display.width", 220)

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": "#c3c2b7",
    "axes.grid": True, "grid.color": "#e1e0d9", "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "axes.titlesize": 11, "axes.labelsize": 9, "xtick.labelsize": 8,
    "ytick.labelsize": 8, "text.color": "#0b0b0b", "axes.labelcolor": "#52514e",
    "xtick.color": "#898781", "ytick.color": "#898781", "axes.prop_cycle": matplotlib.cycler(color=PALETTE),
})

PRICE_PER_MTOK_INPUT = 0.042
ts = TypeSafeClient(api_key=TYPESAFE_API_KEY, timeout=90.0)
LOG: list[dict] = []
REVIEW_FLAGS: list[dict] = []


def flag(item, reason):
    REVIEW_FLAGS.append({"item": item, "reason": reason})


def ask(state, questions, section: str, attempts: int = 3):
    for i in range(attempts):
        t0 = time.perf_counter()
        try:
            response = ts.system_one(state, questions)
        except Exception as e:  # transient 429/5xx: back off and retry, then give up loudly
            if i == attempts - 1:
                raise
            time.sleep(1.5 * (i + 1))
            continue
        LOG.append({"section": section, "model": response.model, "questions": len(questions),
                    "latency_ms": (time.perf_counter() - t0) * 1000,
                    "input_tokens": response.usage.input_tokens or 0,
                    "cost_usd": (response.usage.input_tokens or 0) * PRICE_PER_MTOK_INPUT / 1e6})
        return response


SEC_BASE, SEC_ARCHIVES = "https://data.sec.gov", "https://www.sec.gov/Archives/edgar/data"
HEADERS = {"User-Agent": EDGAR_IDENTITY, "Accept": "application/json"}
CACHE = next((p for p in (Path("edgar_cache"), Path("../edgar_cache")) if p.exists()), Path("edgar_cache"))  # shared cache at the project root
CACHE.mkdir(exist_ok=True)
_rate_lock, _last_call = threading.Lock(), [0.0]


def edgar_get(url: str, fresh: bool = False) -> bytes:
    key = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:])
    if key.exists() and not fresh:
        return key.read_bytes()
    with _rate_lock:
        wait = 0.125 - (time.perf_counter() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.perf_counter()
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    key.write_bytes(r.content)
    return r.content


def html_to_text(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"[ \t\xa0​]+", " ", soup.get_text("\n"))
    return re.sub(r"\n\s*\n+", "\n", text).strip()


flat = lambda s: re.sub(r"\s+", " ", s or "").strip()
STOP = set("the and for that with this our are will may not any such from have has been were which these those their its into been also could would should other than more been upon under over about".split())


def tokens(s):
    return [w.strip(".,") for w in re.findall(r"[a-z0-9.%$]+", s.lower()) if w.strip(".,") not in STOP and len(w.strip(".,")) > 2]


print("available models:", [m.name for m in ts.models.list().models])
""")

md(r"""
## 1. The filing: sections by page, passages, and the 88 risk factors

EDGAR's submissions index gives the S-1 and its primary document. The prospectus prints a page number at the foot of
every page followed by the running "Table of Contents" header, so pages are recoverable from the text, and the table
of contents maps page ranges to sections. Passages of about 1,500 characters are cut inside each section and keep
their page. The risk factors themselves come from the HTML rather than the text: each risk factor heading is a
bold-italic paragraph and each group heading is bold 12-point, which is a more reliable boundary than any regex over
sentences. A check compares the words recovered through the headings with the words in the Risk Factors page range.
""")
code(r"""
CIK = "2130357"
subs = json.loads(edgar_get(f"{SEC_BASE}/submissions/CIK{int(CIK):010d}.json"))
recent = pd.DataFrame(subs["filings"]["recent"])
s1 = recent[recent.form == "S-1"].sort_values("filingDate").iloc[-1]
ACC = s1.accessionNumber.replace("-", "")
S1_URL = f"{SEC_ARCHIVES}/{CIK}/{ACC}/{s1.primaryDocument}"
print(subs["name"], "| S-1 filed", s1.filingDate, "|", S1_URL)
display(recent[["accessionNumber", "form", "filingDate", "primaryDocument"]].head(8))

raw_html = edgar_get(S1_URL)
text = html_to_text(raw_html)
lines = text.split("\n")
print(f"{len(raw_html)/1e6:.1f} MB of HTML -> {len(text):,} characters, {len(lines):,} lines")
""")
code(r"""
# --- pages: a footer page number immediately followed by the running "Table of Contents" header
marks = [(i, lines[i].strip()) for i in range(len(lines) - 1)
         if re.fullmatch(r"(F-)?\d{1,3}|II-\d", lines[i].strip()) and lines[i + 1].strip() == "Table of Contents"]
pages = []  # (page_label, text) in document order
prev = 0
for i, label in marks:
    pages.append((label, "\n".join(lines[prev:i])))
    prev = i + 2
tail = lines[prev:]
ii = next((k for k, l in enumerate(tail) if l.strip() == "II-1"), None)
if ii is not None:  # the last financial-statement page has no running header after it; split at the first Part II footer
    pages.append(("F-end", "\n".join(tail[:ii])))
    pages.append(("II", "\n".join(tail[ii + 1:])))
else:
    pages.append(("II", "\n".join(tail)))

# --- table of contents: section name (one or two lines) followed by its page
toc, k = [], next(i for i, l in enumerate(lines) if l.strip() == "SELECT DEFINED TERMS")
while k < len(lines) - 2 and len(toc) < 40:
    a, b, c = lines[k].strip(), lines[k + 1].strip(), lines[k + 2].strip()
    if re.fullmatch(r"\d{1,3}|F-1", b) and a and not re.fullmatch(r"\d+", a):
        toc.append((a, b)); k += 2
    elif re.fullmatch(r"\d{1,3}|F-1", c) and a and b and not re.fullmatch(r"\d+", b):
        toc.append((a + " " + b, c)); k += 3
    else:
        k += 1
    if toc and toc[-1][0] == "INDEX TO CONSOLIDATED FINANCIAL STATEMENTS":
        break
SHORT = {"MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS": "MD&A",
         "INDEX TO CONSOLIDATED FINANCIAL STATEMENTS": "FINANCIAL STATEMENTS",
         "MATERIAL U.S. FEDERAL INCOME TAX CONSEQUENCES TO NON-U.S. HOLDERS OF OUR CLASS A COMMON STOCK": "TAX",
         "CERTAIN RELATIONSHIPS AND RELATED PERSON TRANSACTIONS": "RELATED PERSON TRANSACTIONS",
         "OUR GOVERNANCE STRUCTURE AND ITS GOALS": "GOVERNANCE", "SPECIAL NOTE REGARDING FORWARD-LOOKING STATEMENTS": "FORWARD-LOOKING STATEMENTS"}
toc_num = [(SHORT.get(n, n), int(p)) for n, p in toc if p.isdigit()]


def section_of(page_label):
    if page_label.startswith("F-"):
        return "FINANCIAL STATEMENTS"
    if page_label.startswith("II"):
        return "PART II"
    p = int(page_label)
    name = "COVER"
    for n, start in toc_num:
        if start <= p:
            name = n
    return name


page_df = pd.DataFrame([{"page": p, "section": section_of(p), "chars": len(t)} for p, t in pages])
sec_summary = page_df.groupby("section", sort=False).agg(pages=("page", "size"), first_page=("page", "first"), chars=("chars", "sum"))
display(sec_summary)
print(f"{len(pages)} pages recovered; {len(toc)} table-of-contents entries")
""")
code(r"""
PASSAGES = []
SECTION_TEXT = {}
for sec in sec_summary.index:
    chunk, offsets = [], []
    pos = 0
    for p, t in pages:
        if section_of(p) != sec:
            continue
        offsets.append((pos, p))
        chunk.append(t)
        pos += len(t) + 1
    joined = "\n".join(chunk)
    SECTION_TEXT[sec] = joined
    i, j = 0, 0
    while i < len(joined):
        page = [p for off, p in offsets if off <= i][-1] if offsets else "?"
        PASSAGES.append({"section": sec, "page": page, "pid": f"{sec}#{j}", "text": flat(joined[i:i + 1500])})
        i += 1300
        j += 1
pass_df = pd.DataFrame(PASSAGES)
print(f"{len(PASSAGES):,} passages;", dict(pass_df.section.value_counts()))
""")
code(r"""
# --- risk factors from the HTML: bold-italic paragraphs are risk headings, bold 12pt paragraphs are group headings
soup = BeautifulSoup(raw_html, "lxml")
style = lambda tag: tag.get("style", "") if tag else ""
blocks = []
for div in soup.find_all("div"):
    kids = [k for k in div.children if getattr(k, "name", None)]
    if not kids or any(k.name != "font" for k in kids):
        continue
    fonts = [k for k in kids if k.get_text(strip=True)]
    if not fonts:
        continue
    bold = all("font-weight:bold" in style(f) or "font-weight:700" in style(f) for f in fonts)
    ital = all("font-style:italic" in style(f) for f in fonts)
    size = re.search(r"font-size:([\d.]+)pt", style(fonts[0]))
    blocks.append({"text": flat(div.get_text(" ")), "bold": bold, "italic": ital, "size": float(size.group(1)) if size else 0.0})

starts = [i for i, b in enumerate(blocks) if b["text"].startswith("Risks Related to our Business and Industry") and b["bold"] and not b["italic"]]
ends = [i for i, b in enumerate(blocks) if b["text"].upper().startswith("SPECIAL NOTE REGARDING FORWARD") and b["bold"] and i > starts[-1]]
s_idx, e_idx = starts[-1], ends[0]
risk_rows, cur_group, cur, i = [], None, None, s_idx
while i < e_idx:
    b = blocks[i]
    if b["bold"] and not b["italic"] and b["size"] >= 11:
        cur_group = b["text"]; i += 1; continue
    if b["bold"] and b["italic"]:
        head = [b["text"]]; i += 1
        while i < e_idx and blocks[i]["bold"] and blocks[i]["italic"]:
            head.append(blocks[i]["text"]); i += 1
        cur = {"group": cur_group, "heading": " ".join(head), "body": []}
        risk_rows.append(cur); continue
    if cur is not None and b["text"] != "Table of Contents" and not re.fullmatch(r"\d{1,3}", b["text"]):
        cur["body"].append(b["text"])
    i += 1
for n, r in enumerate(risk_rows, 1):
    r["body"] = " ".join(r["body"])
    r["words"] = len(r["body"].split())
    r["order"] = n
    r["dollar_figures"] = len(re.findall(r"\$\s?\d", r["body"]))
    r["percent_figures"] = len(re.findall(r"\d\s?%", r["body"]))
risks = pd.DataFrame(risk_rows).set_index("order")
risks["rid"] = [f"r{n:02d}" for n in risks.index]
page_flat = {p: flat(t) for p, t in pages if section_of(p) == "RISK FACTORS"}
risks["page"] = [next((p for p, t in page_flat.items() if h[:40] in t), next((p for p, t in page_flat.items() if h[-40:] in t), None)) for h in risks.heading]
GROUP_SHORT = {"Risks Related to our Business and Industry": "Business & industry", "Risks Related to Privacy, Cybersecurity, and Intellectual Property": "Privacy, cyber & IP",
               "Risks Related to Legal and Regulatory Matters": "Legal & regulatory", "Risks Related to Tax and Accounting Matters": "Tax & accounting",
               "Risks Related to our Governance Structure": "Governance", "Risks Related to Ownership of our Class A Common Stock": "Class A ownership"}
risks["group_short"] = risks.group.map(lambda g: GROUP_SHORT.get(flat(g), flat(g)))
rf_words_in_pages = sum(len(t.split()) for p, t in pages if section_of(p) == "RISK FACTORS")
coverage = risks.words.sum() / rf_words_in_pages
print(f"{len(risks)} risk factors in {risks.group.nunique()} groups; {risks.words.sum():,} words under headings vs {rf_words_in_pages:,} words in the Risk Factors page range ({coverage:.0%} covered)")
if not 0.9 <= coverage <= 1.05:
    flag("risk extraction", f"heading-based bodies cover {coverage:.0%} of the Risk Factors page range")
if risks.page.isna().any():
    flag("risk extraction", f"{int(risks.page.isna().sum())} headings not located on a page")
display(risks.groupby("group_short", sort=False).agg(factors=("words", "size"), words=("words", "sum"), median_words=("words", "median"), first_page=("page", "first")))
display(risks[["rid", "group_short", "page", "words", "dollar_figures", "percent_figures", "heading"]].head(12))
""")

md(r"""
## 2. Typing each risk factor with Jev

One request per risk factor, two passes. The state is the group, the heading and the body (the first 12,000
characters; the median factor is about 540 words and the longest about 4,000). The questions are the ones a reader
would answer in the margin:

* **theme** — a Choice over sixteen named themes plus "other". The descriptions name concrete situations rather than
  labels, because Jev reads literally.
* **specificity** — a four-level Score from language that could appear in any technology filing up to
  Anthropic-specific figures and dates next to named counterparties. This is the boilerplate measure.
* **materialized** — a Noul: does the text say the risk has already happened or is happening (past or present
  tense about Anthropic), not merely that it could.
* **consequence** — a three-level Score on the strength of the stated consequence, from "could adversely affect"
  through "material adverse effect" to existential wording (acceleration, inability to continue, loss of the
  entire investment).
* **control** — a Choice: largely within Anthropic's control, largely external, or mixed.
* **mitigation** and **conflict of interest** — Nouls: does the text describe steps Anthropic is taking; does it
  concern a counterparty that is simultaneously an investor, supplier, lessor, channel or competitor.

Dollar and percent figure counts are regex, not Jev, since counting is a jagged edge. The second pass repeats the
theme and specificity questions; a theme that flips between passes is flagged and the first pass is kept.
""")
code(r"""
THEMES = OrderedDict([
    ("compute_supply", "Securing enough compute: chips, data centers, power, memory, supply chain concentration, export restrictions on hardware, dependence on a few suppliers"),
    ("compute_commitments", "Fixed or minimum compute and infrastructure commitments, equipment leases and capital expenditures that must be paid regardless of usage, and the risk of committing to too much or too little capacity"),
    ("capital_access", "Needing additional capital, liquidity, debt covenants, the cost or availability of financing, dilution from future financings, and a history of net losses with an uncertain path to profitability"),
    ("csp_conflicts", "Reliance on cloud providers and chip partners such as Amazon, Google, Microsoft and Broadcom that are at the same time investors, suppliers, lessors, distribution channels or competitors, and the conflicts that creates"),
    ("revenue_customers", "Customer concentration, usage-based or short-term contracts, pricing pressure, revenue volatility, seasonality, and dependence on distribution channels for revenue"),
    ("competition", "Competition from other AI developers, hyperscalers, open-source and open-weight models, and new entrants"),
    ("model_execution", "Failing to keep developing frontier models and products, research or product execution, model quality, reliability, outages, and the pace of releases"),
    ("safety_misuse", "Harm caused by model behavior or misuse, safety incidents, hallucinations, catastrophic or dual-use capabilities, and reputational damage from AI harms"),
    ("regulation", "AI-specific laws, government regulation and investigations, export controls on model access, geopolitical and national security requirements"),
    ("ip_litigation", "Copyright and training-data lawsuits, intellectual property protection, indemnification claims, and settlements"),
    ("cyber_privacy", "Cybersecurity breaches, theft of model weights, data protection and privacy law compliance"),
    ("talent", "Dependence on founders, senior management and key technical employees, hiring, retention, culture and compensation"),
    ("governance", "Public benefit corporation status, the Long-Term Benefit Trust, Class F and Class T stock, founder control, controlled-company status, and public benefit share issuances"),
    ("accounting_tax", "Fair value accounting for convertible notes and derivatives, internal controls over financial reporting, tax exposure, non-GAAP measures, and the reliability of reported results"),
    ("stock_market", "Share price volatility, dilution of economic or voting interests, lock-ups and future sales, dual-class mechanics, no dividends, analyst coverage, exclusive forum provisions, and other risks of holding the Class A shares"),
    ("international_macro", "International operations, foreign currency, macroeconomic conditions, tariffs and trade, and operating across many jurisdictions"),
    ("operations_general", "General operating risks not specific to AI: managing growth, acquisitions and their integration, catastrophic events and business continuity, payment processing, insurance coverage, and risks compounding one another"),
    ("other", "None of the themes above describes the risk"),
])
SPECIFICITY = ["Generic language that could appear in any technology company's filing, with no detail particular to Anthropic",
               "Describes Anthropic's own situation in general terms, without naming counterparties, agreements, lawsuits, events or figures",
               "Names specific counterparties, agreements, lawsuits, products or dated events involving Anthropic, but gives no Anthropic-specific figures",
               "States Anthropic-specific dollar amounts, percentages or dates alongside named counterparties, agreements or events"]
CONSEQUENCE = ["The stated consequence is that the business, financial condition or results of operations could be adversely affected, or similar general wording",
               "The stated consequence is a material adverse effect, substantial harm, significant liability or a significant decline in the share price",
               "The stated consequence is existential or structural: acceleration of obligations, inability to continue operations, loss of the entire investment, loss of control of the company, or a required change to the business model"]
CONTROL = {"internal": "The risk arises mainly from Anthropic's own decisions, execution or systems",
           "external": "The risk arises mainly from third parties, markets, governments or events outside Anthropic's control",
           "mixed": "The risk depends about equally on Anthropic's own actions and on outside parties or events"}


def risk_questions():
    return {
        "theme": Choice(instructions="Which theme best describes the risk in `heading` and `body`? Judge by the risk itself, not by the group it was filed under.", criteria=dict(THEMES)),
        "specificity": Score(instructions="How specific to Anthropic is the text of this risk factor (`heading` plus `body`)?", criteria=SPECIFICITY),
        "materialized": Noul(instructions="Does `body` state that this risk has already occurred or is currently occurring at Anthropic, in past or present tense (for example an event that happened, a lawsuit that was filed, a loss that was recorded, a condition that exists today)?",
                             criteria=NoulCriteria(true="The text reports that the risk has happened or is happening to Anthropic", false="The text only says the risk could or may happen")),
        "consequence": Score(instructions="How severe is the consequence that `body` states would follow if the risk occurred?", criteria=CONSEQUENCE),
        "control": Choice(instructions="Who mainly controls whether this risk occurs, according to `body`?", criteria=CONTROL),
        "mitigation": Noul(instructions="Does `body` describe concrete steps Anthropic is taking or has taken to reduce this risk?",
                           criteria=NoulCriteria(true="The text names actions, policies, programs or arrangements Anthropic uses against the risk", false="The text does not describe mitigating actions")),
        "conflict": Noul(instructions="Does `body` concern a counterparty that is described as simultaneously holding two or more of these roles toward Anthropic: investor or lender, supplier or lessor, distribution channel, customer, competitor?",
                         criteria=NoulCriteria(true="The text describes a counterparty with two or more of those roles", false="The text does not describe such a multi-role counterparty")),
    }


def type_risk(row, pass_no):
    state = {"group": flat(row.group), "heading": row.heading, "body": row.body[:12000]}
    q = risk_questions() if pass_no == 1 else {"theme": risk_questions()["theme"], "specificity": risk_questions()["specificity"]}
    r = ask(state, q, section=f"2 risk typing pass {pass_no}")
    out = {"rid": row.rid, "pass": pass_no, "theme": r.choices["theme"].choice, "theme_conf": round(r.choices["theme"].confidence, 2),
           "theme_p": round(r.choices["theme"].probabilities[r.choices["theme"].choice], 2), "specificity": round(r.scores["specificity"].score, 2)}
    if pass_no == 1:
        out.update({"specificity_conf": round(r.scores["specificity"].confidence, 2), "materialized": round(r.nouls["materialized"].noul, 2),
                    "consequence": round(r.scores["consequence"].score, 2), "control": r.choices["control"].choice, "control_conf": round(r.choices["control"].confidence, 2),
                    "mitigation": round(r.nouls["mitigation"].noul, 2), "conflict": round(r.nouls["conflict"].noul, 2)})
    return out


with ThreadPoolExecutor(6) as pool:
    p1 = list(pool.map(lambda r: type_risk(r, 1), risks.itertuples()))
    p2 = list(pool.map(lambda r: type_risk(r, 2), risks.itertuples()))
t1 = pd.DataFrame(p1).set_index("rid").drop(columns="pass")
t2 = pd.DataFrame(p2).set_index("rid").drop(columns="pass")
risks = risks.set_index("rid").join(t1)
risks["theme_pass2"] = t2.theme
risks["specificity_pass2"] = t2.specificity
risks["theme_stable"] = risks.theme == risks.theme_pass2
for rid, r in risks[~risks.theme_stable].iterrows():
    flag(f"theme:{rid}", f"theme flipped between passes: {r.theme} -> {r.theme_pass2} (pass-1 confidence {r.theme_conf}); pass 1 kept")
print(f"theme stable across passes on {int(risks.theme_stable.sum())} of {len(risks)}; specificity differs by more than 0.5 on {int((risks.specificity - risks.specificity_pass2).abs().gt(0.5).sum())}")
print("control:", dict(risks.control.value_counts()), "| theme p of the chosen option: median", risks.theme_p.median())
display(risks[["group_short", "page", "words", "theme", "theme_p", "specificity", "materialized", "consequence", "control", "mitigation", "conflict", "heading"]].head(20))
""")
code(r"""
low = risks[risks.theme_p < 0.5]
print(f"{len(low)} risk factors where the chosen theme holds less than half the probability (a second theme competes):")
for rid, r in low.iterrows():
    print(f"  {rid} {r.theme} ({r.theme_p}) vs {r.theme_pass2} | {r.heading[:110]}")
""")

md(r"""
## 3. Disclosure weight by theme

Weight as the filing itself assigns it: how many words each theme receives, how many factors, where the first
factor on the theme sits in the running order (page 26 is the front of the queue), how specific the writing is, how
much of it describes something that has already happened, and how strong the consequence language is. The
prospectus summary of this S-1 does not carry a bulleted risk summary, so there is no "summary inclusion" signal;
position in the running order stands in for it.
""")
code(r"""
TH = risks[risks.theme != "other"]
themes = TH.groupby("theme").agg(factors=("words", "size"), words=("words", "sum"), first_position=("page", "min"), first_order=("words", lambda s: int(min(int(x[1:]) for x in s.index))),
                                 specificity=("specificity", "mean"), share_materialized=("materialized", lambda s: (s >= 0.5).mean()),
                                 consequence=("consequence", "mean"), mitigation=("mitigation", lambda s: (s >= 0.5).mean()), figures=("dollar_figures", "sum"))
themes["word_share"] = themes.words / themes.words.sum()
themes = themes.reindex([t for t in THEMES if t in themes.index])
themes["boilerplate_words"] = TH[TH.specificity < 1.5].groupby("theme").words.sum().reindex(themes.index).fillna(0).astype(int)
themes["boilerplate_share"] = themes.boilerplate_words / themes.words
display(themes.sort_values("words", ascending=False).round({"specificity": 2, "share_materialized": 2, "consequence": 2, "mitigation": 2, "word_share": 3, "boilerplate_share": 2}))
missing = [t for t in THEMES if t not in themes.index and t != "other"]
print("themes with no risk factor assigned:", missing or "none", "| factors typed 'other':", int((risks.theme == "other").sum()))

fig, ax = plt.subplots(figsize=(8, 4.6))
order = themes.sort_values("words").index
spec = themes.loc[order, "specificity"]
colors = [plt.cm.Blues(0.35 + 0.6 * (s - 0.5) / 2.5) for s in spec]
ax.barh(order, themes.loc[order, "words"], color=colors, edgecolor="#fcfcfb")
for y, (w, n) in enumerate(zip(themes.loc[order, "words"], themes.loc[order, "factors"])):
    ax.text(w + 300, y, f"{n} factor{'s' if n > 1 else ''}", va="center", fontsize=7, color="#52514e")
ax.set_xlabel("words in the Risk Factors section (shade: mean specificity, darker = more Anthropic-specific)")
ax.set_title("Where the risk-factor words go")
plt.tight_layout()
plt.show()
""")

md(r"""
## 4. The document's own evidence, theme by theme

Two measures independent of the Risk Factors section.

**Evidence passages.** Every passage of the Prospectus Summary, MD&A, Business, Governance, Related Person
Transactions, Description of Capital Stock, Shares Eligible for Future Sale, Use of Proceeds, Capitalization and the
Financial Statements goes to Jev with sixteen Nouls, one per theme: does the passage state a concrete fact about
Anthropic (a figure, a named agreement or counterparty, a dated event, a lawsuit, a financial statement item) that
bears on the theme. A passage counts as evidence for a theme at probability 0.7 or above. The count per theme,
normalized, is the evidence share. The two strongest passages per theme are shown with their page so the reader can
see what the count is made of.

**Exposure anchors.** A short table of figures pulled by regex from the sentences that state them: commitments,
cash, the fair value charge, the settlement, the voting structure. Each anchor is mapped to a theme by the author
and expressed as a multiple of liquidity (cash plus short-term investments at June 30, 2026). Anchors overlap
(the Broadcom rent and the post-quarter commitments are different notes measuring different things), so they are
shown as a list, not summed.
""")
code(r"""
EVIDENCE_SECTIONS = ["PROSPECTUS SUMMARY", "USE OF PROCEEDS", "CAPITALIZATION", "MD&A", "BUSINESS", "GOVERNANCE", "RELATED PERSON TRANSACTIONS",
                     "DESCRIPTION OF CAPITAL STOCK", "SHARES ELIGIBLE FOR FUTURE SALE", "FINANCIAL STATEMENTS", "PART II"]
ev_pass = [p for p in PASSAGES if p["section"] in EVIDENCE_SECTIONS and len(p["text"]) > 300]
EV_THEMES = [t for t in THEMES if t != "other"]
est_tokens = sum(len(p["text"]) for p in ev_pass) / 4 + len(ev_pass) * 16 * 60
print(f"{len(ev_pass)} passages x {len(EV_THEMES)} theme questions; about {est_tokens/1e6:.1f}M input tokens, about ${est_tokens * PRICE_PER_MTOK_INPUT / 1e6:.3f}")


def evidence_questions():
    return {t: Noul(instructions=f"Does `passage` state a concrete fact about Anthropic (a figure; a named counterparty, competitor or product; a named agreement, policy or program; a dated event; a lawsuit; or a financial statement item) that bears on this risk theme: {desc}?",
                    criteria=NoulCriteria(true="The passage contains such a concrete fact and the fact relates to the theme", false="The passage mentions the theme only in general terms without a concrete fact, or its facts have nothing to do with the theme"))
            for t, desc in THEMES.items() if t != "other"}


def judge_passage(p):
    r = ask({"passage": p["text"], "section": p["section"], "page": p["page"]}, evidence_questions(), section="4 evidence")
    return {"pid": p["pid"], "section": p["section"], "page": p["page"], **{t: round(r.nouls[t].noul, 2) for t in EV_THEMES}, "text": p["text"]}


with ThreadPoolExecutor(6) as pool:
    ev_rows = list(pool.map(judge_passage, ev_pass))
ev = pd.DataFrame(ev_rows).set_index("pid")
EV_T = 0.7
hits = (ev[EV_THEMES] >= EV_T)
themes["evidence_passages"] = hits.sum().reindex(themes.index).fillna(0).astype(int)
themes["evidence_share"] = themes.evidence_passages / themes.evidence_passages.sum()
by_section = pd.DataFrame({t: hits[t].groupby(ev.section).sum() for t in EV_THEMES}).T.reindex(themes.index).fillna(0).astype(int)
by_section = by_section[[s for s in EVIDENCE_SECTIONS if s in by_section.columns]]
ev.drop(columns="text").to_csv("anthropic_s1_evidence_hits.csv")
print(f"{int(hits.values.sum())} (passage, theme) evidence hits at >= {EV_T} across {int(hits.any(axis=1).sum())} passages; passages with no theme: {int((~hits.any(axis=1)).sum())}")
display(by_section)

fig, ax = plt.subplots(figsize=(9, 5))
im = ax.imshow(by_section.values, cmap="Blues", aspect="auto")
ax.set_xticks(range(len(by_section.columns))); ax.set_xticklabels(by_section.columns, rotation=35, ha="right", fontsize=7)
ax.set_yticks(range(len(by_section.index))); ax.set_yticklabels(by_section.index, fontsize=8)
ax.grid(False)
for i in range(by_section.shape[0]):
    for j in range(by_section.shape[1]):
        v = by_section.values[i, j]
        if v:
            ax.text(j, i, str(v), ha="center", va="center", fontsize=7, color="white" if v > by_section.values.max() * 0.6 else "#0b0b0b")
ax.set_title(f"Evidence passages per theme (Jev Noul >= {EV_T}) by section")
plt.tight_layout()
plt.show()
""")
code(r"""
top_ev = []
for t in EV_THEMES:
    best = ev.sort_values(t, ascending=False).head(2)
    for pid, r in best.iterrows():
        top_ev.append({"theme": t, "p": r[t], "section": r.section, "page": r.page, "passage": r.text[:260] + "…"})
top_ev = pd.DataFrame(top_ev)
display(top_ev)
""")
code(r"""
# --- exposure anchors: figures the filing states, pulled from the sentence that states them
FS = flat(SECTION_TEXT["FINANCIAL STATEMENTS"]); MDA = flat(SECTION_TEXT["MD&A"]); RF = flat(SECTION_TEXT["RISK FACTORS"]); GOV = flat(SECTION_TEXT["GOVERNANCE"]); PS = flat(SECTION_TEXT["PROSPECTUS SUMMARY"])
REL = flat(SECTION_TEXT["RELATED PERSON TRANSACTIONS"])


def grab(pattern, source, scale=1.0, group=1, as_text=False):
    m = re.search(pattern, source)
    if not m:
        return None
    if as_text:
        return m.group(group)
    return float(m.group(group).replace(",", "").replace(" ", "")) * scale


def row_values(source, label, n, after=""):
    # numeric cells after a table row label; "(x)" is negative, "—" is zero
    m = re.search(re.escape(label) + after + r"((?:\s*(?:\$\s*)?(?:\([\d,]+\)|[\d,]+|—)){" + str(n) + "})", source)
    if not m:
        return None
    vals = []
    for tok in re.findall(r"\([\d,]+\)|[\d,]+|—", m.group(1)):
        vals.append(0.0 if tok == "—" else (-float(tok.strip("()").replace(",", "")) if tok.startswith("(") else float(tok.replace(",", ""))))
    return vals


A = {}
A["cash_busd"] = grab(r"cash and cash equivalents of \$([\d.]+) billion", MDA)
A["sti_busd"] = grab(r"\$([\d.]+) billion of short-term investments", MDA)
A["liquidity_busd"] = (A["cash_busd"] or 0) + (A["sti_busd"] or 0)
A["min_commitments_jun30_busd"] = grab(r"expected future fixed or minimum guaranteed commitments under these agreements were approximately \$([\d.]+) billion", FS)
A["commitments_dec31_table_busd"] = (row_values(FS, "Total non-cancelable contractual commitments", 1) or [None])[0]
FS_UNAUD = FS[FS.find("Subsequent Events (Unaudited)"):] if "Subsequent Events (Unaudited)" in FS else ""
if not FS_UNAUD:
    flag("anchors", "unaudited subsequent-events note not found in the financial statements section")
A["post_dec31_commitments_busd"] = grab(r"Subsequent to December 31, 2025[^.]*?aggregate future minimum payment obligations of approximately \$([\d.]+) billion", FS)
A["post_quarter_commitments_busd"] = grab(r"subsequent to June 30, 2026[^.]*?aggregate future minimum payment obligations of approximately \$([\d.]+) billion", FS_UNAUD)
A["post_quarter_short_term_busd"] = grab(r"short term in nature with minimum non-cancelable payments under such contracts of approximately \$([\d.]+) billion", FS_UNAUD)
A["broadcom_rent_busd"] = grab(r"rent payments over the life of these leases are equal to an aggregate of approximately \$([\d.]+) billion", MDA)
A["lease_2026_rent_busd"] = grab(r"five-year equipment lease are equal to an aggregate of approximately \$([\d.]+) billion", RF)
A["tpu_estimate_low_busd"] = grab(r"approximately \$([\d.]+) billion to \$[\d.]+ billion, which are not included", MDA)
A["tpu_estimate_high_busd"] = grab(r"approximately \$[\d.]+ billion to \$([\d.]+) billion, which are not included", MDA)
A["amazon_notes_busd"] = grab(r"approximately \$([\d.]+) billion aggregate principal amount of which remains outstanding", MDA)
A["npa_capacity_busd"] = (grab(r"Total \$ ([\d,]+) \$ —", MDA) or 0) / 1000 or None
A["revolver_busd"] = grab(r"\$(\d+) billion senior secured revolving credit facility with the full amount", MDA)
A["min_liquidity_covenant_busd"] = grab(r"of at least \$([\d.]+) billion as of the last day of each fiscal quarter", MDA)
A["fv_change_h1_2026_busd"] = grab(r"including \$([\d.]+) billion during the six months ended June 30, 2026", MDA)
A["fv_cumulative_busd"] = grab(r"accumulated deficit of \$[\d.]+ billion\s*,\s*which includes \$([\d.]+) billion related to changes in the fair value", MDA)
A["accumulated_deficit_busd"] = grab(r"accumulated deficit of \$([\d.]+) billion", MDA)
A["convertible_notes_carrying_musd"] = (row_values(FS, "Convertible notes payable", 3) or [None] * 3)[2]
A["bartz_settlement_busd"] = grab(r"settlement in the amount of \$([\d.]+) billion", FS)
A["bartz_accrued_jun30_busd"] = grab(r"\$([\d.]+) billion in accounts payable, accrued expenses, and other current liabilities as of June 30, 2026", FS)
A["top5_customers_pct"] = grab(r"top five customers represented approximately (\d+)% of our revenue", RF)
A["class_f_vote_pct"] = grab(r"equals (\d+\.\d)% of the total voting power", GOV)
A["public_benefit_issuance_pct"] = grab(r"representing (\d+) ?% of our fully diluted shares", MDA)
A["rsu_grants_post_q_busd"] = grab(r"aggregate grant date fair value of \$([\d.]+) billion", FS)
A["donation_match_q3_busd"] = grab(r"recognized \$([\d.]+) billion within other operating and administrative expense", FS)
A["revenue_h1_2026_musd"] = (row_values(PS, "Revenue", 5, after=r"\s*\$") or [None] * 5)[4]
A["operating_loss_h1_2026_musd"] = (row_values(PS, "Operating loss", 5) or [None] * 5)[4]
A["op_cf_h1_2026_musd"] = (row_values(MDA, "Operating activities", 5, after=r"\s*\$") or [None] * 5)[4]
A["fin_cf_h1_2026_musd"] = (row_values(MDA, "Financing activities", 5) or [None] * 5)[4]
VENDOR_COMMIT = {"Microsoft": grab(r"agreement with Microsoft[^.]*?at least \$([\d.]+) billion", MDA), "Google": grab(r"agreement with Google[^.]*?at least approximately \$([\d.]+) billion", MDA),
                 "Amazon": grab(r"agreement with Amazon, pursuant to which we committed to spend an aggregate of at least \$([\d.]+) billion", MDA),
                 "SpaceXAI": grab(r"SpaceXAI Arrangements, we agreed to spend an aggregate of up to \$([\d.]+) billion", MDA), "Nscale": grab(r"Nscale Services Agreements, we agreed to spend an aggregate of up to approximately \$([\d.]+) billion", MDA),
                 "Lambda": grab(r"Lambda Agreements, we agreed to spend an aggregate of approximately \$([\d.]+) billion", MDA), "AMD": grab(r"we expect aggregate expenditures to exceed \$([\d.]+) billion", MDA)}
for k, v in A.items():
    if v is None:
        flag(f"anchor:{k}", "regex found no value in the expected section")
liq = A["liquidity_busd"]
ANCHORS = [
    ("compute_commitments", "Fixed or minimum purchase commitments at June 30, 2026 (Note 13)", A["min_commitments_jun30_busd"]),
    ("compute_commitments", "Minimum commitments added after December 31, 2025, per the audited subsequent-events note", A["post_dec31_commitments_busd"]),
    ("compute_commitments", "Minimum commitments added after June 30, 2026 (Note 17)", A["post_quarter_commitments_busd"]),
    ("compute_commitments", "Short-term non-cancelable commitments added after June 30 (Note 17)", A["post_quarter_short_term_busd"]),
    ("compute_commitments", "Broadcom equipment lease rent, excluding interest (MD&A)", A["broadcom_rent_busd"]),
    ("compute_commitments", "Additional TPU compute, estimated, not in the commitments table (MD&A, low end)", A["tpu_estimate_low_busd"]),
    ("csp_conflicts", "Minimum spend committed to Amazon, Google and Microsoft (MD&A)", sum(v for k, v in VENDOR_COMMIT.items() if k in ("Amazon", "Google", "Microsoft") and v)),
    ("csp_conflicts", "Amazon convertible notes outstanding (MD&A)", A["amazon_notes_busd"]),
    ("capital_access", "Cash, equivalents and short-term investments at June 30, 2026", liq),
    ("capital_access", "Undrawn convertible-note capacity under the 2026 NPAs", A["npa_capacity_busd"]),
    ("capital_access", "A&R revolving credit facility, undrawn", A["revolver_busd"]),
    ("capital_access", "Minimum liquidity covenant from Q4 2026", A["min_liquidity_covenant_busd"]),
    ("accounting_tax", "Fair value charge on notes, derivatives and SAFEs, H1 2026", A["fv_change_h1_2026_busd"]),
    ("accounting_tax", "Cumulative fair value charges in the accumulated deficit", A["fv_cumulative_busd"]),
    ("ip_litigation", "Bartz settlement (approved July 2026)", A["bartz_settlement_busd"]),
    ("ip_litigation", "Bartz amount still accrued at June 30, 2026", A["bartz_accrued_jun30_busd"]),
    ("talent", "RSUs granted after June 30, 2026, grant-date fair value", A["rsu_grants_post_q_busd"]),
    ("governance", "Donation-matching charge recognized in Q3 2026", A["donation_match_q3_busd"]),
]
anchors = pd.DataFrame(ANCHORS, columns=["theme", "anchor", "busd"])
anchors["x_liquidity"] = (anchors.busd / liq).round(2) if liq else None
pct_rows = pd.DataFrame([("revenue_customers", "Top five customers, share of revenue, nine months to Sep 30, 2026", A["top5_customers_pct"]),
                         ("governance", "Class F voting power after the offering", A["class_f_vote_pct"]),
                         ("governance", "Initial Public Benefit Issuance, share of fully diluted shares", A["public_benefit_issuance_pct"])], columns=["theme", "anchor", "percent"])
display(anchors)
display(pct_rows)
print(f"liquidity at June 30, 2026: ${liq:.1f}B | H1 2026 revenue ${A['revenue_h1_2026_musd']:,.0f}m, operating loss ${-A['operating_loss_h1_2026_musd']:,.0f}m, operating cash flow ${A['op_cf_h1_2026_musd']:,.0f}m, financing cash flow ${A['fin_cf_h1_2026_musd']:,.0f}m")
themes["largest_anchor_x_liquidity"] = anchors.groupby("theme").x_liquidity.max().reindex(themes.index)
""")

md(r"""
## 5. Peer check: which headings also appear in CoreWeave's S-1

CoreWeave's March 2025 S-1 is the nearest listed-company analogue for an AI-infrastructure-heavy IPO and is drafted
in the same genre. Its risk headings are extracted the same way (bold-italic paragraphs inside the Risk Factors
section). For each Anthropic heading, BM25 proposes the ten closest CoreWeave headings and Jev picks the one that
describes the same underlying risk, or "none". A match at probability 0.5 or above marks the Anthropic factor as
shared with the peer. Shared is not the same as unimportant; it is the same as not distinctive. The word share of
each theme that is peer-shared is the third weighting signal.
""")
code(r"""
def all_filings(cik):
    s = json.loads(edgar_get(f"{SEC_BASE}/submissions/CIK{int(cik):010d}.json"))
    frames = [pd.DataFrame(s["filings"]["recent"])]
    for f in s["filings"].get("files", []):
        frames.append(pd.DataFrame(json.loads(edgar_get(f"{SEC_BASE}/submissions/{f['name']}"))))
    return pd.concat(frames, ignore_index=True)


PEER_CIK = "1769628"
peer_filings = all_filings(PEER_CIK)
peer_s1 = peer_filings[peer_filings.form == "S-1"].sort_values("filingDate").iloc[0]
peer_url = f"{SEC_ARCHIVES}/{PEER_CIK}/{peer_s1.accessionNumber.replace('-', '')}/{peer_s1.primaryDocument}"
peer_soup = BeautifulSoup(edgar_get(peer_url), "lxml")
st = lambda t: (t.get("style") or "").replace(" ", "").lower()
paras = []
for p in peer_soup.find_all("p"):
    txt = flat(p.get_text(" "))
    if not txt:
        continue
    inner = " ".join(st(c) for c in p.find_all(True))
    bold = "font-weight:bold" in st(p) or "font-weight:700" in st(p) or p.find("b") is not None or "font-weight:bold" in inner
    ital = "font-style:italic" in st(p) or p.find("i") is not None or "font-style:italic" in inner
    paras.append((txt, bold, ital))
p_start = max(i for i, (t, b, it) in enumerate(paras) if t.startswith("Risks Related to Our Business and Industry") and b and not it)
p_end = next(i for i, (t, b, it) in enumerate(paras) if i > p_start and b and (t.upper().startswith("SPECIAL NOTE") or t.upper().startswith("CAUTIONARY NOTE")))
peer_heads = [t for t, b, it in paras[p_start:p_end] if b and it and len(t) > 40]
print(f"CoreWeave S-1 filed {peer_s1.filingDate}: {len(peer_heads)} risk headings between paragraphs {p_start} and {p_end}")
if not 40 <= len(peer_heads) <= 250:
    flag("peer", f"{len(peer_heads)} CoreWeave headings parsed; outside the expected range, peer check unreliable")

_PT = [tokens(h) for h in peer_heads]
_PDF = Counter(w for t in _PT for w in set(t))
_PAVG = sum(len(t) for t in _PT) / len(_PT)


def peer_bm25(i, q, k1=1.5, b=0.75):
    tf, n = Counter(_PT[i]), len(_PT[i])
    return sum(math.log(1 + (len(_PT) - _PDF[w] + 0.5) / (_PDF[w] + 0.5)) * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * n / _PAVG)) for w in q if w in tf)


def peer_match(row):
    q = tokens(row.heading)
    cands = sorted(range(len(peer_heads)), key=lambda i: -peer_bm25(i, q))[:10]
    crit = {f"c{k}": peer_heads[i] for k, i in enumerate(cands)}
    crit["none"] = "No CoreWeave risk factor in the options describes the same underlying risk as the Anthropic heading"
    r = ask({"anthropic_risk_heading": row.heading, "anthropic_group": flat(row.group), "note": "The options are risk factor headings from CoreWeave's S-1, a GPU cloud provider"},
            {"match": Choice(instructions="Which option describes the same underlying risk as `anthropic_risk_heading`? Two headings match when a reader would say they warn about the same thing happening to the company, even if the wording differs. Choose none if the options only share vocabulary or warn about a different thing.", criteria=crit)},
            section="5 peer match")
    a = r.choices["match"]
    return {"rid": row.Index, "peer_choice": a.choice, "peer_p": round(a.probabilities[a.choice], 2), "peer_conf": round(a.confidence, 2),
            "peer_heading": None if a.choice == "none" else crit[a.choice]}


with ThreadPoolExecutor(6) as pool:
    pm = pd.DataFrame(list(pool.map(peer_match, risks.itertuples()))).set_index("rid")
risks = risks.join(pm)
risks["peer_shared"] = (risks.peer_choice != "none") & (risks.peer_p >= 0.5)
themes["peer_shared_words"] = risks[(risks.theme != "other") & risks.peer_shared].groupby("theme").words.sum().reindex(themes.index).fillna(0).astype(int)
themes["peer_shared_share"] = themes.peer_shared_words / themes.words
print(f"{int(risks.peer_shared.sum())} of {len(risks)} Anthropic risk factors have a CoreWeave counterpart at p >= 0.5 ({risks[risks.peer_shared].words.sum() / risks.words.sum():.0%} of the words)")
display(risks[["theme", "words", "peer_shared", "peer_p", "heading", "peer_heading"]].sort_values("peer_p", ascending=False).head(12))
print("\nthe least peer-like factors (no counterpart, highest specificity):")
display(risks[~risks.peer_shared].sort_values("specificity", ascending=False)[["theme", "page", "words", "specificity", "materialized", "heading"]].head(12))
""")

md(r"""
## 6. Overweighted or underweighted: words against facts

For each theme: the share of risk-factor words (section 3) against the share of evidence passages the rest of the
filing carries (section 4). The ratio of the two is the weighting index. Above 1.5 the theme gets more words than
the document's own facts would suggest; below 0.67 it gets fewer. The peer-shared share and the boilerplate share
say what kind of words they are, and the largest anchor says how big the exposure is in dollars relative to
liquidity. Themes are then ranked within each verdict by the size of the gap.
""")
code(r"""
themes["weight_index"] = (themes.word_share / themes.evidence_share.replace(0, float("nan"))).round(2)


def verdict_from(x):
    if pd.isna(x):
        return "no evidence outside risk factors"
    if x >= 1.5:
        return "overweighted (more words than facts)"
    if x <= 1 / 1.5:
        return "underweighted (more facts than words)"
    return "proportionate"


themes["verdict"] = themes.weight_index.map(verdict_from)
themes["gap"] = (themes.weight_index.map(lambda x: abs(math.log(x)) if x and not pd.isna(x) else float("nan"))).round(2)
view = themes.sort_values(["verdict", "gap"], ascending=[True, False])[["factors", "words", "word_share", "evidence_passages", "evidence_share", "weight_index", "verdict", "specificity", "boilerplate_share", "peer_shared_share", "share_materialized", "consequence", "largest_anchor_x_liquidity", "first_position"]]
display(view.round({"word_share": 3, "evidence_share": 3, "specificity": 2, "boilerplate_share": 2, "peer_shared_share": 2, "share_materialized": 2, "consequence": 2}))

fig, ax = plt.subplots(figsize=(7.5, 5.5))
xs, ys = themes.evidence_share * 100, themes.word_share * 100
col = [PALETTE[1] if v.startswith("over") else PALETTE[2] if v.startswith("under") else PALETTE[0] for v in themes.verdict]
ax.scatter(xs, ys, s=40 + 400 * themes.peer_shared_share.fillna(0), color=col, alpha=0.85, edgecolor="#fcfcfb")
lim = max(xs.max(), ys.max()) * 1.15
ax.plot([0, lim], [0, lim], color="#c3c2b7", linewidth=0.8, linestyle="--")
ax.plot([0, lim], [0, lim * 1.5], color="#e1e0d9", linewidth=0.6, linestyle=":")
ax.plot([0, lim], [0, lim / 1.5], color="#e1e0d9", linewidth=0.6, linestyle=":")
for t, x, y in zip(themes.index, xs, ys):
    ax.annotate(t, (x, y), fontsize=7, color="#52514e", xytext=(4, 3), textcoords="offset points")
ax.set_xlabel("share of evidence passages outside Risk Factors (%)")
ax.set_ylabel("share of Risk Factors words (%)")
ax.set_title("Words vs facts by theme (orange: overweighted, green: underweighted; bubble = peer-shared share)")
ax.set_xlim(0, lim); ax.set_ylim(0, lim)
plt.tight_layout()
plt.show()
""")
code(r"""
# Sensitivity 1: evidence from the operating sections only (Summary, MD&A, Business). The Description of Capital Stock and
# the financial-statement notes document share classes, equity accounting and governance mechanics at length, which
# inflates the evidence count for stock_market, governance and accounting_tax without saying anything about exposure.
OPERATING = ["PROSPECTUS SUMMARY", "MD&A", "BUSINESS"]
hits_op = hits[ev.section.isin(OPERATING)]
themes["evidence_passages_operating"] = hits_op.sum().reindex(themes.index).fillna(0).astype(int)
themes["evidence_share_operating"] = themes.evidence_passages_operating / themes.evidence_passages_operating.sum()
themes["weight_index_operating"] = (themes.word_share / themes.evidence_share_operating.replace(0, float("nan"))).round(2)
themes["verdict_operating"] = themes.weight_index_operating.map(verdict_from)
themes["robust_verdict"] = [a if a == b else "depends on the evidence base" for a, b in zip(themes.verdict, themes.verdict_operating)]
# Sensitivity 2: factor count instead of words
themes["factor_share"] = themes.factors / themes.factors.sum()
themes["weight_index_by_count"] = (themes.factor_share / themes.evidence_share.replace(0, float("nan"))).round(2)
agree = ((themes.weight_index >= 1.5) == (themes.weight_index_by_count >= 1.5)) & ((themes.weight_index <= 1 / 1.5) == (themes.weight_index_by_count <= 1 / 1.5))
print(f"verdict unchanged with operating-section evidence only: {int((themes.verdict == themes.verdict_operating).sum())} of {len(themes)} themes; unchanged when weighting by factor count: {int(agree.sum())} of {len(themes)}")
display(themes[["word_share", "evidence_share", "weight_index", "verdict", "evidence_share_operating", "weight_index_operating", "verdict_operating", "robust_verdict", "weight_index_by_count"]].sort_values("weight_index", ascending=False).round({"word_share": 3, "evidence_share": 3, "evidence_share_operating": 3}))
""")

md(r"""
## 7. The financing structure

The S-1 describes a company financed almost entirely with equity and equity-like paper, with the cash obligations
sitting in compute contracts rather than debt. The Liquidity section of the MD&A is split at its own-line headings
into instrument blocks. For each block, regex pulls the figures from the sentences and tables that state them and
Jev types the instrument: what it is, whether it is drawn, committed or conditional, how it settles, what secures
it, and whether its availability or use is tied to compute. The compute commitments in "Infrastructure Service
Arrangements" are split by agreement and typed the same way (fixed regardless of usage, fees as capacity is
delivered, cancelable how). Balance sheet and cash flow figures come from the statements' own rows.
""")
code(r"""
mda_lines = SECTION_TEXT["MD&A"].split("\n")
own = lambda name: [i for i, l in enumerate(mda_lines) if l.strip() == name]
liq_end = own("Quantitative and Qualitative Disclosures about Market Risk")[-1]
liq_start = max(i for i in own("Liquidity and Capital Resources") if i < liq_end)
SPLIT_HEADS = ["Revolving Credit Agreement", "AMD Agreement", "Convertible Notes", "Outstanding Notes", "Note Purchase Agreements", "Amazon", "Broadcom", "Google",
               "Cash Flows", "Off-Balance Sheet Arrangements", "Contractual Obligations", "Infrastructure Service Arrangements", "Infrastructure Equipment Leases"]
OPENERS = ("The following", "In ", "We ", "Overview", "Since", "As of", "Our ", "Between")
cuts = [(i, mda_lines[i].strip()) for i in range(liq_start, liq_end)
        if mda_lines[i].strip() in SPLIT_HEADS and mda_lines[i + 1].strip().startswith(OPENERS)]
cuts = [(liq_start, "Liquidity and Capital Resources")] + cuts + [(liq_end, None)]
BLOCKS = []
for (i, name), (j, _) in zip(cuts, cuts[1:]):
    body = flat("\n".join(mda_lines[i + 1:j]))
    BLOCKS.append({"block": name, "text": body})
seen = Counter()
for b in BLOCKS:
    seen[b["block"]] += 1
    if seen[b["block"]] > 1:
        b["block"] = f"{b['block']} ({seen[b['block']]})"
B = {b["block"]: b["text"] for b in BLOCKS}
display(pd.DataFrame([{"block": b["block"], "chars": len(b["text"]), "opens": b["text"][:110] + "…"} for b in BLOCKS]))
""")
code(r"""
def fig_candidates(text):
    out = []
    for m in re.finditer(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million)?", text):
        v = float(m.group(1).replace(",", ""))
        unit = m.group(2) or ""
        out.append(f"${m.group(1)}{' ' + unit if unit else ''}")
    return list(dict.fromkeys(out))


INSTRUMENT_TYPE = {"revolver": "A revolving credit facility from banks that can be borrowed, repaid and reborrowed", "convertible_note_outstanding": "Convertible promissory notes already issued and outstanding",
                   "convertible_note_facility": "An agreement under which convertible notes or shares may be issued in the future, nothing issued yet", "equity_purchase_commitment": "A counterparty's commitment to buy the company's shares in the future",
                   "equipment_lease": "A lease of hardware or equipment accounted for as a finance lease", "compute_purchase_commitment": "A commitment to pay a vendor for compute or infrastructure services",
                   "preferred_stock": "Redeemable convertible preferred stock sold to investors", "other": "None of the above"}
STATUS = {"drawn": "Money has been borrowed or notes issued and are outstanding", "committed_undrawn": "The counterparty is committed and the amount is available but nothing has been drawn or issued",
          "conditional": "Availability depends on future milestones, revenue tests, deliveries or other conditions that have not been met", "not_applicable": "The concept of drawn or undrawn does not apply to this arrangement"}
SETTLEMENT = {"cash": "Repaid or paid in cash", "shares": "Settled by issuing shares of the company's stock", "cash_or_shares": "May be settled in cash or in shares depending on an election or a cap",
              "services": "Paid as rent or fees for equipment or services received", "not_stated": "The text does not say how it is settled"}
SECURITY = {"all_assets": "Secured by substantially all of the company's assets", "specific_collateral": "Secured by specific equipment or collateral, or on a junior basis by it",
            "unsecured_or_not_stated": "Unsecured, or the text does not mention security"}
COUNTERPARTIES = ["Amazon", "Google", "Microsoft", "Broadcom", "AMD", "NVIDIA", "SpaceXAI", "Nscale", "Lambda", "Morgan Stanley", "banks (syndicate)", "multiple", "none named"]

INSTRUMENTS = [
    {"name": "A&R senior secured revolving credit facility", "block": "Revolving Credit Agreement", "size": r"\$(\d+) billion senior secured revolving credit facility with the full amount", "unit": "B",
     "extra": {"maturity": (r"mature on ([A-Z][a-z]+ \d{1,2}, \d{4})", True), "min_liquidity_busd": (r"of at least \$([\d.]+) billion as of the last day of each fiscal quarter", False), "springing_maturity_trigger_musd": (r"more than \$(\d+) million in aggregate scheduled cash principal", False),
               "letters_of_credit_musd": (r"\$(\d+) million of standby letters of credit", False), "prior_facility_busd": (r"increase the aggregate revolving commitments to \$([\d.]+) billion \(the Initial", False)}},
    {"name": "AMD Class N purchase commitment", "block": "AMD Agreement", "size": r"purchase up to \$([\d.]+) billion of our Class N", "unit": "B", "extra": {"first_milestone": (r"first of such milestones to be achieved in (\d{4})", True)}},
    {"name": "Amazon rollover convertible notes (2023 and 2024 NPAs)", "block": "Outstanding Notes", "size": r"Total \$ ([\d,]+) [\d,]+", "unit": "M",
     "extra": {"note_2023_musd": (r"Amazon 2023 NPA \(3\) \$ ([\d,]+) \$", False), "note_2023_conversion_price": (r"Amazon 2023 NPA \(3\) \$ [\d,]+ \$ ([\d.]+)", False), "note_2024_musd": (r"Amazon 2024 NPA \(4\) ([\d,]+) \$", False),
               "note_2024_conversion_price": (r"Amazon 2024 NPA \(4\) [\d,]+ \$ ([\d.]+)", False), "ownership_cap_pct": (r"more than (\d+)% of our capitalization", False)}},
    {"name": "Amazon 2026 NPA (convertible note / share facility)", "block": "Amazon", "size": r"\$([\d.]+) billion \$[\d.]+ billion", "unit": "B", "extra": {"increment_busd": (r"in \$([\d.]+) billion increments following the achievement", False), "draw_window_months": (r"(\d+) months after this offering", False)}},
    {"name": "Broadcom Infrastructure Partner 2026 NPA", "block": "Broadcom", "size": r"\$([\d.]+) billion \$[\d.]+ billion", "unit": "B",
     "extra": {"pik_rate_pct": (r"(\d+\.\d+)% per annum", False), "penalty_rate_pct": (r"bear interest at (\d+\.\d+)% per annum and convert", False), "conversion_discount_pct": (r"conversion price equal to (\d+)% of the 30-day", False),
               "penalty_conversion_pct": (r"convert at (\d+)%, rather than", False), "change_of_control_pct": (r"cash equal to (\d+)% of the then-outstanding", False)}},
    {"name": "Google 2026 NPA (convertible note / share facility)", "block": "Google", "size": r"\$([\d.]+) billion \$[\d.]+ billion", "unit": "B",
     "extra": {"ownership_cap_pct": (r"exceed (\d+\.\d+)% of our outstanding capitalization", False), "concurrent_private_placement_busd": (r"option to purchase up to \$([\d.]+) billion of our Class N", False), "draw_window_ends": (r"can be made through ([A-Z][a-z]+ \d{1,2}, \d{4})", True)}},
    {"name": "Broadcom master equipment leases (finance leases)", "block": "Infrastructure Equipment Leases", "size": r"aggregate of approximately \$([\d.]+) billion excluding interest", "unit": "B", "extra": {"term": (r"(five-year) master equipment leases", True)}},
]


def type_instrument(ins):
    textb = B.get(ins["block"], "")
    if not textb:
        flag(f"instrument:{ins['name']}", f"block {ins['block']} not found")
    rec = {"instrument": ins["name"], "block": ins["block"], "amount": None, "amount_unit": ins["unit"]}
    m = re.search(ins["size"], textb)
    rec["amount"] = float(m.group(1).replace(",", "")) if m else None
    rec["amount_busd"] = rec["amount"] / (1000 if ins["unit"] == "M" else 1) if rec["amount"] is not None else None
    if rec["amount"] is None:
        flag(f"instrument:{ins['name']}", "size regex found nothing in its block")
    for k, (pat, as_text) in ins.get("extra", {}).items():
        v = grab(pat, textb, as_text=as_text)
        rec[k] = v
        if v is None:
            flag(f"instrument:{ins['name']}", f"{k} not found")
    r = ask({"instrument": ins["name"], "text": textb[:9000]},
            {"type": Choice(instructions="What kind of financing arrangement does `text` describe for `instrument`?", criteria=INSTRUMENT_TYPE),
             "status": Choice(instructions="As of the date of the text, is the arrangement drawn, committed but undrawn, or conditional?", criteria=STATUS),
             "settlement": Choice(instructions="How are amounts under the arrangement settled or repaid, according to `text`?", criteria=SETTLEMENT),
             "security": Choice(instructions="What secures the company's obligations under the arrangement, according to `text`?", criteria=SECURITY),
             "counterparty": Choice(instructions="Who is the counterparty to `instrument` in `text`?", criteria={c: c for c in COUNTERPARTIES}),
             "compute_linked": Noul(instructions="Is the availability, use or repayment of this arrangement tied to compute: delivery or deployment milestones for chips, rent on compute equipment, compute capacity agreements, or data center build-out?",
                                    criteria=NoulCriteria(true="The text ties the arrangement to compute delivery, compute equipment or compute agreements", false="The arrangement is general-purpose or the text does not tie it to compute")),
             "conditional": Noul(instructions="Does drawing or issuing under the arrangement depend on conditions such as revenue tests, milestones, covenant compliance or counterparty elections?",
                                 criteria=NoulCriteria(true="The text names conditions that must hold before amounts become available", false="No such conditions are described")),
             "converts_to_equity": Noul(instructions="Can the arrangement result in the issuance of the company's shares (conversion, share settlement or share purchase)?",
                                        criteria=NoulCriteria(true="The text describes conversion into or settlement in shares, or a share purchase", false="The text describes no path to share issuance"))},
            section="7 instruments")
    for k in ("type", "status", "settlement", "security", "counterparty"):
        rec[k] = r.choices[k].choice
        rec[k + "_conf"] = round(r.choices[k].confidence, 2)
    for k in ("compute_linked", "conditional", "converts_to_equity"):
        rec[k] = round(r.nouls[k].noul, 2)
    return rec


with ThreadPoolExecutor(6) as pool:
    fin = pd.DataFrame(list(pool.map(type_instrument, INSTRUMENTS)))
display(fin[["instrument", "amount_busd", "type", "status", "settlement", "security", "counterparty", "compute_linked", "conditional", "converts_to_equity"]])
extra_cols = [c for c in fin.columns if c not in {"instrument", "block", "amount", "amount_unit", "amount_busd", "type", "status", "settlement", "security", "counterparty", "compute_linked", "conditional", "converts_to_equity"} and not c.endswith("_conf")]
display(fin.set_index("instrument")[extra_cols].T.dropna(how="all"))
""")
code(r"""
# --- compute commitments by agreement, from the "Infrastructure Service Arrangements" block
isa = B["Infrastructure Service Arrangements"]
paras_isa = [p.strip() for p in re.split(r"(?=(?:In [A-Z][a-z]+(?:, [A-Z][a-z]+)*(?: and [A-Z][a-z]+)? 20\d\d\s*,\s*we entered|Between [A-Z][a-z]+ and [A-Z][a-z]+ 20\d\d\s*,\s*we entered|Under the Hardware Supply Agreement with AMD))", isa) if len(p.strip()) > 200]
VENDORS = ["Microsoft", "Google", "Amazon", "SpaceXAI", "AMD", "Nscale", "Lambda"]
BASIS = {"fixed_minimum": "A fixed or minimum dollar amount is payable regardless of actual usage, with any shortfall trued up", "fees_as_delivered": "Fees accrue only as capacity is delivered to and accepted by the company",
         "no_fixed_amount": "The agreement specifies no fixed dollar commitment; the amount is an estimate of expected spend", "mixed": "Part of the amount is fixed and part depends on delivery or usage"}
CANCEL = {"non_cancelable_breach_only": "Non-cancelable except for the vendor's uncured material breach (or per undelivered tranche)", "cancelable_on_notice": "Either party may cancel on notice after an initial non-cancelable period",
          "cancelable_if_financing_or_lease_fails": "Terminable if the vendor fails to secure financing, a facility lease or a delivery milestone", "not_stated": "The text does not say"}


def type_commitment(p):
    vendor = next((v for v in VENDORS if v in p), "unknown")
    cands = fig_candidates(p)
    crit = {f"f{i}": c for i, c in enumerate(cands)} | {"none": "No figure in the text is the aggregate commitment amount"}
    r = ask({"agreement_text": p, "vendor": vendor},
            {"amount": Choice(instructions="Which figure is the aggregate dollar amount the company committed or expects to spend under this agreement over its term (not a monthly rate and not a sub-component)?", criteria=crit),
             "basis": Choice(instructions="On what basis is the amount payable, according to `agreement_text`?", criteria=BASIS),
             "cancel": Choice(instructions="How can the company get out of the commitment, according to `agreement_text`?", criteria=CANCEL),
             "true_up": Noul(instructions="Does `agreement_text` say the company must pay the difference if its actual spend falls short?", criteria=NoulCriteria(true="A shortfall true-up payment is described", false="No true-up is described")),
             "vendor_financing_dependency": Noul(instructions="Does `agreement_text` make the arrangement depend on the vendor obtaining financing, a facility lease, or delivering capacity on a schedule?",
                                                 criteria=NoulCriteria(true="The vendor must secure financing, a lease or deliveries for the arrangement to proceed", false="No such vendor-side dependency is described"))},
            section="7 commitments")
    a = r.choices["amount"]
    amt = None if a.choice == "none" else crit[a.choice]
    return {"vendor": vendor, "amount_text": amt, "amount_busd": float(re.sub(r"[^\d.]", "", amt)) if amt and "billion" in amt else None, "amount_p": round(a.probabilities[a.choice], 2),
            "basis": r.choices["basis"].choice, "basis_conf": round(r.choices["basis"].confidence, 2), "cancelability": r.choices["cancel"].choice, "cancel_conf": round(r.choices["cancel"].confidence, 2),
            "true_up": round(r.nouls["true_up"].noul, 2), "vendor_dependency": round(r.nouls["vendor_financing_dependency"].noul, 2), "figures_in_text": ", ".join(cands), "regex_amount_busd": VENDOR_COMMIT.get(vendor), "text": p[:300] + "…"}


with ThreadPoolExecutor(6) as pool:
    commits = pd.DataFrame(list(pool.map(type_commitment, paras_isa)))
commits["jev_vs_regex_agree"] = (commits.amount_busd == commits.regex_amount_busd)
for r in commits[~commits.jev_vs_regex_agree].itertuples():
    flag(f"commitment:{r.vendor}", f"Jev picked {r.amount_text} where the regex read {r.regex_amount_busd}; regex value kept in the chart")
display(commits[["vendor", "amount_text", "amount_p", "regex_amount_busd", "jev_vs_regex_agree", "basis", "basis_conf", "cancelability", "true_up", "vendor_dependency"]])
print(f"agreements parsed: {len(commits)}; sum of regex amounts ${sum(v for v in VENDOR_COMMIT.values() if v):.1f}B (not additive with the Note 13 total: different dates, and estimates are included)")
""")
code(r"""
# --- preferred stock rounds from the related-person section, balance sheet rows from the statements
pref = []
for m in re.finditer(r"From ([A-Z][a-z]+ \d{4}) to ([A-Z][a-z]+ \d{4}), we sold an aggregate of ([\d,]+) shares of our Series ([A-H])(?:-1|-1 and [A-Z]-\d)?[^.]*?at a purchase price of \$([\d.]+) per share, for an aggregate purchase price of\s*\$([\d,\s]+?)\s*\.", REL):
    pref.append({"series": m.group(4), "from": m.group(1), "to": m.group(2), "shares": int(m.group(3).replace(",", "")), "price_per_share": float(m.group(5)), "gross_busd": round(int(re.sub(r"[\s,]", "", m.group(6))) / 1e9, 2)})
pref = pd.DataFrame(pref)
display(pref)
bs = {"cash_musd": (row_values(FS, "Cash and cash equivalents", 3, after=r"\s*\$") or [None] * 3)[2], "sti_musd": (row_values(FS, "Short-term investments", 3) or [None] * 3)[2],
      "restricted_cash_musd": (row_values(FS, "Restricted cash", 3) or [None] * 3)[2], "convertible_notes_payable_musd": A["convertible_notes_carrying_musd"],
      "finance_lease_liabilities_musd": (row_values(FS, "Total finance lease liabilities", 1, after=r"\s*\$") or [None])[0],
      "redeemable_preferred_musd": grab(r"Redeemable convertible preferred stock \$ ([\d,]+)", PS), "accumulated_deficit_musd": grab(r"Accumulated deficit \$ \(([\d,]+)\)", PS),
      "total_liabilities_musd": grab(r"Total liabilities \$ ([\d,]+)", PS), "total_assets_musd": grab(r"Total assets \$ ([\d,]+)", PS)}
display(pd.Series(bs, name="June 30, 2026 ($m)").to_frame())
print(f"preferred rounds C through H raised ${pref.gross_busd.sum():.1f}B gross; Series H alone ${pref[pref.series == 'H'].gross_busd.sum():.1f}B; convertible notes carried at fair value ${bs['convertible_notes_payable_musd']/1000:.1f}B against ${A['amazon_notes_busd']}B of principal")
""")
code(r"""
# --- capital sources against committed spend, in billions; every bar is a figure the filing states, nothing is netted
src = [("Cash + short-term investments (6/30/26)", liq, PALETTE[0]), ("A&R revolver, undrawn", fin.set_index("instrument").loc["A&R senior secured revolving credit facility", "amount_busd"], PALETTE[0]),
       ("Google 2026 NPA", fin.set_index("instrument").loc["Google 2026 NPA (convertible note / share facility)", "amount_busd"], PALETTE[6]), ("Amazon 2026 NPA", fin.set_index("instrument").loc["Amazon 2026 NPA (convertible note / share facility)", "amount_busd"], PALETTE[6]),
       ("Broadcom NPA (rent financing only)", fin.set_index("instrument").loc["Broadcom Infrastructure Partner 2026 NPA", "amount_busd"], PALETTE[6]), ("AMD Class N commitment", fin.set_index("instrument").loc["AMD Class N purchase commitment", "amount_busd"], PALETTE[3])]
use = [("Minimum purchase commitments (6/30/26, Note 13)", A["min_commitments_jun30_busd"], PALETTE[1]), ("Added after 6/30 (Note 17)", A["post_quarter_commitments_busd"], PALETTE[1]),
       ("Short-term, added after 6/30", A["post_quarter_short_term_busd"], PALETTE[1]), ("Broadcom lease rent ex-interest (Note 7 leases)", A["broadcom_rent_busd"], PALETTE[4]),
       ("TPU estimate, low end (not in table)", A["tpu_estimate_low_busd"], PALETTE[7])]
fig, ax = plt.subplots(figsize=(8.5, 3.4))
for label, items in (("sources", src), ("committed spend", use)):
    left = 0
    for name, v, c in items:
        if v:
            ax.barh(label, v, left=left, color=c, edgecolor="#fcfcfb")
            if v > 25:
                ax.text(left + v / 2, label, f"{name}\n${v:,.0f}B", ha="center", va="center", fontsize=6.5, color="white")
            left += v
ax.set_xlabel("$ billions as stated in the S-1 (bars are not netted; categories come from different notes and may overlap)")
ax.set_title("Capital sources available against compute spend committed")
plt.tight_layout()
plt.show()
tot_src = sum(v for _, v, _ in src if v); tot_use = sum(v for _, v, _ in use if v)
print(f"sources shown ${tot_src:,.0f}B (of which ${liq:,.0f}B is cash and ${sum(v for n, v, _ in src if 'NPA' in n or 'AMD' in n):,.0f}B is contingent share-settled capacity); committed spend shown ${tot_use:,.0f}B")
""")

md(r"""
### Counterparty roles

Every passage in the filing that names one of nine counterparties, up to 30 per name ranked by how often the name
appears, goes to Jev with seven Nouls: does the passage establish that the counterparty is an investor or
noteholder, a financing source or guarantor, a compute or hardware supplier, a lessor, a customer, a distribution
channel, or a competitor. A role counts when any passage reaches 0.8; the number of supporting passages is the
depth of the record. This is the factual basis for the conflict-of-interest theme.
""")
code(r"""
ROLE_Q = {
    "investor": "holds Anthropic's preferred stock, common stock or convertible notes, or has invested money in Anthropic",
    "financing_source": "provides or commits to provide financing to Anthropic: a note purchase facility, a share purchase commitment, a credit facility, a guarantee of lease obligations",
    "supplier": "supplies Anthropic with compute, chips, cloud capacity, hardware or data center services",
    "lessor": "leases equipment or facilities to Anthropic",
    "customer": "buys or uses Anthropic's models, platform or applications",
    "distribution_channel": "makes Anthropic's models available to customers through its own cloud platform or marketplace, such as Amazon Bedrock, Google Cloud Vertex AI or Microsoft Foundry",
    "competitor": "develops or offers AI models or services that compete with Anthropic's",
}
NAMES = ["Amazon", "Google", "Microsoft", "Broadcom", "AMD", "NVIDIA", "SpaceXAI", "Nscale", "Lambda"]
ROLE_SECTIONS = [s for s in sec_summary.index if s not in ("UNDERWRITING", "TAX", "PART II", "EXECUTIVE COMPENSATION", "MANAGEMENT", "COVER")]
role_jobs = []
for name in NAMES:
    cand = [p for p in PASSAGES if p["section"] in ROLE_SECTIONS and re.search(r"\b" + re.escape(name) + r"\b", p["text"])]
    cand.sort(key=lambda p: -len(re.findall(r"\b" + re.escape(name) + r"\b", p["text"])))
    role_jobs += [(name, p) for p in cand[:60]]
print(f"{len(role_jobs)} (counterparty, passage) pairs")


def judge_role(job):
    name, p = job
    r = ask({"counterparty": name, "passage": p["text"], "section": p["section"]},
            {k: Noul(instructions=f"Does `passage` state that `counterparty` {desc}?", criteria=NoulCriteria(true=f"The passage says {name} {desc}", false="The passage does not establish this role for the counterparty"))
             for k, desc in ROLE_Q.items()}, section="7 roles")
    return {"counterparty": name, "pid": p["pid"], "section": p["section"], "page": p["page"], **{k: round(r.nouls[k].noul, 2) for k in ROLE_Q}, "text": p["text"][:240]}


with ThreadPoolExecutor(6) as pool:
    roles_raw = pd.DataFrame(list(pool.map(judge_role, role_jobs)))
ROLE_T = 0.8
roles = pd.DataFrame({k: roles_raw.groupby("counterparty")[k].apply(lambda s: int((s >= ROLE_T).sum())) for k in ROLE_Q}).reindex(NAMES)
roles["roles_established"] = (roles[list(ROLE_Q)] > 0).sum(axis=1)
roles["passages_read"] = roles_raw.groupby("counterparty").size().reindex(NAMES)
display(roles)
fig, ax = plt.subplots(figsize=(7, 3.8))
mat = roles[list(ROLE_Q)].values
ax.imshow(mat > 0, cmap="Blues", aspect="auto", vmin=0, vmax=1.6)
ax.set_xticks(range(len(ROLE_Q))); ax.set_xticklabels(list(ROLE_Q), rotation=30, ha="right", fontsize=8)
ax.set_yticks(range(len(NAMES))); ax.set_yticklabels(NAMES, fontsize=8)
ax.grid(False)
for i in range(mat.shape[0]):
    for j in range(mat.shape[1]):
        if mat[i, j]:
            ax.text(j, i, str(mat[i, j]), ha="center", va="center", fontsize=7, color="white")
ax.set_title(f"Roles each counterparty holds toward Anthropic (cells: passages at Noul >= {ROLE_T})")
plt.tight_layout()
plt.show()
best_quotes = roles_raw.melt(id_vars=["counterparty", "section", "page", "text"], value_vars=list(ROLE_Q), var_name="role", value_name="p")
best_quotes = best_quotes[best_quotes.p >= ROLE_T].sort_values("p", ascending=False).drop_duplicates(["counterparty", "role"])
display(best_quotes.sort_values(["counterparty", "role"])[["counterparty", "role", "p", "section", "page", "text"]].reset_index(drop=True))
""")

md(r"""
## 8. Run metrics, generated summary, review flags, and manual checks
""")
code(r"""
log_df = pd.DataFrame(LOG)
summary = log_df.groupby("section").agg(calls=("latency_ms", "size"), questions=("questions", "sum"), median_ms=("latency_ms", "median"),
                                        p95_ms=("latency_ms", lambda s: s.quantile(0.95)), input_tokens=("input_tokens", "sum"), cost_usd=("cost_usd", "sum"))
summary.loc["TOTAL"] = [len(log_df), log_df.questions.sum(), log_df.latency_ms.median(), log_df.latency_ms.quantile(0.95), log_df.input_tokens.sum(), log_df.cost_usd.sum()]
display(summary.round({"median_ms": 0, "p95_ms": 0, "cost_usd": 4}))

F = fin.set_index("instrument")
MANUAL_CHECKS = [
    {"item": "risk factors extracted", "expected": "88 headings in 6 groups", "got": f"{len(risks)} in {risks.group.nunique()}", "source": "S-1 Risk Factors, pp. 26-119", "agrees": len(risks) == 88 and risks.group.nunique() == 6},
    {"item": "first risk factor", "expected": "develop the most advanced and capable AI models", "got": risks.iloc[0].heading[:70], "source": "p. 26", "agrees": "most advanced and capable AI models" in risks.iloc[0].heading},
    {"item": "cash and short-term investments", "expected": "$112.4B + $19.3B", "got": f"${A['cash_busd']}B + ${A['sti_busd']}B", "source": "MD&A Liquidity", "agrees": (A["cash_busd"], A["sti_busd"]) == (112.4, 19.3)},
    {"item": "A&R revolver", "expected": "$15B, matures September 4, 2031, $5.0B minimum liquidity, $500M springing trigger", "got": f"${F.loc['A&R senior secured revolving credit facility', 'amount_busd']:.0f}B, {F.loc['A&R senior secured revolving credit facility', 'maturity']}, ${F.loc['A&R senior secured revolving credit facility', 'min_liquidity_busd']}B, ${F.loc['A&R senior secured revolving credit facility', 'springing_maturity_trigger_musd']:.0f}M", "source": "MD&A Revolving Credit Agreement",
     "agrees": (F.loc["A&R senior secured revolving credit facility", "amount_busd"], F.loc["A&R senior secured revolving credit facility", "maturity"], F.loc["A&R senior secured revolving credit facility", "min_liquidity_busd"], F.loc["A&R senior secured revolving credit facility", "springing_maturity_trigger_musd"]) == (15.0, "September 4, 2031", 5.0, 500.0)},
    {"item": "letters of credit at June 30", "expected": "$78M", "got": f"${F.loc['A&R senior secured revolving credit facility', 'letters_of_credit_musd']:.0f}M", "source": "MD&A", "agrees": F.loc["A&R senior secured revolving credit facility", "letters_of_credit_musd"] == 78},
    {"item": "Amazon notes outstanding", "expected": "$6,203M = $2,186M at $2.0928 + $4,017M at $5.0478; 12% cap", "got": f"${F.loc['Amazon rollover convertible notes (2023 and 2024 NPAs)', 'amount']:,.0f}M = {F.loc['Amazon rollover convertible notes (2023 and 2024 NPAs)', 'note_2023_musd']:,.0f} at {F.loc['Amazon rollover convertible notes (2023 and 2024 NPAs)', 'note_2023_conversion_price']} + {F.loc['Amazon rollover convertible notes (2023 and 2024 NPAs)', 'note_2024_musd']:,.0f} at {F.loc['Amazon rollover convertible notes (2023 and 2024 NPAs)', 'note_2024_conversion_price']}; {F.loc['Amazon rollover convertible notes (2023 and 2024 NPAs)', 'ownership_cap_pct']:.0f}%", "source": "MD&A Outstanding Notes table",
     "agrees": (F.loc["Amazon rollover convertible notes (2023 and 2024 NPAs)", "amount"], F.loc["Amazon rollover convertible notes (2023 and 2024 NPAs)", "note_2023_musd"], F.loc["Amazon rollover convertible notes (2023 and 2024 NPAs)", "note_2024_musd"], F.loc["Amazon rollover convertible notes (2023 and 2024 NPAs)", "ownership_cap_pct"]) == (6203.0, 2186.0, 4017.0, 12.0)},
    {"item": "NPA capacity", "expected": "$77B = Google $20B + Amazon $15B + Broadcom $42B", "got": f"${A['npa_capacity_busd']:.0f}B = {F.loc['Google 2026 NPA (convertible note / share facility)', 'amount_busd']:.0f} + {F.loc['Amazon 2026 NPA (convertible note / share facility)', 'amount_busd']:.0f} + {F.loc['Broadcom Infrastructure Partner 2026 NPA', 'amount_busd']:.0f}", "source": "MD&A Note Purchase Agreements table",
     "agrees": (A["npa_capacity_busd"], F.loc["Google 2026 NPA (convertible note / share facility)", "amount_busd"], F.loc["Amazon 2026 NPA (convertible note / share facility)", "amount_busd"], F.loc["Broadcom Infrastructure Partner 2026 NPA", "amount_busd"]) == (77.0, 20.0, 15.0, 42.0)},
    {"item": "Broadcom NPA terms", "expected": "9.00% PIK; 13.00% and 85% if revenue conditions fail; converts at 90% of VWAP; 150% on change of control", "got": f"{F.loc['Broadcom Infrastructure Partner 2026 NPA', 'pik_rate_pct']}%; {F.loc['Broadcom Infrastructure Partner 2026 NPA', 'penalty_rate_pct']}% and {F.loc['Broadcom Infrastructure Partner 2026 NPA', 'penalty_conversion_pct']:.0f}%; {F.loc['Broadcom Infrastructure Partner 2026 NPA', 'conversion_discount_pct']:.0f}%; {F.loc['Broadcom Infrastructure Partner 2026 NPA', 'change_of_control_pct']:.0f}%", "source": "MD&A Broadcom",
     "agrees": (F.loc["Broadcom Infrastructure Partner 2026 NPA", "pik_rate_pct"], F.loc["Broadcom Infrastructure Partner 2026 NPA", "penalty_rate_pct"], F.loc["Broadcom Infrastructure Partner 2026 NPA", "penalty_conversion_pct"], F.loc["Broadcom Infrastructure Partner 2026 NPA", "conversion_discount_pct"], F.loc["Broadcom Infrastructure Partner 2026 NPA", "change_of_control_pct"]) == (9.0, 13.0, 85.0, 90.0, 150.0)},
    {"item": "Google cap and concurrent placement", "expected": "14.99% cap; $10.0B option at the IPO price", "got": f"{F.loc['Google 2026 NPA (convertible note / share facility)', 'ownership_cap_pct']}%; ${F.loc['Google 2026 NPA (convertible note / share facility)', 'concurrent_private_placement_busd']}B", "source": "MD&A Google", "agrees": (F.loc["Google 2026 NPA (convertible note / share facility)", "ownership_cap_pct"], F.loc["Google 2026 NPA (convertible note / share facility)", "concurrent_private_placement_busd"]) == (14.99, 10.0)},
    {"item": "AMD commitment", "expected": "$5.0B of Class N, first milestone 2027", "got": f"${F.loc['AMD Class N purchase commitment', 'amount_busd']}B, {F.loc['AMD Class N purchase commitment', 'first_milestone']}", "source": "MD&A AMD Agreement", "agrees": (F.loc["AMD Class N purchase commitment", "amount_busd"], F.loc["AMD Class N purchase commitment", "first_milestone"]) == (5.0, "2027")},
    {"item": "purchase commitments", "expected": "$265.6B at June 30, 2026; $54,559M table at Dec 31, 2025; ~$245B + ~$21B added after June 30; ~$417B added after Dec 31, 2025", "got": f"${A['min_commitments_jun30_busd']}B; ${A['commitments_dec31_table_busd']:,.0f}M; ${A['post_quarter_commitments_busd']:.0f}B + ${A['post_quarter_short_term_busd']:.0f}B; ${A['post_dec31_commitments_busd']:.0f}B", "source": "Notes 13 and 17; FY2025 subsequent events", "agrees": (A["min_commitments_jun30_busd"], A["commitments_dec31_table_busd"], A["post_quarter_commitments_busd"], A["post_quarter_short_term_busd"], A["post_dec31_commitments_busd"]) == (265.6, 54559.0, 245.0, 21.0, 417.0)},
    {"item": "Broadcom lease rent", "expected": "$161.2B all leases; $125.2B for the 2026 Lease Arrangement", "got": f"${A['broadcom_rent_busd']}B; ${A['lease_2026_rent_busd']}B", "source": "MD&A Infrastructure Equipment Leases; Risk Factors", "agrees": (A["broadcom_rent_busd"], A["lease_2026_rent_busd"]) == (161.2, 125.2)},
    {"item": "vendor commitments", "expected": "Microsoft 44.9, Google 114.5, Amazon 110.0, SpaceXAI 120.5, Nscale 44.6, Lambda 41.3, AMD >20.0", "got": ", ".join(f"{k} {v}" for k, v in VENDOR_COMMIT.items()), "source": "MD&A Infrastructure Service Arrangements", "agrees": VENDOR_COMMIT == {"Microsoft": 44.9, "Google": 114.5, "Amazon": 110.0, "SpaceXAI": 120.5, "Nscale": 44.6, "Lambda": 41.3, "AMD": 20.0}},
    {"item": "TPU estimate", "expected": "$125.0B to $150.0B, not in the table", "got": f"${A['tpu_estimate_low_busd']}B to ${A['tpu_estimate_high_busd']}B", "source": "MD&A", "agrees": (A["tpu_estimate_low_busd"], A["tpu_estimate_high_busd"]) == (125.0, 150.0)},
    {"item": "balance sheet", "expected": "convertible notes payable $108,566M; preferred $157,510M; accumulated deficit $132,902M; finance lease liabilities $443M; restricted cash $2,529M", "got": f"${bs['convertible_notes_payable_musd']:,.0f}M; ${bs['redeemable_preferred_musd']:,.0f}M; ${bs['accumulated_deficit_musd']:,.0f}M; ${bs['finance_lease_liabilities_musd']:,.0f}M; ${bs['restricted_cash_musd']:,.0f}M", "source": "F-5 and summary balance sheet data",
     "agrees": (bs["convertible_notes_payable_musd"], bs["redeemable_preferred_musd"], bs["accumulated_deficit_musd"], bs["finance_lease_liabilities_musd"], bs["restricted_cash_musd"]) == (108566.0, 157510.0, 132902.0, 443.0, 2529.0)},
    {"item": "fair value charges", "expected": "$72.4B in H1 2026; $113.2B cumulative of a $132.9B deficit", "got": f"${A['fv_change_h1_2026_busd']}B; ${A['fv_cumulative_busd']}B of ${A['accumulated_deficit_busd']}B", "source": "MD&A Liquidity", "agrees": (A["fv_change_h1_2026_busd"], A["fv_cumulative_busd"], A["accumulated_deficit_busd"]) == (72.4, 113.2, 132.9)},
    {"item": "H1 2026 results and cash flows", "expected": "revenue $16,286M; operating loss $(693)M; operating cash flow $3,929M; financing $110,774M", "got": f"${A['revenue_h1_2026_musd']:,.0f}M; ${A['operating_loss_h1_2026_musd']:,.0f}M; ${A['op_cf_h1_2026_musd']:,.0f}M; ${A['fin_cf_h1_2026_musd']:,.0f}M", "source": "Summary data; MD&A Cash Flows", "agrees": (A["revenue_h1_2026_musd"], A["operating_loss_h1_2026_musd"], A["op_cf_h1_2026_musd"], A["fin_cf_h1_2026_musd"]) == (16286.0, -693.0, 3929.0, 110774.0)},
    {"item": "preferred rounds", "expected": "H $45.73B, G $23.45B, F $13.00B, E $3.57B, D $1.20B, C $0.45B", "got": ", ".join(f"{r.series} ${r.gross_busd}B" for r in pref.itertuples()), "source": "Related Person Transactions", "agrees": dict(zip(pref.series, pref.gross_busd)) == {"H": 45.73, "G": 23.45, "F": 13.0, "E": 3.57, "D": 1.2, "C": 0.45}},
    {"item": "Bartz", "expected": "$1.5B settlement; $1.2B accrued at June 30, 2026", "got": f"${A['bartz_settlement_busd']}B; ${A['bartz_accrued_jun30_busd']}B", "source": "Note 13", "agrees": (A["bartz_settlement_busd"], A["bartz_accrued_jun30_busd"]) == (1.5, 1.2)},
    {"item": "concentration and control", "expected": "top five customers 25%; Class F 50.1% of votes; public benefit issuance 5%", "got": f"{A['top5_customers_pct']:.0f}%; {A['class_f_vote_pct']}%; {A['public_benefit_issuance_pct']:.0f}%", "source": "Risk Factors; Governance; MD&A", "agrees": (A["top5_customers_pct"], A["class_f_vote_pct"], A["public_benefit_issuance_pct"]) == (25.0, 50.1, 5.0)},
    {"item": "Amazon roles", "expected": "investor, financing source, supplier, customer or channel, competitor all established", "got": ", ".join(k for k in ROLE_Q if roles.loc["Amazon", k] > 0), "source": "passages naming Amazon", "agrees": all(roles.loc["Amazon", k] > 0 for k in ("investor", "financing_source", "supplier", "competitor"))},
]
manual = pd.DataFrame(MANUAL_CHECKS)
flags_df = pd.DataFrame(REVIEW_FLAGS) if REVIEW_FLAGS else pd.DataFrame(columns=["item", "reason"])
print("review flags:")
display(flags_df)
print("\nmanual checks (author-read against the quoted source; the 'got' column is this run's output):")
display(manual)

risks.drop(columns=["body"]).to_csv("anthropic_s1_risk_factors.csv")
themes.to_csv("anthropic_s1_risk_themes.csv")
top_ev.to_csv("anthropic_s1_theme_evidence_passages.csv", index=False)
anchors.to_csv("anthropic_s1_exposure_anchors.csv", index=False)
risks[["theme", "words", "peer_shared", "peer_p", "heading", "peer_heading"]].to_csv("anthropic_s1_peer_matches.csv")
fin.to_csv("anthropic_s1_financing.csv", index=False)
commits.to_csv("anthropic_s1_vendor_commitments.csv", index=False)
roles.to_csv("anthropic_s1_counterparty_roles.csv")
manual.to_csv("anthropic_s1_manual_checks.csv", index=False)

over = themes[themes.verdict.str.startswith("over")].sort_values("gap", ascending=False)
under = themes[themes.verdict.str.startswith("under")].sort_values("gap", ascending=False)
prop = themes[themes.verdict == "proportionate"].sort_values("words", ascending=False)
mat_share = risks[risks.materialized >= 0.5].words.sum() / risks.words.sum()
generated = f'''
### Generated summary of this run

* **Inputs:** S-1 filed {s1.filingDate}, {len(text):,} characters over {len(pages)} pages; {len(risks)} risk factors ({risks.words.sum():,} words, {coverage:.0%} of the Risk Factors page range) in {risks.group.nunique()} groups; {len(ev_pass)} evidence passages from {len(EVIDENCE_SECTIONS)} other sections; {len(peer_heads)} CoreWeave S-1 headings.
* **Jev:** {len(log_df)} requests, {int(log_df.questions.sum()):,} judgments, ${log_df.cost_usd.sum():.4f}; median latency {log_df.latency_ms.median():.0f} ms. Theme stable across two passes on {int(risks.theme_stable.sum())} of {len(risks)} factors.
* **Where the words go:** {", ".join(f"{t} {themes.loc[t, 'word_share']:.0%}" for t in themes.sort_values("words", ascending=False).index[:5])}. Factors describing something that has already happened carry {mat_share:.0%} of the words; mean specificity {risks.specificity.mean():.2f} on a 0-3 scale; {risks[risks.specificity < 1.5].words.sum() / risks.words.sum():.0%} of words sit in factors Jev scored as generic.
* **Overweighted (more words than facts):** {"; ".join(f"{t} (index {themes.loc[t, 'weight_index']}, peer-shared {themes.loc[t, 'peer_shared_share']:.0%})" for t in over.index) or "none"}.
* **Underweighted (more facts than words):** {"; ".join(f"{t} (index {themes.loc[t, 'weight_index']}, largest anchor {themes.loc[t, 'largest_anchor_x_liquidity']}x liquidity)" if not pd.isna(themes.loc[t, 'largest_anchor_x_liquidity']) else f"{t} (index {themes.loc[t, 'weight_index']})" for t in under.index) or "none"}.
* **Proportionate:** {", ".join(prop.index)}.
* **Robust under both evidence bases (all sections, and Summary + MD&A + Business only):** overweighted {", ".join(themes[themes.robust_verdict.str.startswith("over")].index) or "none"}; underweighted {", ".join(themes[themes.robust_verdict.str.startswith("under")].index) or "none"}; proportionate {", ".join(themes[themes.robust_verdict == "proportionate"].index) or "none"}; depends on the evidence base: {", ".join(themes[themes.robust_verdict == "depends on the evidence base"].index) or "none"}.
* **Peer check:** {int(risks.peer_shared.sum())} of {len(risks)} factors ({risks[risks.peer_shared].words.sum() / risks.words.sum():.0%} of words) have a CoreWeave S-1 counterpart; least shared themes {", ".join(themes.sort_values("peer_shared_share").index[:3])}.
* **Financing:** liquidity ${liq:.1f}B against ${A["min_commitments_jun30_busd"]}B of minimum commitments at June 30 and about ${A["post_quarter_commitments_busd"]:.0f}B added since; the only funded debt-like paper is ${A["amazon_notes_busd"]}B of non-interest-bearing Amazon notes (carried at ${bs["convertible_notes_payable_musd"]/1000:.1f}B fair value) and ${bs["finance_lease_liabilities_musd"]/1000:.2f}B of finance leases; the ${F.loc["A&R senior secured revolving credit facility", "amount_busd"]:.0f}B revolver is undrawn; ${A["npa_capacity_busd"]:.0f}B of NPA capacity plus ${F.loc["AMD Class N purchase commitment", "amount_busd"]:.0f}B from AMD is contingent and share-settled; preferred rounds C-H raised ${pref.gross_busd.sum():.1f}B; H1 2026 financing inflow ${A["fin_cf_h1_2026_musd"]/1000:.1f}B against operating cash flow ${A["op_cf_h1_2026_musd"]/1000:.1f}B.
* **Instruments typed:** {int((fin.compute_linked >= 0.5).sum())} of {len(fin)} tied to compute; {int((fin.converts_to_equity >= 0.5).sum())} can end in shares; {int((fin.status == "drawn").sum())} drawn. Vendor commitments: {int((commits.basis == "fixed_minimum").sum())} of {len(commits)} fixed regardless of usage, {int((commits.true_up >= 0.5).sum())} with a true-up, {int((commits.vendor_dependency >= 0.5).sum())} depending on the vendor's own financing or deliveries.
* **Counterparty roles:** {", ".join(f"{n} {int(roles.loc[n, 'roles_established'])}" for n in NAMES[:4])} of 7 roles established; Amazon and Google each: {", ".join(k for k in ROLE_Q if roles.loc["Amazon", k] > 0 and roles.loc["Google", k] > 0)}.
* **Manual checks:** {int(manual.agrees.sum())} of {len(manual)} agree. **Review flags:** {len(flags_df)}.
'''
display(Markdown(re.sub(r"(?<!\\)\$", r"\\$", generated)))
print("wrote anthropic_s1_risk_factors.csv, anthropic_s1_risk_themes.csv, anthropic_s1_evidence_hits.csv, anthropic_s1_theme_evidence_passages.csv, anthropic_s1_exposure_anchors.csv, anthropic_s1_peer_matches.csv, anthropic_s1_financing.csv, anthropic_s1_vendor_commitments.csv, anthropic_s1_counterparty_roles.csv, anthropic_s1_manual_checks.csv")
""")

md(r"""
## Takeaways

Qualitative on purpose; the numbers are in the generated summary and the CSVs.

**On the first question: which risks, and are they weighted in proportion.** Five themes are overweighted under
both evidence bases: regulation, competition, AI safety and misuse, copyright and IP litigation, and cybersecurity
and privacy. They take about two fifths of the risk-factor words and the rest of the filing carries few concrete
facts about them. That is partly the nature of externally driven risks, which a registrant can warn about but not
document, and partly genre: the regulation, IP and cyber factors are mostly shared with CoreWeave's S-1 heading for
heading. Safety is the exception that proves the point. It is the single largest theme by words, the least
peer-shared of all, and most of it describes things that have already happened (the company's own commitments,
its political exposure, the suits already filed). Anthropic is using its risk factors to state a position as much
as to warn.

Three themes are underweighted under both bases, and they are the ones a credit or equity analyst would start
with. The multi-role counterparty problem gets one risk factor of about 750 words, around one percent of the
section, while the document's own record shows Amazon and Google each in six of seven roles toward Anthropic
(investor, financing source, supplier, customer, distribution channel, competitor) and the three cloud providers
holding minimum spend commitments of about twice the company's liquidity. Access to capital gets four factors
against the largest evidence footprint in the filing: minimum commitments at June 30 of roughly twice cash and
investments, a half-year in which financing inflows were about thirty times operating cash flow, and a liquidity
covenant that starts in the fourth quarter. Talent is third, with the most generic writing in the section (every
talent factor has a CoreWeave twin) set against post-quarter equity grants and a donation-matching charge measured
in billions. The compute commitment theme sits between: proportionate by words against facts, but it is the most
specific theme in the section, it carries the largest dollar anchor (post-quarter minimum commitments above three
times liquidity), and it gets two factors. By the dollar lens rather than the word lens it is light.

Six themes change verdict depending on whether the Description of Capital Stock and the financial statement
notes count as evidence. Governance and the stock-ownership risks look underweighted only because those sections
document share classes and equity accounting at length; on the operating sections alone they are proportionate.
Compute supply, model execution and customer revenue look overweighted only on the full document; the MD&A and
Business sections carry them in proportion. The notebook reports both and treats only the agreements as findings.

Two numbers describe the section as a whole: about two thirds of the words have a counterpart in a peer S-1 from
eighteen months earlier, and about two thirds of the words sit in factors that describe something that has already
occurred. The second is the more useful reading of this document: the risk factors are where the filing discloses
its history, including the settlement, the restricted cash, the conflicts, and the compute shortfalls.

**On the second question: the financing structure.** Anthropic is financed with equity and equity-like paper, and
its cash obligations sit in compute contracts rather than in debt. Preferred stock is carried at well over
$150 billion, with the Series G and H rounds of 2026 accounting for most of what was raised since inception. The
only funded instrument that resembles debt is about $6 billion of non-interest-bearing Amazon rollover notes,
carried at fair value near $109 billion; the $72 billion fair value charge in the first half is the accounting
shadow of a rising valuation on those notes, not cash, and the notes convert at the offering subject to Amazon's
ownership cap. The $15 billion revolver is undrawn, secured, and carries a $5 billion minimum liquidity covenant
and a springing maturity; its security and most negative covenants fall away on an investment-grade rating. The
$77 billion of note purchase capacity and the $5 billion AMD commitment are conditional and share-settled: Amazon
in $5 billion tranches on compute milestones under its own commercial agreements, Google reducible by a concurrent
placement at the IPO price, Broadcom usable only to pay rent on Broadcom's own equipment at 9% paid in kind, with
penalty terms if revenue growth falls below thresholds and a 150% payout on a change of control. Six of the seven
instruments typed can end in shares; five are tied to compute.

The commitments are where the leverage lives. Minimum purchase commitments rose from about $55 billion at the end
of 2025 to about $266 billion at June 30, 2026, with roughly $245 billion more signed after the quarter, on top of
about $161 billion of equipment lease rent to Broadcom and an estimated $125 to $150 billion of further TPU
capacity outside the table. By agreement, the Microsoft, Google and Amazon commitments are fixed regardless of
usage (two with explicit true-ups); the SpaceXAI arrangement is cancelable on notice after early 2027; the Nscale
and Lambda agreements accrue fees only as capacity is delivered and depend on those vendors securing their own
financing or facility leases. The circularity the conflicts risk factor describes in general terms is specific in
the tables: the parties supplying the compute are the parties financing it, and in two cases the financing draws
are triggered by milestones under the same compute agreements.

**Where Jev earned its place.** Typing 88 risk factors on seven dimensions in two passes with no theme flips;
reading 649 passages against sixteen themes, about ten thousand judgments, in a few minutes for a few cents;
matching headings to a peer filing; typing seven instruments and seven commitments from their own paragraphs; and
establishing counterparty roles passage by passage. Regex pulled the figures, pandas built the index, and every
author-read check agreed with the run.

**Caveats.** The weighting index compares words with the count of fact-bearing passages, not with dollars, and the
sections that document equity mechanics inflate it, which is why the operating-sections sensitivity is reported
and only agreements are called findings. The evidence judgment is Jev's and a passage can be counted for a theme on
a fact that is incidental to it; the full matrix is saved for review. Theme assignment is one label per factor
and several factors span two. The peer check uses one peer and one vintage. The S-1 is a first filing with the
price range, capitalization and contractual-obligations tables blank; the first amendment will fill them and is
the next primary source.
""")

nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).resolve().parent / "jev_anthropic_s1.ipynb"
nbf.write(nb, out)
print("wrote", out, "with", len(cells), "cells")
