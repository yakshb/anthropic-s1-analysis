# Anthropic S-1 Economics

An independent, figure-by-figure reading of Anthropic, PBC's [Form S-1](https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/anthropicpbc-sx1.htm) (filed October 26, 2026, SEC CIK 2130357). It covers margins, compute efficiency, the economics of roughly $680–855 billion of contracted compute, customer concentration, and how the filing distributes its risk disclosure.

**Interactive report:** https://yakshb.github.io/anthropic-s1-analysis/ (also in [`docs/index.html`](docs/index.html)).

> This is an independent analysis of a public filing. It is not affiliated with or endorsed by Anthropic and is not investment advice.

## Key findings

| Question | Finding |
|---|---|
| **Gross margin** | Accounting gross margin was **85.4%** in H1 2026, but cost of revenue covers serving compute only. Charging all compute, training included, as cost of goods gives **45.1%**. After channel-partner fees it is about **28%**, and the operating margin was **−4.3%**. FY2025's operating margin was **−175.8%**, including the $1.5B Bartz settlement. |
| **Compute efficiency** | Revenue per compute dollar rose from **$0.57** (Q2 2025) to **$2.08** (Q2 2026), a 3.7× gain. About half of the 15× revenue growth came with more compute. The gains arrived in steps after model releases. The marginal return on new compute fell from Q1 to Q2 2026: $6.09 of revenue per added compute dollar, then $3.14. |
| **Contracted compute** | Firm compute commitments total about **$682B**. The **$855B** upper bound adds deals that can be cancelled or that depend on the vendor's financing, and may double-count contracts amended after June 30. Press reports on draft prospectuses put the figure between $600B and $750B. If revenue grows only as fast as demand, it must compound about **44% a year** from the $46B Q2 2026 run-rate to carry the firm commitments, or about **69% a year** if every contracted deal runs. Discount rates are 10.9% on revenue and 7.4% on payments. |
| **Customers** | Customers spending $100K+ a year were **74%** of H1 2026 revenue, and about **250** customers spend $10M+. The top five customers' share fell from **36%** (Q1 2026) to **21%** (Q3 2026). Losing that 21% from 2028 raises the demand growth needed on firm commitments to about **73% a year**. |
| **Disclosure emphasis** | Risk factors spend the most words, relative to the filing's own facts, on regulation, competition, AI safety, IP litigation and cybersecurity. They spend the least on access to capital, supplier conflicts of interest, and talent. |

Every figure in the report links to the sentence in the filing that states it.

## What is in this repository

```
docs/index.html            the interactive report, served by GitHub Pages
data/model/                figures extracted from the filing and the outputs of the economic model
data/jev/                  Jev's reading of the filing: risk factors, evidence, peers, agreements, roles
src/                       Python: the Jev reading, filing parser, economics, discount rates, report builder, checks
web/                       the report's stylesheet and scripts, including the JavaScript model
```

| `src/` | Does |
|---|---|
| `paths.py` | Every folder the project reads or writes; scripts run from any directory |
| `s1_jev_reading.py` | Jev's reading of the filing (risk factors, evidence, peer matching, agreements, financing, roles); writes `data/jev/` and `data/jev/run_metrics.csv` |
| `s1_filing.py` | Fetches and parses the S-1; every figure is returned with its quote and page |
| `s1_economics.py` | Margin bridge, compute efficiency, contract ledger, payment calendar, reverse DCF; writes `data/model/` |
| `s1_hurdle.py` | Discount-rate inputs (Treasury, equity risk premium, peer betas), cached to `data/model/hurdle_inputs.csv` |
| `s1_dashboard.py` | Builds `docs/index.html` from `data/` and `web/` |
| `s1_check_model.py` | Checks `web/s1_model.js` against the Python model (needs Node.js) |
| `s1_role_passages.py` | A small Jev pass behind the counterparty role map; writes `data/jev/counterparty_role_passages.csv` |

### Datasets

| File | Contents |
|---|---|
| `data/model/filing_facts.csv` | Every figure extracted from the filing, with its unit, section, page and quote |
| `data/model/margin_bridge.csv` | Revenue to operating income by period, with serving and non-serving compute bounds |
| `data/model/quarterly_efficiency.csv` | Quarterly revenue, compute expense and efficiency ratios |
| `data/model/contract_ledger.csv`, `ledger_reconciliation.csv`, `payment_calendar.csv` | The reconciled commitments, the checks on them, and the payment schedule |
| `data/model/utilization_scenarios.csv`, `model_assumptions.csv`, `hurdle_inputs.csv` | Reverse-DCF scenarios, every assumption with its reason, and the discount-rate inputs |
| `data/jev/risk_factors.csv`, `risk_themes.csv`, `evidence_hits.csv`, `theme_evidence_passages.csv`, `peer_matches.csv` | Jev's typing of the 88 risk factors, the words-versus-facts index, and the evidence behind it |
| `data/jev/financing.csv`, `vendor_commitments.csv`, `counterparty_roles.csv`, `counterparty_role_passages.csv` | Jev's reading of financing instruments, compute agreements and counterparty roles |
| `data/jev/manual_checks.csv`, `run_metrics.csv` | Author-read checks against the filing; Jev requests, judgments, latency and cost per step |

## Working with the files

**Just reading:** open `docs/index.html` in a browser (an internet connection is needed for fonts and plotly.js). Click any chart element or table row to read its source.

**Rebuilding the report** (no API keys needed). Run from the repository root:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env.local            # set EDGAR_IDENTITY; keys are optional for this step
.venv/bin/python src/s1_economics.py  # extracts figures, runs the model, writes data/model/
.venv/bin/python src/s1_check_model.py   # optional; needs Node.js
.venv/bin/python src/s1_dashboard.py  # writes docs/index.html
```

The first run downloads the S-1 from SEC EDGAR into `edgar_cache/`, which is git-ignored. Later runs read the cache.

**Refreshing market inputs:** set `FMP_API_KEY` in `.env.local`, then run `.venv/bin/python src/s1_hurdle.py --refresh` before `src/s1_economics.py`.

**Re-running the Jev analysis:** set `TYPESAFE_API_KEY` in `.env.local`, then run the full pipeline:

```bash
.venv/bin/python src/s1_jev_reading.py   # Jev's reading of the filing; writes data/jev/
.venv/bin/python src/s1_economics.py     # figures and the economic model; writes data/model/
.venv/bin/python src/s1_dashboard.py     # writes docs/index.html
```

`s1_jev_reading.py` makes about 1,100 requests to TypeSafe's Jev: about 13,000 judgments, roughly $0.11, a few minutes. `src/s1_role_passages.py` refreshes the counterparty role map separately; it makes about 160 requests.

## Method in brief

- **Figures** are extracted from the filing by pattern-matching, and each keeps the sentence and page that state it. All arithmetic is in code.
- **Judgments that need reading** are made by TypeSafe's Jev. These cover which theme a passage supports, how an agreement can be cancelled, and which role a counterparty plays. Jev returns typed answers with probabilities, so every threshold and count can be inspected and re-run.
- **The reverse DCF** treats compute payments as debt-like and discounts them at the filing's own lease rate. Revenue is discounted at an unlevered cost of capital built from listed peers. The model solves for the demand growth and the price-efficiency at which NPV reaches zero.
- **Limitations** are listed in the report's Appendix A. In particular, the filing gives no physical capacity units, leaves its own aggregate commitment figures blank, and does not split training compute from other R&D. Assumptions are listed in Appendix B and `data/model/model_assumptions.csv`.

## Contributing

Corrections and extensions are welcome.

- **Found a wrong figure?** Open an issue with the figure, the page of the S-1, and the sentence that states it. Every extracted value is in `data/model/filing_facts.csv` with its quote.
- **Changing the model?** Keep `web/s1_model.js` and `model()` in `src/s1_economics.py` in step, and run `src/s1_check_model.py` before opening a pull request.
- **Changing assumptions?** Add or edit them in `ASSUMPTIONS` in `src/s1_economics.py` with a one-line reason. They flow into the report's appendix automatically.
- **Never commit keys.** `.env.local` and every other `.env*` file except `.env.example` are git-ignored.
- After any change, rebuild with `src/s1_economics.py` and `src/s1_dashboard.py` so `docs/index.html` and `data/` stay in sync with the code.

## Sources

### Primary filing

- **Anthropic, PBC, Form S-1 registration statement**, filed with the SEC on October 26, 2026. CIK 2130357, accession no. 0001628280-26-067168.
  - Document: [anthropicpbc-sx1.htm](https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/anthropicpbc-sx1.htm)
  - Filing index, with exhibits: [0001628280-26-067168](https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/0001628280-26-067168-index.html)
  - Company filings on EDGAR: [Anthropic, PBC](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0002130357&type=S-1)

  Every figure, quote and passage in the report and in `data/` comes from this document. The pipeline locates it through the [EDGAR submissions API](https://data.sec.gov/submissions/CIK0002130357.json).

### Comparison filing

- **CoreWeave, Inc., Form S-1 registration statement**, filed with the SEC on March 3, 2025. CIK 1769628, accession no. 0001193125-25-044231.
  - Document: [d899798ds1.htm](https://www.sec.gov/Archives/edgar/data/1769628/000119312525044231/d899798ds1.htm)
  - Filing index: [0001193125-25-044231](https://www.sec.gov/Archives/edgar/data/1769628/000119312525044231/0001193125-25-044231-index.html)

  Its 69 risk-factor headings are the comparison set for the industry-boilerplate analysis (report section 9, `data/jev/peer_matches.csv`).

### Market data for the discount rates

Retrieved through [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs) and cached in `data/model/hurdle_inputs.csv`:

- **10-year US Treasury yield**: 5.00% on October 23, 2026, from the US Treasury's [daily par yield curve](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value_month=202610).
- **US equity risk premium**: 4.46%, from FMP's market-risk-premium country table. The source gives no as-of date; it was retrieved on October 26, 2026.
- **Peer betas and capital structure**: five-year monthly betas, market capitalizations and total debt from FMP company profiles and balance sheets for Microsoft, Alphabet, Amazon, Meta, Oracle, Palantir, Snowflake, ServiceNow, Datadog and CoreWeave.

The payment-side discount rate uses no outside data. It is the lease discount rate disclosed in Note 7 of the Anthropic S-1.

### Press reports used as a cross-check

These describe draft prospectuses reviewed before the public filing. They are compared with the contract ledger in report section 3.1; no figure in the model comes from them.

- [Bloomberg, October 20, 2026](https://www.bloomberg.com/news/articles/2026-10-20/anthropic-could-spend-750-billion-on-computing-costs-wsj-says), citing The Wall Street Journal: possible computing spend of up to $750B, including deals still under negotiation.
- [The Next Web, October 21, 2026](https://thenextweb.com/news/anthropic-s-1-750bn-compute-80-7bn-loss), summarizing the WSJ and Axios: more than $600B of future infrastructure costs, plus about $150B in deals under negotiation.

### Reading judgments

- **[TypeSafe](https://docs.typesafe.ai)'s Jev** made the reading judgments: risk-factor typing, evidence, peer matching, and agreement and counterparty roles.

## License

MIT, see [LICENSE](LICENSE). The S-1 text quoted in the report and datasets comes from public SEC filings.
