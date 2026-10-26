"""Parity check: the dashboard's JavaScript model (s1_model.js) against the Python model in s1_economics.py."""
import json
import subprocess
from pathlib import Path

import numpy as np

import s1_economics as E
from paths import WEB

HERE = Path(__file__).resolve().parent
cases = []
for toggles in ({}, {"cancelable": True, "vendor_conditional": True}, {"estimates": True}):
    sched, _ = E.scope_sched(toggles)
    for over in ({"u": 0.5}, {"u": 0.9, "demand_on": True, "demand_g": 0.0}, {"u": 0.7, "k_drift": -0.1, "rate_rev": 0.15, "rate_premium": 0.03}, {"u": 0.9, "demand_on": True, "demand_g": 0.8, "revolver_in_cash": True}, {"u": 1.0, "train_end": 0.3, "ramp_year": 2028, "opex_pct": 0.25, "loss_share": 0.21, "loss_year": 2027.5, "rate_pay": 0.06}):
        p = dict(E.BASE, **over)
        py = E.model(p, sched)
        cases.append({"p": p, "sched": list(map(float, sched)), "py": {"npv": py["npv"], "min_cash": py["min_cash"], "R": list(map(float, py["R"])), "mult": E.solve_mult(p, sched), "dem": E.solve_demand(p, sched, 5.0)}})
js = f"""
const M = require({json.dumps(str(WEB / 's1_model.js'))});
const cases = {json.dumps(cases)};
const years = {json.dumps(E.YEARS)};
console.log(JSON.stringify(cases.map(c => {{ const r = M.model(c.p, c.sched, years); return {{npv: r.npv, min_cash: r.min_cash, R: r.R, mult: M.solveMult(c.p, c.sched, years), dem: M.solveDemand(c.p, c.sched, years, 5.0)}}; }})).replace(/null/g, "null"));
"""
res = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
worst = 0.0
for c, r in zip(cases, res):
    nan = lambda x: x is None or (isinstance(x, float) and np.isnan(x))
    pairs = [(c["py"][k], r[k]) for k in ("npv", "min_cash", "mult")] + [(c["py"]["dem"][k], r["dem"][k]) for k in ("g_npv", "g_cash", "g_both")]
    for a, b in pairs:
        assert nan(a) == nan(b), f"NaN mismatch: {a} vs {b}"
        if not nan(a):
            worst = max(worst, abs(a - b))
    worst = max(worst, float(np.max(np.abs(np.array(c["py"]["R"]) - np.array(r["R"])))))
print(f"{len(cases)} cases; largest absolute difference between Python and JavaScript: {worst:.2e}")
assert worst < 1e-6, "JavaScript model diverges from the Python model"
