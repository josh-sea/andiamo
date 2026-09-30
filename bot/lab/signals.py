"""
Signal registry and promotion gate.

A signal is a module in brain/lab/signals/<name>.py defining UNIVERSE (list of symbols)
and signal(prices) -> DataFrame of target weights (dates x symbols) using only data up to
each date. It is promoted only if it passes a lookahead check and performs out of sample
on the holdout year, net of costs. Promoted signals are re-evaluated daily and retired if
their live record decays.
"""

import json
import os
import re
from datetime import datetime, timezone

from bot.lab.sandbox import LAB_DIR, Sandbox

SIGNALS_DIR = os.path.join(LAB_DIR, "signals")
REGISTRY_PATH = os.path.join(LAB_DIR, "signals.json")
COST_BPS = 5.0

GATE = {
    "min_insample_days": 504,
    "min_insample_sharpe": 0.5,
    "min_holdout_sharpe": 0.5,
    "max_holdout_drawdown": -0.25,
    "min_avg_gross": 0.05,
}
RETIRE = {"min_live_days": 40, "min_live_sharpe": 0.0, "max_live_drawdown": -0.20}

EVAL_SCRIPT = r'''
import importlib.util, json
spec = importlib.util.spec_from_file_location("sig", SIGNAL_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

prices = load_prices(list(mod.UNIVERSE)).dropna(how="all")
prices = prices.loc[:, prices.notna().mean() > 0.5]
raw = mod.signal(prices)
if not isinstance(raw, pd.DataFrame):
    raise TypeError("signal() must return a DataFrame of weights")
cols = [c for c in raw.columns if c in prices.columns]
w = quant.normalize_weights(raw[cols].reindex(prices.index).ffill())

# Lookahead check: recompute on truncated history; past weights must not change
n = len(prices)
max_diff = 0.0
for frac in (0.35, 0.5, 0.65, 0.8, 0.95):
    d = prices.index[int(n * frac)]
    part = mod.signal(prices.loc[:d])
    part = quant.normalize_weights(part.reindex(columns=cols).reindex(prices.loc[:d].index).ffill())
    diff = float((part.iloc[-1].fillna(0) - w.loc[d].fillna(0)).abs().max())
    max_diff = max(max_diff, diff)

bt = quant.backtest(w[cols], prices[cols], cost_bps=COST_BPS)
pnl = bt["pnl"].iloc[1:]
first_active = w.abs().sum(axis=1).gt(0).idxmax()
pnl = pnl[pnl.index > first_active]
insample = pnl[pnl.index < HOLDOUT_START]
holdout = pnl[pnl.index >= HOLDOUT_START]
live = pnl[pnl.index > pd.Timestamp(PROMOTED)] if PROMOTED else pnl.iloc[0:0]
last = w.iloc[-1]
last = last[last.abs() > 1e-4].sort_values(key=abs, ascending=False)
eq = (1 + pnl).cumprod()
result = {
    "lookahead_max_diff": max_diff,
    "insample": quant.perf_stats(insample) | {"avg_gross": float(w.loc[insample.index].abs().sum(axis=1).mean()) if len(insample) else 0.0},
    "holdout": quant.perf_stats(holdout),
    "full": bt["stats"],
    "live": quant.perf_stats(live),
    "as_of": str(prices.index[-1].date()),
    "current_weights": {k: round(float(v), 4) for k, v in last.head(20).items()},
    "equity_curve": [[str(d.date()), round(float(v), 4)] for d, v in eq.iloc[::5].items()],
}
with open("eval_result.json", "w") as f:
    json.dump(result, f)
'''


def load_registry() -> dict:
    try:
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_registry(reg: dict):
    os.makedirs(LAB_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(reg, f, indent=2)


def _evaluate(name: str, promoted: str | None = None) -> dict:
    sandbox = Sandbox(research=False)
    path = os.path.join(SIGNALS_DIR, f"{name}.py")
    script = (f"SIGNAL_PATH = {path!r}\nCOST_BPS = {COST_BPS}\nPROMOTED = {promoted!r}\n" + EVAL_SCRIPT)
    rc, out = sandbox.run(script, timeout=900)
    result_path = os.path.join(sandbox.workdir, "eval_result.json")
    if rc != 0 or not os.path.exists(result_path):
        return {"error": out[-3000:]}
    with open(result_path) as f:
        return json.load(f)


def _gate(ev: dict) -> list[str]:
    fails = []
    if ev["lookahead_max_diff"] > 1e-6:
        fails.append(f"lookahead: past weights changed when future data was removed (max diff {ev['lookahead_max_diff']:.4f})")
    ins, hold = ev["insample"], ev["holdout"]
    if ins["days"] < GATE["min_insample_days"]:
        fails.append(f"only {ins['days']} in-sample days (need {GATE['min_insample_days']})")
    if ins["sharpe"] < GATE["min_insample_sharpe"]:
        fails.append(f"in-sample Sharpe {ins['sharpe']:.2f} < {GATE['min_insample_sharpe']}")
    if hold["sharpe"] < GATE["min_holdout_sharpe"]:
        fails.append(f"holdout Sharpe {hold['sharpe']:.2f} < {GATE['min_holdout_sharpe']}")
    if hold["max_drawdown"] < GATE["max_holdout_drawdown"]:
        fails.append(f"holdout drawdown {hold['max_drawdown']:.1%} worse than {GATE['max_holdout_drawdown']:.0%}")
    if ins.get("avg_gross", 0) < GATE["min_avg_gross"]:
        fails.append("signal is almost never invested")
    return fails


def propose(name: str, description: str, hypothesis: str, universe: list[str], code: str) -> dict:
    name = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:50]
    if not name or name[0].isdigit():
        return {"status": "error", "reason": "name must be snake_case starting with a letter"}
    reg = load_registry()
    if reg.get(name, {}).get("status") == "promoted":
        return {"status": "error", "reason": f"{name} is already promoted; choose a new name for a variant"}
    os.makedirs(SIGNALS_DIR, exist_ok=True)
    with open(os.path.join(SIGNALS_DIR, f"{name}.py"), "w") as f:
        f.write(f"UNIVERSE = {json.dumps(sorted(set(universe)))}\n\n{code.strip()}\n")

    ev = _evaluate(name)
    today = datetime.now(timezone.utc).date().isoformat()
    entry = {
        "name": name, "description": description, "hypothesis": hypothesis,
        "universe_size": len(set(universe)), "proposed": today,
        "attempts": reg.get(name, {}).get("attempts", 0) + 1,
    }
    if "error" in ev:
        entry.update(status="error", reasons=["signal code failed to run"], error=ev["error"])
    else:
        fails = _gate(ev)
        entry.update(
            status="rejected" if fails else "promoted", reasons=fails, evaluation=ev,
            promoted=None if fails else today,
        )
    reg[name] = entry
    _save_registry(reg)
    return entry


def update_promoted() -> dict:
    """Daily: refresh current weights and live record of promoted signals; retire decayed ones."""
    reg = load_registry()
    today = datetime.now(timezone.utc).date().isoformat()
    for name, entry in reg.items():
        if entry.get("status") != "promoted":
            continue
        ev = _evaluate(name, promoted=entry["promoted"])
        if "error" in ev:
            entry["last_error"] = ev["error"][-1000:]
            continue
        entry["evaluation"] = ev
        entry.pop("last_error", None)
        live = ev["live"]
        if live["days"] >= RETIRE["min_live_days"] and (
            live["sharpe"] < RETIRE["min_live_sharpe"] or live["max_drawdown"] < RETIRE["max_live_drawdown"]
        ):
            entry["status"] = "retired"
            entry["retired"] = today
            entry["reasons"] = [f"live Sharpe {live['sharpe']:.2f}, drawdown {live['max_drawdown']:.1%} after {live['days']} days"]
        print(f"[lab] {name}: {entry['status']} live_days={live['days']} live_sharpe={live['sharpe']:.2f}")
    _save_registry(reg)
    return reg


def trader_briefing() -> str:
    promoted = [e for e in load_registry().values() if e.get("status") == "promoted"]
    if not promoted:
        return "No promoted quant signals yet."
    parts = []
    for e in promoted:
        ev = e["evaluation"]
        weights = ", ".join(f"{k} {v:+.1%}" for k, v in list(ev["current_weights"].items())[:12])
        parts.append(
            f"### {e['name']} (promoted {e['promoted']})\n{e['description']}\n"
            f"Backtest: in-sample Sharpe {ev['insample']['sharpe']:.2f}, holdout Sharpe {ev['holdout']['sharpe']:.2f}, "
            f"holdout max DD {ev['holdout']['max_drawdown']:.1%}. Live since promotion: {ev['live']['days']} days, "
            f"Sharpe {ev['live']['sharpe']:.2f}.\nTarget weights as of {ev['as_of']} (fraction of the signal's capital): {weights or 'flat'}"
        )
    return "\n\n".join(parts)
