# Anthropic S-1 Economics

An independent, figure-by-figure reading of Anthropic, PBC's Form S-1 (filed October 26, 2026, SEC CIK 2130357). It covers margins, compute efficiency, the economics of more than $800 billion of contracted compute, customer concentration, and how the filing distributes its risk disclosure.

**Interactive report:** [`docs/index.html`](docs/index.html). Open it in a browser, or view the published copy on GitHub Pages once it is enabled (see [Publishing](#publishing-the-report)).

> This is an independent analysis of a public filing. It is not affiliated with or endorsed by Anthropic and is not investment advice.

## Key findings

| Question | Finding |
|---|---|
| **Gross margin** | Accounting gross margin was **85.4%** in H1 2026, but cost of revenue covers serving compute only. Charging all compute, training included, as cost of goods gives **45.1%**. After channel-partner fees it is about **28%**, and the operating margin was **−4.3%**. FY2025's operating margin was **−175.8%**, including the $1.5B Bartz settlement. |
| **Compute efficiency** | Revenue per compute dollar rose from **$0.57** (Q2 2025) to **$2.08** (Q2 2026), a 3.7× gain. About half of the 15× revenue growth came with more compute. The gains arrived in steps after model releases. The marginal return on new compute fell from Q1 to Q2 2026: $6.09 of revenue per added compute dollar, then $3.14. |
| **Contracted compute** | **$855B** is contracted, of which **$683B** is firm. If demand fills that capacity at H1 2026 economics, the contracts are worth about **$276B** at split discount rates: 10.9% on revenue, 7.4% on payments. If revenue is limited by demand, it must grow about **64% a year** from the $46B Q2 2026 run-rate for NPV ≥ 0. It must grow about **69% a year** to keep cash above the $5B liquidity covenant. |
| **Customers** | Customers spending $100K+ a year were **74%** of H1 2026 revenue, and about **250** customers spend $10M+. The top five customers' share fell from **36%** (Q1 2026) to **21%** (Q3 2026). Losing that 21% from 2028 raises the demand growth needed to about **114% a year**. |
| **Disclosure emphasis** | Risk factors spend the most words, relative to the filing's own facts, on regulation, competition, AI safety, IP litigation and cybersecurity. They spend the least on supplier conflicts of interest, access to capital and talent. |

Every figure in the report links to the sentence in the filing that states it.

## What is in this repository

```
docs/index.html                     the interactive report (self-contained; loads plotly.js from cdnjs)
jev_anthropic_s1.ipynb              notebook: Jev's reading of the filing (risk factors, evidence, peers, agreements, roles)
jev_anthropic_s1_colab.ipynb        the same notebook for Google Colab (outputs cleared)
build_anthropic_s1_notebook.py      generates the notebook

s1_filing.py                        fetches and parses the S-1; every figure is returned with its quote and page
s1_economics.py                     margin bridge, compute efficiency, contract ledger, payment calendar, reverse DCF
s1_hurdle.py                        discount-rate inputs (Treasury, equity risk premium, peer betas); cached to CSV
s1_model.js                         the reverse-DCF model in JavaScript, used by the report's controls
s1_check_model.py                   checks the JavaScript model against the Python model
s1_role_passages.py                 a small Jev pass behind the counterparty role map
s1_dashboard.py / .js / .css        build the report

anthropic_s1_*.csv                  every dataset behind the report (see below)
```

### Datasets

| File | Contents |
|---|---|
| `anthropic_s1_filing_facts.csv` | Every figure extracted from the filing, with its unit, section, page and quote |
| `anthropic_s1_margin_bridge.csv` | Revenue to operating income by period, with serving and non-serving compute bounds |
| `anthropic_s1_quarterly_efficiency.csv` | Quarterly revenue, compute expense and efficiency ratios |
| `anthropic_s1_contract_ledger.csv`, `_ledger_reconciliation.csv`, `_payment_calendar.csv` | The reconciled commitments, the checks on them, and the payment schedule |
| `anthropic_s1_utilization_scenarios.csv`, `_model_assumptions.csv`, `_hurdle_inputs.csv` | Reverse-DCF scenarios, every assumption with its reason, and the discount-rate inputs |
| `anthropic_s1_risk_factors.csv`, `_risk_themes.csv`, `_evidence_hits.csv`, `_theme_evidence_passages.csv`, `_peer_matches.csv` | Jev's typing of the 88 risk factors, the words-versus-facts index, and the evidence behind it |
| `anthropic_s1_financing.csv`, `_vendor_commitments.csv`, `_counterparty_roles.csv`, `_counterparty_role_passages.csv` | Jev's reading of financing instruments, compute agreements and counterparty roles |
| `anthropic_s1_manual_checks.csv` | Author-read checks against the filing |

## Working with the files

**Just reading:** open `docs/index.html` in a browser (an internet connection is needed for fonts and plotly.js). Click any chart element or table row to read its source.

**Rebuilding the report** (no API keys needed):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env.local        # set EDGAR_IDENTITY; keys are optional for this step
.venv/bin/python s1_economics.py  # extracts figures, runs the model, writes the CSVs
.venv/bin/python s1_check_model.py   # optional; needs Node.js
.venv/bin/python s1_dashboard.py  # writes docs/index.html
```

The first run downloads the S-1 from SEC EDGAR into `edgar_cache/`, which is git-ignored. Later runs read the cache.

**Refreshing market inputs:** set `FMP_API_KEY` in `.env.local`, then run `.venv/bin/python s1_hurdle.py --refresh` before `s1_economics.py`.

**Re-running the Jev analysis:** set `TYPESAFE_API_KEY` in `.env.local`, then open `jev_anthropic_s1.ipynb` in Jupyter. Or run it headless:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute --inplace jev_anthropic_s1.ipynb
```

A full run makes about 1,100 requests to TypeSafe's Jev (about 13,000 judgments, roughly $0.11). In Colab, add `TYPESAFE_API_KEY` under Secrets and run `jev_anthropic_s1_colab.ipynb`.

## Method in brief

- **Figures** are extracted from the filing by pattern-matching, and each keeps the sentence and page that state it. All arithmetic is in code.
- **Judgments that need reading** are made by TypeSafe's Jev. These cover which theme a passage supports, how an agreement can be cancelled, and which role a counterparty plays. Jev returns typed answers with probabilities, so every threshold and count can be inspected and re-run.
- **The reverse DCF** treats compute payments as debt-like and discounts them at the filing's own lease rate. Revenue is discounted at an unlevered cost of capital built from listed peers. The model solves for the demand growth and the price-efficiency at which NPV reaches zero.
- **Limitations** are listed in the report's Appendix A. In particular, the filing gives no physical capacity units, leaves its own aggregate commitment figures blank, and does not split training compute from other R&D. Assumptions are listed in Appendix B and `anthropic_s1_model_assumptions.csv`.

## Publishing the report

`docs/index.html` is a static page, so it can be served directly by GitHub Pages: **Settings → Pages → Deploy from a branch → `main` / `/docs`**. It is then available at `https://yakshb.github.io/anthropic-s1-analysis/`.

## Contributing

Corrections and extensions are welcome.

- **Found a wrong figure?** Open an issue with the figure, the page of the S-1, and the sentence that states it. Every extracted value is in `anthropic_s1_filing_facts.csv` with its quote.
- **Changing the model?** Keep `s1_model.js` and `model()` in `s1_economics.py` in step, and run `s1_check_model.py` before opening a pull request.
- **Changing assumptions?** Add or edit them in `ASSUMPTIONS` in `s1_economics.py` with a one-line reason. They flow into the report's appendix automatically.
- **Never commit keys.** `.env.local` and every other `.env*` file except `.env.example` are git-ignored.
- After any change, rebuild with `s1_economics.py` and `s1_dashboard.py` so `docs/index.html` and the CSVs stay in sync with the code.

## Sources

SEC EDGAR: Anthropic, PBC Form S-1 (CIK 2130357), filed October 26, 2026. Peer risk-factor headings come from CoreWeave, Inc.'s Form S-1 (March 3, 2025). Market inputs are from Financial Modeling Prep. Reading judgments are by [TypeSafe](https://docs.typesafe.ai)'s Jev.
