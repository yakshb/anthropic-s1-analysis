"""Standalone Jev pass: per-passage counterparty-role probabilities for Anthropic's S-1.

Writes data/jev/counterparty_role_passages.csv (one row per (counterparty, passage) with seven role Nouls) so the
dashboard can draw a probability gradient instead of a thresholded count. Pure Python; run from the repository root:
    python src/s1_role_passages.py
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from typesafe_sdk import Noul, NoulCriteria, TypeSafeClient

from paths import DATA_JEV, ENV_FILE, CACHE

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
EDGAR_IDENTITY = os.environ.get("EDGAR_IDENTITY", "Example user@example.com")
ts = TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"], timeout=90.0)
CACHE.mkdir(exist_ok=True)
SEC_BASE, SEC_ARCHIVES = "https://data.sec.gov", "https://www.sec.gov/Archives/edgar/data"
_lock, _last = threading.Lock(), [0.0]
LOG = []


def edgar_get(url):
    key = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:])
    if key.exists():
        return key.read_bytes()
    with _lock:
        wait = 0.125 - (time.perf_counter() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.perf_counter()
    r = requests.get(url, headers={"User-Agent": EDGAR_IDENTITY, "Accept": "application/json"}, timeout=120)
    r.raise_for_status()
    key.write_bytes(r.content)
    return r.content


def html_to_text(raw):
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"[ \t\xa0​]+", " ", soup.get_text("\n"))
    return re.sub(r"\n\s*\n+", "\n", text).strip()


flat = lambda s: re.sub(r"\s+", " ", s or "").strip()


def ask(state, questions, attempts=3):
    for i in range(attempts):
        try:
            r = ts.system_one(state, questions)
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(1.5 * (i + 1))
            continue
        LOG.append({"input_tokens": r.usage.input_tokens or 0})
        return r


# --- the filing, sectioned by page exactly as in s1_jev_reading.py
CIK = "2130357"
subs = json.loads(edgar_get(f"{SEC_BASE}/submissions/CIK{int(CIK):010d}.json"))
recent = pd.DataFrame(subs["filings"]["recent"])
s1 = recent[recent.form == "S-1"].sort_values("filingDate").iloc[-1]
text = html_to_text(edgar_get(f"{SEC_ARCHIVES}/{CIK}/{s1.accessionNumber.replace('-', '')}/{s1.primaryDocument}"))
lines = text.split("\n")
marks = [(i, lines[i].strip()) for i in range(len(lines) - 1) if re.fullmatch(r"(F-)?\d{1,3}|II-\d", lines[i].strip()) and lines[i + 1].strip() == "Table of Contents"]
pages, prev = [], 0
for i, label in marks:
    pages.append((label, "\n".join(lines[prev:i])))
    prev = i + 2
tail = lines[prev:]
ii = next((k for k, l in enumerate(tail) if l.strip() == "II-1"), None)
pages += [("F-end", "\n".join(tail[:ii])), ("II", "\n".join(tail[ii + 1:]))] if ii is not None else [("II", "\n".join(tail))]
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
SHORT = {"MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS": "MD&A", "INDEX TO CONSOLIDATED FINANCIAL STATEMENTS": "FINANCIAL STATEMENTS",
         "MATERIAL U.S. FEDERAL INCOME TAX CONSEQUENCES TO NON-U.S. HOLDERS OF OUR CLASS A COMMON STOCK": "TAX", "CERTAIN RELATIONSHIPS AND RELATED PERSON TRANSACTIONS": "RELATED PERSON TRANSACTIONS",
         "OUR GOVERNANCE STRUCTURE AND ITS GOALS": "GOVERNANCE", "SPECIAL NOTE REGARDING FORWARD-LOOKING STATEMENTS": "FORWARD-LOOKING STATEMENTS"}
toc_num = [(SHORT.get(n, n), int(p)) for n, p in toc if p.isdigit()]


def section_of(label):
    if label.startswith("F-"):
        return "FINANCIAL STATEMENTS"
    if label.startswith("II"):
        return "PART II"
    name = "COVER"
    for n, start in toc_num:
        if start <= int(label):
            name = n
    return name


PASSAGES = []
for sec in dict.fromkeys(section_of(p) for p, _ in pages):
    chunk, offsets, pos = [], [], 0
    for p, t in pages:
        if section_of(p) == sec:
            offsets.append((pos, p)); chunk.append(t); pos += len(t) + 1
    joined, i, j = "\n".join(chunk), 0, 0
    while i < len(joined):
        PASSAGES.append({"section": sec, "page": [p for off, p in offsets if off <= i][-1], "pid": f"{sec}#{j}", "text": flat(joined[i:i + 1500])})
        i += 1300; j += 1
print(f"{len(PASSAGES)} passages from the S-1 filed {s1.filingDate}")

# --- counterparties, with the aliases the filing uses
ALIASES = {"Amazon": r"\bAmazon\b|\bAWS\b", "Google": r"\bGoogle\b|\bAlphabet\b", "Microsoft": r"\bMicrosoft\b|\bAzure\b", "Broadcom": r"\bBroadcom\b",
           "AMD": r"\bAMD\b|Advanced Micro Devices", "NVIDIA": r"\bNVIDIA\b", "SpaceXAI": r"SpaceXAI|SpaceX\.AI|\bX\.AI\b|\bxAI\b", "Nscale": r"\bNscale\b", "Lambda": r"\bLambda\b"}
ROLE_Q = {
    "investor": "holds Anthropic's preferred stock, common stock or convertible notes, or has invested money in Anthropic",
    "financing_source": "provides or commits to provide financing to Anthropic: a note purchase facility, a share purchase commitment, a credit facility, a guarantee of lease obligations",
    "supplier": "supplies Anthropic with compute, chips, cloud capacity, hardware or data center services",
    "lessor": "leases equipment or facilities to Anthropic",
    "customer": "buys or uses Anthropic's models, platform or applications",
    "distribution_channel": "makes Anthropic's models available to customers through its own cloud platform or marketplace, such as Amazon Bedrock, Google Cloud Vertex AI or Microsoft Foundry",
    "competitor": "develops or offers AI models or services that compete with Anthropic's",
}
SKIP = {"UNDERWRITING", "TAX", "PART II", "EXECUTIVE COMPENSATION", "MANAGEMENT", "COVER"}
jobs = []
for name, pat in ALIASES.items():
    cand = [p for p in PASSAGES if p["section"] not in SKIP and re.search(pat, p["text"])]
    cand.sort(key=lambda p: -len(re.findall(pat, p["text"])))
    jobs += [(name, p) for p in cand[:60]]
print(f"{len(jobs)} (counterparty, passage) pairs:", {n: sum(1 for x, _ in jobs if x == n) for n in ALIASES})


def judge(job):
    name, p = job
    r = ask({"counterparty": name, "passage": p["text"], "section": p["section"]},
            {k: Noul(instructions=f"Does `passage` state that `counterparty` {desc}?", criteria=NoulCriteria(true=f"The passage says {name} {desc}", false="The passage does not establish this role for the counterparty")) for k, desc in ROLE_Q.items()})
    return {"counterparty": name, "pid": p["pid"], "section": p["section"], "page": p["page"], **{k: round(r.nouls[k].noul, 3) for k in ROLE_Q}, "text": p["text"]}


t0 = time.perf_counter()
with ThreadPoolExecutor(6) as pool:
    rows = list(pool.map(judge, jobs))
out = pd.DataFrame(rows)
out.to_csv(DATA_JEV / "counterparty_role_passages.csv", index=False)
tok = sum(l["input_tokens"] for l in LOG)
print(f"{len(rows)} requests, {tok:,} input tokens, ${tok * 0.042 / 1e6:.4f}, {time.perf_counter() - t0:.0f}s -> data/jev/counterparty_role_passages.csv")
print(out.groupby("counterparty")[list(ROLE_Q)].max().round(2))
