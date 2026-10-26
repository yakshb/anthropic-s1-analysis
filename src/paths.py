"""Every location the project reads or writes, relative to the repository root, so scripts run from any directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_MODEL = ROOT / "data" / "model"   # written by s1_economics.py and s1_hurdle.py
DATA_JEV = ROOT / "data" / "jev"       # written by the Jev notebook and s1_role_passages.py
NOTEBOOKS = ROOT / "notebooks"
WEB = ROOT / "web"                     # the report's stylesheet and scripts
DOCS = ROOT / "docs"                   # the built report, served by GitHub Pages
BUILD = ROOT / "build"                 # git-ignored build byproducts
ENV_FILE = ROOT / ".env.local"         # git-ignored; copy from .env.example
# SEC filings are cached locally (git-ignored). A cache in the folder above the repo is reused if one exists.
CACHE = next((p for p in (ROOT / "edgar_cache", ROOT.parent / "edgar_cache") if p.exists()), ROOT / "edgar_cache")

for _d in (DATA_MODEL, DATA_JEV, DOCS, BUILD):
    _d.mkdir(parents=True, exist_ok=True)
