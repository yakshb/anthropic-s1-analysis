// Reverse-DCF on Anthropic's contracted compute. Mirror of model() in s1_economics.py (checked by s1_check_model.py).
// p: parameters; sched: annual compute payments ($B) for YEARS; years: array of calendar years (2026 = H2 only).
const S1MODEL = (() => {
  const T0 = 2026.5;
  function model(p, sched, years) {
    const n = years.length, out = {C: [], train: [], S: [], k: [], R: [], util: [], gp_serving: [], fcf: [], cash: [], breakeven_R: []};
    let pvRev = 0, pvPay = 0, cash = p.liquidity + (p.revolver_in_cash ? p.revolver : 0), minCash = Infinity, minYear = years[0];
    const span = Math.max(p.ramp_year + 0.5 - T0, 0.25);
    for (let i = 0; i < n; i++) {
      const y = years[i], frac = y === 2026 ? 0.5 : 1.0, mid = y === 2026 ? 0.25 : y - T0 + 0.5;
      const C = sched[i];
      const t = Math.min(Math.max((y + (y === 2026 ? 0.75 : 0.5) - T0) / span, 0), 1);
      const train = p.train_start + (p.train_end - p.train_start) * t;
      const S = C * (1 - train);
      const k = p.k_obs * (1 - p.policy_share) / p.u_obs * Math.pow(1 + p.k_drift, Math.max(y + 0.5 - T0 - 0.5, 0)) * p.k_mult;
      const cap = S * k * p.u;
      let R = cap;
      if (p.demand_on) R = Math.min(cap, p.q2_run_rate * (1 - p.policy_share) * Math.pow(1 + p.demand_g, Math.max(y - 2026, 0)) * frac);
      R = R * (1 - p.loss_share * Math.min(Math.max(y + 1 - p.loss_year, 0), 1));
      const util = S * k > 0 ? R / (S * k) : 0;
      const ebit = R - C - p.opex_pct * R, tax = p.tax * Math.max(ebit, 0);
      const fcf = ebit - tax;
      pvRev += (R - p.opex_pct * R - tax) * Math.pow(1 + p.rate_rev + p.rate_premium, -mid);
      pvPay += C * Math.pow(1 + p.rate_pay, -mid);
      cash += fcf;
      if (cash < minCash) { minCash = cash; minYear = y; }
      out.C.push(C); out.train.push(train); out.S.push(S); out.k.push(k); out.R.push(R); out.util.push(util);
      out.gp_serving.push(R - S); out.fcf.push(fcf); out.cash.push(cash); out.breakeven_R.push(C / (1 - p.opex_pct));
    }
    out.npv = pvRev - pvPay; out.pv_rev = pvRev; out.pv_pay = pvPay; out.min_cash = minCash; out.min_cash_year = minYear;
    return out;
  }
  // NaN when no multiple in [0, 20] reaches NPV = 0 (e.g. revenue capped by demand): callers must report "no break-even"
  function solveMult(p, sched, years) {
    let lo = 0, hi = 20;
    if (model(Object.assign({}, p, {k_mult: hi}), sched, years).npv <= 0) return NaN;
    if (model(Object.assign({}, p, {k_mult: lo}), sched, years).npv > 0) return lo;
    for (let i = 0; i < 80; i++) {
      const m = (lo + hi) / 2;
      if (model(Object.assign({}, p, {k_mult: m}), sched, years).npv > 0) hi = m; else lo = m;
    }
    return (lo + hi) / 2;
  }
  // lowest constant demand growth from the Q2 2026 run-rate giving NPV >= 0, and separately cash >= covenant every year
  function solveDemand(p, sched, years, covenant, lo = -0.5, hi = 5.0) {
    const q = Object.assign({}, p, {demand_on: true, k_mult: 1.0});
    const solve = ok => {
      if (!ok(hi)) return NaN;
      if (ok(lo)) return lo;
      let a = lo, b = hi;
      for (let i = 0; i < 60; i++) { const m = (a + b) / 2; if (ok(m)) b = m; else a = m; }
      return b;
    };
    const g_npv = solve(g => model(Object.assign({}, q, {demand_g: g}), sched, years).npv >= 0);
    const g_cash = solve(g => model(Object.assign({}, q, {demand_g: g}), sched, years).min_cash >= covenant);
    return {g_npv, g_cash, g_both: (isNaN(g_npv) || isNaN(g_cash)) ? NaN : Math.max(g_npv, g_cash)};
  }
  return {model, solveMult, solveDemand};
})();
if (typeof module !== "undefined") module.exports = S1MODEL;
