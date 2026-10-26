"""Shared access to Anthropic's S-1 (filed 2026-10-26): text, pages, sections, passages, risk factors, and figures
extracted together with the sentence that states them.

Every number the dashboard presents as "from the filing" goes through `fact()` or `table_row()`, which return the value
with its quote and page so the dashboard can show the source on click.
"""
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
HERE = Path(__file__).resolve().parent
from paths import CACHE  # noqa: E402
SEC_BASE, SEC_ARCHIVES = "https://data.sec.gov", "https://www.sec.gov/Archives/edgar/data"
CIK = "2130357"
_lock, _last = threading.Lock(), [0.0]
flat = lambda s: re.sub(r"\s+", " ", s or "").strip()


def edgar_get(url: str) -> bytes:
    CACHE.mkdir(exist_ok=True)
    key = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:])
    if key.exists():
        return key.read_bytes()
    with _lock:
        wait = 0.125 - (time.perf_counter() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.perf_counter()
    ident = os.environ.get("EDGAR_IDENTITY", "Example user@example.com")
    r = requests.get(url, headers={"User-Agent": ident, "Accept": "application/json"}, timeout=120)
    r.raise_for_status()
    key.write_bytes(r.content)
    return r.content


def html_to_text(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"[ \t\xa0​]+", " ", soup.get_text("\n"))
    return re.sub(r"\n\s*\n+", "\n", text).strip()


@dataclass
class Fact:
    key: str
    value: object
    unit: str
    quote: str
    section: str
    page: str
    label: str = ""

    def row(self):
        return {"key": self.key, "label": self.label, "value": self.value, "unit": self.unit, "section": self.section, "page": self.page, "quote": self.quote}


SHORT = {"MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS": "MD&A", "INDEX TO CONSOLIDATED FINANCIAL STATEMENTS": "FINANCIAL STATEMENTS",
         "MATERIAL U.S. FEDERAL INCOME TAX CONSEQUENCES TO NON-U.S. HOLDERS OF OUR CLASS A COMMON STOCK": "TAX", "CERTAIN RELATIONSHIPS AND RELATED PERSON TRANSACTIONS": "RELATED PERSON TRANSACTIONS",
         "OUR GOVERNANCE STRUCTURE AND ITS GOALS": "GOVERNANCE", "SPECIAL NOTE REGARDING FORWARD-LOOKING STATEMENTS": "FORWARD-LOOKING STATEMENTS"}


class Filing:
    def __init__(self):
        subs = json.loads(edgar_get(f"{SEC_BASE}/submissions/CIK{int(CIK):010d}.json"))
        rec = subs["filings"]["recent"]
        rows = [dict(zip(rec, v)) for v in zip(*rec.values())]
        s1 = sorted([r for r in rows if r["form"] == "S-1"], key=lambda r: r["filingDate"])[-1]
        self.filed = s1["filingDate"]
        self.url = f"{SEC_ARCHIVES}/{CIK}/{s1['accessionNumber'].replace('-', '')}/{s1['primaryDocument']}"
        self.raw = edgar_get(self.url)
        self.text = html_to_text(self.raw)
        self._build_pages()
        self._build_passages()

    # ---- pages and sections, identical to s1_jev_reading.py
    def _build_pages(self):
        lines = self.text.split("\n")
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
        self.toc_num = [(SHORT.get(n, n), int(p)) for n, p in toc if p.isdigit()]
        self.pages = pages
        self.flat_pages = [(p, flat(t)) for p, t in pages]

    def section_of(self, label):
        if label.startswith("F-"):
            return "FINANCIAL STATEMENTS"
        if label.startswith("II"):
            return "PART II"
        name = "COVER"
        for n, start in self.toc_num:
            if start <= int(label):
                name = n
        return name

    def section_text(self, sec):
        return "\n".join(t for p, t in self.pages if self.section_of(p) == sec)

    def _build_passages(self):
        self.passages = []
        for sec in dict.fromkeys(self.section_of(p) for p, _ in self.pages):
            chunk, offsets, pos = [], [], 0
            for p, t in self.pages:
                if self.section_of(p) == sec:
                    offsets.append((pos, p)); chunk.append(t); pos += len(t) + 1
            joined, i, j = "\n".join(chunk), 0, 0
            while i < len(joined):
                self.passages.append({"section": sec, "page": [p for off, p in offsets if off <= i][-1], "pid": f"{sec}#{j}", "text": flat(joined[i:i + 1500])})
                i += 1300; j += 1
        self.passage_by_pid = {p["pid"]: p for p in self.passages}

    # ---- locating a quote
    def page_of(self, snippet):
        s = flat(snippet)[:80]
        for p, t in self.flat_pages:
            if s in t:
                return p
        s = flat(snippet)[:40]
        return next((p for p, t in self.flat_pages if s in t), "?")

    @staticmethod
    def sentence_around(text, start, end):
        a = max(text.rfind(". ", 0, start), text.rfind("• ", 0, start), text.rfind("| ", 0, start))
        a = 0 if a < 0 else a + 2
        b = text.find(". ", end)
        b = len(text) if b < 0 else b + 1
        return text[a:b].strip()

    def fact(self, key, pattern, section, unit, label="", scale=1.0, group=1, as_text=False, within=None, required=True):
        """Value from the first match of `pattern` in `section` (or in `within`, a substring anchor), with its sentence."""
        src = flat(self.section_text(section))
        if within:
            i = src.find(within)
            src = src[i:] if i >= 0 else ""
        m = re.search(pattern, src)
        if not m:
            if required:
                raise ValueError(f"fact {key}: pattern not found in {section}: {pattern}")
            return Fact(key, None, unit, "", section, "?", label)
        raw = m.group(group)
        val = raw if as_text else float(re.sub(r"[,\s$]", "", raw)) * scale
        quote = self.sentence_around(src, m.start(), m.end())
        return Fact(key, val, unit, quote, section, self.page_of(src[m.start():m.end() + 60] if len(quote) < 40 else quote), label)

    def table_row(self, section, anchor, label, n, end_anchor=None):
        """n numeric cells after a row label inside the table that starts at `anchor`; '(x)' negative, '—' zero, footnote markers skipped."""
        src = flat(self.section_text(section))
        i = src.find(anchor)
        if i < 0:
            raise ValueError(f"table anchor not found: {anchor}")
        j = src.find(end_anchor, i + len(anchor)) if end_anchor else -1
        block = src[i: j if j > 0 else i + 8000]
        m = re.search(re.escape(label) + r"\s*(?:\(\d\))?\s*((?:\$?\s*(?:\([\d,]+\)|[\d,]+(?:\.\d+)?|—)\s*%?\s*){" + str(n) + "})", block)
        if not m:
            raise ValueError(f"row {label!r} not found after {anchor!r}")
        vals = []
        for tok in re.findall(r"\([\d,]+\)|[\d,]+(?:\.\d+)?|—", m.group(1))[:n]:
            vals.append(0.0 if tok == "—" else (-float(tok.strip("()").replace(",", "")) if tok.startswith("(") else float(tok.replace(",", ""))))
        quote = (block[:block.find(" ", 160)] + " … " + m.group(0)) if m.start() > 200 else block[: m.end()]
        return vals, quote, self.page_of(m.group(0)[:60]) if self.page_of(m.group(0)[:60]) != "?" else self.page_of(anchor)

    # ---- risk factors from the HTML, as in s1_jev_reading.py
    @lru_cache(maxsize=1)
    def risk_factors(self):
        soup = BeautifulSoup(self.raw, "lxml")
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
        s_idx = [i for i, b in enumerate(blocks) if b["text"].startswith("Risks Related to our Business and Industry") and b["bold"] and not b["italic"]][-1]
        e_idx = next(i for i, b in enumerate(blocks) if b["text"].upper().startswith("SPECIAL NOTE REGARDING FORWARD") and b["bold"] and i > s_idx)
        out, group, cur, i = [], None, None, s_idx
        while i < e_idx:
            b = blocks[i]
            if b["bold"] and not b["italic"] and b["size"] >= 11:
                group = b["text"]; i += 1; continue
            if b["bold"] and b["italic"]:
                head = [b["text"]]; i += 1
                while i < e_idx and blocks[i]["bold"] and blocks[i]["italic"]:
                    head.append(blocks[i]["text"]); i += 1
                cur = {"group": group, "heading": " ".join(head), "body": []}
                out.append(cur); continue
            if cur is not None and b["text"] != "Table of Contents" and not re.fullmatch(r"\d{1,3}", b["text"]):
                cur["body"].append(b["text"])
            i += 1
        for n, r in enumerate(out, 1):
            r["rid"] = f"r{n:02d}"
            r["body"] = " ".join(r["body"])
        return out

    # ---- MD&A liquidity blocks and the infrastructure agreement paragraphs
    @lru_cache(maxsize=1)
    def liquidity_blocks(self):
        mda = self.section_text("MD&A").split("\n")
        own = lambda name: [i for i, l in enumerate(mda) if l.strip() == name]
        end = own("Quantitative and Qualitative Disclosures about Market Risk")[-1]
        start = max(i for i in own("Liquidity and Capital Resources") if i < end)
        heads = {"Revolving Credit Agreement", "AMD Agreement", "Convertible Notes", "Outstanding Notes", "Note Purchase Agreements", "Amazon", "Broadcom", "Google",
                 "Cash Flows", "Off-Balance Sheet Arrangements", "Contractual Obligations", "Infrastructure Service Arrangements", "Infrastructure Equipment Leases"}
        openers = ("The following", "In ", "We ", "Overview", "Since", "As of", "Our ", "Between")
        cuts = [(start, "Liquidity and Capital Resources")] + [(i, mda[i].strip()) for i in range(start, end) if mda[i].strip() in heads and mda[i + 1].strip().startswith(openers)] + [(end, None)]
        return {name: flat("\n".join(mda[i + 1:j])) for (i, name), (j, _) in zip(cuts, cuts[1:])}

    @lru_cache(maxsize=1)
    def agreement_paragraphs(self):
        isa = self.liquidity_blocks()["Infrastructure Service Arrangements"]
        parts = re.split(r"(?=(?:In [A-Z][a-z]+(?:, [A-Z][a-z]+)*(?: and [A-Z][a-z]+)? 20\d\d\s*,\s*we entered|Between [A-Z][a-z]+ and [A-Z][a-z]+ 20\d\d\s*,\s*we entered|Under the Hardware Supply Agreement with AMD))", isa)
        vendors = ["Microsoft", "Google", "Amazon", "SpaceXAI", "AMD", "Nscale", "Lambda"]
        out = {}
        for p in parts:
            p = p.strip()
            if len(p) > 200:
                out[next((v for v in vendors if v in p), "other")] = p
        return out


_FILING = None


def filing() -> Filing:
    global _FILING
    if _FILING is None:
        _FILING = Filing()
    return _FILING
