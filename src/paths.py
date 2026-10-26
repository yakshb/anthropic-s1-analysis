"""Every location the project reads or writes, relative to the repository root, so scripts run from any directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_MODEL = ROOT / "data" / "model"   # written by s1_economics.py and s1_hurdle.py
DATA_JEV = ROOT / "data" / "jev"       # written by s1_jev_reading.py and s1_role_passages.py
WEB = ROOT / "web"                     # the report's stylesheet and scripts
DOCS = ROOT / "docs"                   # the built report, served by GitHub Pages
BUILD = ROOT / "build"                 # git-ignored build byproducts
# Keys: .env.local at the repo root (git-ignored; copy from .env.example), or one folder above the repo.
ENV_FILE = next((p for p in (ROOT / ".env.local", ROOT.parent / ".env.local") if p.exists()), ROOT / ".env.local")
# SEC filings are cached locally (git-ignored). A cache in the folder above the repo is reused if one exists.
CACHE = next((p for p in (ROOT / "edgar_cache", ROOT.parent / "edgar_cache") if p.exists()), ROOT / "edgar_cache")

for _d in (DATA_MODEL, DATA_JEV, DOCS, BUILD):
    _d.mkdir(parents=True, exist_ok=True)
