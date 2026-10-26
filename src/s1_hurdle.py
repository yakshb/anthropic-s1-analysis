"""Discount rates for the reverse DCF, built from sourced inputs and cached to data/model/hurdle_inputs.csv.

Two rates, because the two sides of the contracts carry different risk:
* Fixed compute payments are owed regardless of usage, so they are debt-like. They are discounted at Anthropic's own
  incremental borrowing rate as the filing discloses it: the weighted-average discount rates on its operating and finance
  leases (Note 7), weighted by the lease liabilities.
* Revenue net of variable costs and tax carries operating risk. With the fixed payments valued separately, that stream is
  discounted at an unlevered (asset) cost of capital: the 10-year Treasury yield + peer median unlevered beta × the US
  equity risk premium. Peer betas are FMP's 5-year monthly betas, unlevered with Hamada using market cap and total debt.

Run with --refresh to refetch from FMP; otherwise the cached CSV is used so rebuilds are reproducible offline.
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
from paths import DATA_MODEL, ENV_FILE

CACHE = DATA_MODEL / "hurdle_inputs.csv"
PEERS = {"AI platforms": ["MSFT", "GOOGL", "AMZN", "META", "ORCL"], "High-growth AI software": ["PLTR", "SNOW", "NOW", "DDOG", "CRWV"]}
TAX = 0.21


def fetch():
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    key = os.environ["FMP_API_KEY"]
    base = "https://financialmodelingprep.com/stable"
    get = lambda path, **q: requests.get(f"{base}/{path}", params={**q, "apikey": key}, timeout=30).json()
    rows = []
    t = get("treasury-rates")[0]
    rows.append({"kind": "risk_free", "name": "US 10-year Treasury yield", "value": t["year10"] / 100, "as_of": t["date"], "source": "FMP /stable/treasury-rates (US Treasury par curve)"})
    erp = next(r for r in get("market-risk-premium") if r["country"] == "United States")
    import datetime as _dt
    rows.append({"kind": "erp", "name": "US total equity risk premium", "value": erp["totalEquityRiskPremium"] / 100, "as_of": f"undated in source; fetched {_dt.date.today().isoformat()}", "source": "FMP /stable/market-risk-premium (country table, no as-of date)"})
    for group, syms in PEERS.items():
        for s in syms:
            p = get("profile", symbol=s)[0]
            bs = get("balance-sheet-statement", symbol=s, limit=1)
            debt = (bs[0].get("totalDebt") or 0) if bs else 0
            mc = p["marketCap"]
            bu = p["beta"] / (1 + (1 - TAX) * debt / mc) if p.get("beta") else None
            rows.append({"kind": "peer", "name": s, "group": group, "company": p["companyName"], "beta_levered": p.get("beta"), "market_cap": mc, "total_debt": debt,
                         "debt_to_equity": debt / mc, "beta_unlevered": bu, "as_of": bs[0]["date"] if bs else "", "source": "FMP /stable/profile + balance-sheet-statement"})
    df = pd.DataFrame(rows)
    df.to_csv(CACHE, index=False)
    return df


def load(refresh=False):
    return fetch() if refresh or not CACHE.exists() else pd.read_csv(CACHE)


def rates(lease_rates, lease_liabs, refresh=False):
    """lease_rates/lease_liabs: dicts {'operating': .., 'finance': ..} from the filing."""
    df = load(refresh)
    rf = float(df.loc[df.kind == "risk_free", "value"].iloc[0])
    erp = float(df.loc[df.kind == "erp", "value"].iloc[0])
    peers = df[df.kind == "peer"].dropna(subset=["beta_unlevered"])
    beta = float(peers.beta_unlevered.median())
    by_group = peers.groupby("group").beta_unlevered.median().to_dict()
    r_pay = sum(lease_rates[k] * lease_liabs[k] for k in lease_rates) / sum(lease_liabs.values())
    return {"rf": rf, "erp": erp, "beta_u": beta, "beta_u_by_group": by_group, "beta_u_range": (float(peers.beta_unlevered.min()), float(peers.beta_unlevered.max())),
            "r_rev": rf + beta * erp, "r_pay": r_pay, "as_of": str(df.loc[df.kind == "risk_free", "as_of"].iloc[0]), "peers": peers}


if __name__ == "__main__":
    df = load(refresh="--refresh" in sys.argv)
    pd.set_option("display.width", 200)
    print(df.drop(columns=["source"]).round(3).to_string())
    peers = df[df.kind == "peer"]
    print("median unlevered beta:", round(peers.beta_unlevered.median(), 3), dict(peers.groupby("group").beta_unlevered.median().round(3)))
