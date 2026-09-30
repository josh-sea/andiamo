"""
Weekly quant research session. The agent picks questions from its agenda, the trader's
requests and the latest scans; writes and runs Python against the price store; saves
reusable tools to its library; proposes signals to the promotion gate; and publishes a notebook.
"""

import json
import os
import re
import shutil
from datetime import datetime, timezone

import anthropic

from bot.config import ANTHROPIC_API_KEY, ASSETS_DIR, DOCS_DIR
from bot.investigator import TOOLS as RESEARCH_TOOLS, _dispatch_tool as research_dispatch, run_agent_loop
from bot.lab import signals
from bot.lab.data import META_PATH
from bot.lab.sandbox import LAB_DIR, Sandbox, load_library_index, save_to_library

NOTEBOOK_DIR = os.path.join(LAB_DIR, "notebook")
AGENDA_PATH = os.path.join(LAB_DIR, "agenda.json")
FIGURES_DOCS_DIR = os.path.join(DOCS_DIR, "lab", "figures")

SYSTEM_PROMPT = """You are the quantitative research lab of Andiamo, an autonomous trading system.
You work like a careful quant researcher: form a hypothesis, test it on data, report what you found — including null results.

Your environment:
- run_python executes Python in a sandbox. Every cell starts with `from andiamo_lab import *`, giving you:
  np, pd, plt, quant (toolkit), load_prices(symbols, field='close'|'open'|'high'|'low'|'volume', start, end),
  load_returns(...), universe('sp500'|'etf'|'all'), sectors(), scans() (Andiamo's daily research leads as a DataFrame),
  save_figure(name) (publishes the current matplotlib figure in your notebook), holdout_start().
- quant has: returns, zscore, bollinger, rsi, momentum, realized_vol, ols, multi_regression (rolling too), rolling_beta,
  factor_model (PCA), index_decomposition (lasso), lead_lag, lead_lag_matrix, granger, cointegration, find_pairs,
  half_life, spectrum (FFT), spectral_significance (surrogate test), event_study, normalize_weights, backtest, perf_stats.
  Use help(quant.<fn>) to read docstrings. numpy, pandas, scipy, statsmodels, scikit-learn and matplotlib are installed.
- Your library: `from library import <module>` loads code you saved in past sessions. Save anything reusable with save_to_library.
- Files you write in the working directory persist across cells within this session.
- The price data you can see ENDS at the holdout start. The most recent ~year is hidden from you on purpose: it is used
  to judge signals you propose. This protects you from fooling yourself.

Discipline:
- Many tests on the same data will produce false positives. Prefer economically motivated hypotheses, report how many
  variants you tried, and be skeptical of anything that only works for one parameter choice.
- Frequency-domain structure in prices is usually noise — test significance (spectral_significance) before believing a cycle.
- A signal must be tradeable: daily close-to-close, 5bp costs per unit turnover, weights decided with data up to that day.
- Print compact summaries, not huge frames. Plot when a picture helps and save it with save_figure.

To propose a signal, call propose_signal with code defining:
    def signal(prices):  # prices: DataFrame of closes for your UNIVERSE, dates x symbols
        ...               # return DataFrame of target weights, same index/columns; gross exposure is capped at 1
Only use data up to each row's date (rolling windows, .shift(k) with k>0). Anything that peeks ahead is rejected.
The gate: in-sample Sharpe ≥ 0.5, holdout Sharpe ≥ 0.5, holdout drawdown better than -25%, at least 2 years in-sample.
Promoted signals are shown to the portfolio manager daily and retired automatically if their live record decays."""

LAB_TOOLS = [
    {
        "name": "run_python",
        "description": "Execute Python in the lab sandbox and return stdout/stderr",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "save_to_library",
        "description": "Save a reusable Python module to your library for future sessions (functions, not scripts)",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "snake_case module name"},
                "description": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["name", "description", "code"],
        },
    },
    {
        "name": "propose_signal",
        "description": "Submit a trading signal to the promotion gate (lookahead check + holdout backtest). Returns the verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string", "description": "What it trades and why, in plain English"},
                "hypothesis": {"type": "string", "description": "The economic reason it should work"},
                "universe": {"type": "array", "items": {"type": "string"}},
                "code": {"type": "string", "description": "Python defining signal(prices) -> weights DataFrame"},
            },
            "required": ["name", "description", "hypothesis", "universe", "code"],
        },
    },
    {
        "name": "read_notebook",
        "description": "Read a past lab notebook entry (YYYY-MM-DD)",
        "input_schema": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
    },
    {
        "name": "read_signal_code",
        "description": "Read the code of a signal in the registry",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
]


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _read(path: str) -> str:
    return open(path).read() if os.path.exists(path) else ""


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class LabSession:
    def __init__(self):
        self.sandbox = Sandbox(research=True)
        self.proposals: list[dict] = []

    def dispatch(self, name: str, inputs: dict) -> str:
        if name == "run_python":
            rc, out = self.sandbox.run(inputs["code"])
            return out if rc == 0 else f"[exit {rc}]\n{out}"
        if name == "save_to_library":
            return save_to_library(self.sandbox, inputs["name"], inputs["code"], inputs["description"])
        if name == "propose_signal":
            entry = signals.propose(inputs["name"], inputs["description"], inputs["hypothesis"],
                                    inputs["universe"], inputs["code"])
            self.proposals.append(entry)
            view = {k: v for k, v in entry.items() if k not in ("evaluation",)}
            if entry.get("evaluation"):
                ev = entry["evaluation"]
                view["results"] = {k: ev[k] for k in ("insample", "holdout", "lookahead_max_diff")}
            return json.dumps(view, indent=2, default=str)
        if name == "read_notebook":
            return _read(os.path.join(NOTEBOOK_DIR, f"{inputs['date']}.md")) or "No entry for that date."
        if name in ("get_price_history", "get_account_status"):
            return "Not available in the lab: live prices would reveal the holdout year."
        if name == "read_signal_code":
            safe = re.sub(r"[^a-z0-9_]", "", inputs["name"])
            return _read(os.path.join(signals.SIGNALS_DIR, f"{safe}.py")) or "No such signal."
        return research_dispatch(name, inputs)


def _briefing(sandbox: Sandbox) -> str:
    from bot.trader import DIRECTIVES_PATH, _load_json as tl

    agenda = _load_json(AGENDA_PATH, {})
    trader = tl(DIRECTIVES_PATH, {})
    meta = _load_json(META_PATH, {})
    library = load_library_index()
    registry = signals.load_registry()

    notebooks = sorted(f for f in os.listdir(NOTEBOOK_DIR) if f.endswith(".md"))[-3:] if os.path.exists(NOTEBOOK_DIR) else []
    past = "\n\n".join(_read(os.path.join(NOTEBOOK_DIR, f)).split("## Session log")[0][:3000] for f in notebooks)

    scan_bits = []
    for fname in sorted(f for f in os.listdir(ASSETS_DIR) if f.startswith("scan-"))[-5:]:
        m = re.search(r"```json\s*(\{.*\})\s*```", _read(os.path.join(ASSETS_DIR, fname)), re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                data = data.get("scan", data) if isinstance(data.get("scan"), dict) else data
                titles = "; ".join(str(l.get("title") or l.get("headline")) for l in data.get("leads", []) if isinstance(l, dict))
                scan_bits.append(f"- {fname[5:-3]}: {titles}")
            except json.JSONDecodeError:
                pass

    reg_lines = "\n".join(
        f"- {n} [{e.get('status')}] {e.get('description', '')[:140]}"
        + (f" — reasons: {'; '.join(e.get('reasons', []))[:200]}" if e.get("reasons") else "")
        for n, e in registry.items()
    )
    lib_lines = "\n".join(f"- library.{n}: {v['description'][:150]}" for n, v in library.items())

    return f"""LAB SESSION — {_today()}

Price store: {meta.get('symbols', '?')} symbols, {meta.get('first_date', '?')} → {meta.get('last_date', '?')}.
Your visible data ends before the holdout start: {sandbox.holdout}.

## Your open research agenda
{json.dumps(agenda.get('next_questions', []), indent=2) or '(empty — first session)'}

## Requests from the portfolio manager
{json.dumps(trader.get('lab_requests', []), indent=2) or '(none)'}
Research directives the PM gave the news desk (may suggest quant questions too):
{json.dumps(trader.get('directives', []), indent=2)}

## Recent research scan headlines
{chr(10).join(scan_bits) or '(none)'}

## Signal registry (every signal ever proposed)
{reg_lines or '(empty)'}

## Your library
{lib_lines or '(empty — build it up)'}

## Your recent notebooks
{past or '(none)'}

---

Run a focused session: pick 2–4 questions worth answering, test them properly, and propose signals only when the
evidence supports it. Leave the library better than you found it.

End with a JSON block wrapped in ```json ... ```:
{{
  "headline": "one line",
  "summary": "a paragraph a portfolio manager would want to read",
  "experiments": [{{"title": "...", "question": "...", "method": "...", "finding": "...", "conclusion": "...",
                     "confidence": "low|medium|high", "figures": ["name.png"]}}],
  "notes_for_trader": ["actionable observations about current markets, with numbers"],
  "next_questions": ["what to research next session and why"]
}}"""


def _extract_json(text: str) -> dict:
    for block in reversed(re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    return {}


def _save(lab: LabSession, result: dict, full_text: str):
    today = _today()
    os.makedirs(NOTEBOOK_DIR, exist_ok=True)
    os.makedirs(FIGURES_DOCS_DIR, exist_ok=True)

    published = {}
    for fig in lab.sandbox.figures():
        dest = f"{today}-{fig}"
        shutil.copy(os.path.join(lab.sandbox.fig_dir, fig), os.path.join(FIGURES_DOCS_DIR, dest))
        published[fig] = dest

    exp_md = ""
    for e in result.get("experiments") or []:
        figs = "\n".join(f"![{f}](figures/{published[f]})" for f in e.get("figures") or [] if f in published)
        exp_md += (f"\n### {e.get('title', 'Experiment')}\n*Confidence: {e.get('confidence', '?')}*\n\n"
                   f"**Question:** {e.get('question', '')}\n\n**Method:** {e.get('method', '')}\n\n"
                   f"**Finding:** {e.get('finding', '')}\n\n**Conclusion:** {e.get('conclusion', '')}\n\n{figs}\n")
    unreferenced = [d for f, d in published.items()
                    if not any(f in (e.get("figures") or []) for e in result.get("experiments") or [])]
    if unreferenced:
        exp_md += "\n### Other figures\n" + "\n".join(f"![{d}](figures/{d})" for d in unreferenced) + "\n"

    props = "\n".join(
        f"- **{p['name']}** — {p.get('status', '').upper()}"
        + (f": {'; '.join(p.get('reasons') or [])}" if p.get("reasons") else "")
        for p in lab.proposals
    ) or "None this session."
    notes = "\n".join(f"- {n}" for n in result.get("notes_for_trader") or []) or "—"
    nxt = "\n".join(f"- {q}" for q in result.get("next_questions") or []) or "—"

    entry = f"""# {result.get('headline') or f'Lab session {today}'}
*Date: {today} · {lab.sandbox.cells} code cells run · {len(lab.proposals)} signals proposed*

## Summary
{result.get('summary', '')}

## Experiments
{exp_md or 'No experiments recorded.'}

## Signals proposed
{props}

## Notes for the portfolio manager
{notes}

## Next questions
{nxt}

## Session log
{full_text.strip()}
"""
    with open(os.path.join(NOTEBOOK_DIR, f"{today}.md"), "w") as f:
        f.write(entry)
    with open(AGENDA_PATH, "w") as f:
        json.dump({"date": today, "next_questions": result.get("next_questions") or [],
                   "notes_for_trader": result.get("notes_for_trader") or []}, f, indent=2)


def run_session(max_turns: int = 80, verbose: bool = True) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    lab = LabSession()
    messages = [{"role": "user", "content": _briefing(lab.sandbox)}]
    # No live price tools: they would reveal the holdout year
    research = [t for t in RESEARCH_TOOLS if t["name"] not in ("get_price_history", "get_account_status")]
    full_text = run_agent_loop(client, SYSTEM_PROMPT, research + LAB_TOOLS, lab.dispatch,
                               messages, max_turns, verbose)
    result = _extract_json(full_text)
    _save(lab, result, full_text)
    return {"result": result, "proposals": lab.proposals, "cells": lab.sandbox.cells}
