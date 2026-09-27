"""
Autonomous paper-trading portfolio manager.

Each session it reads its own strategy, journal, recent scans and account state,
researches as it sees fit, trades, then rewrites its strategy and leaves research
directives that steer the next daily scan.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import anthropic

from bot.config import ANTHROPIC_API_KEY, ASSETS_DIR, BRAIN_DIR
from bot.investigator import TOOLS as RESEARCH_TOOLS, _dispatch_tool as research_dispatch, run_agent_loop
from bot.sources import alpaca

TRADER_DIR = os.path.join(BRAIN_DIR, "trader")
JOURNAL_DIR = os.path.join(TRADER_DIR, "journal")
STRATEGY_PATH = os.path.join(TRADER_DIR, "strategy.md")
STRATEGY_HISTORY_PATH = os.path.join(TRADER_DIR, "strategy_history.md")
DIRECTIVES_PATH = os.path.join(TRADER_DIR, "directives.json")
LEDGER_PATH = os.path.join(TRADER_DIR, "trades.jsonl")
EQUITY_PATH = os.path.join(TRADER_DIR, "equity.json")

SYSTEM_PROMPT = """You are Andiamo, an autonomous portfolio manager running a paper-trading account on Alpaca.
You have complete discretion. There are no position limits, no mandate, and no one approving your trades.
You decide the strategy, the holdings, the sizing, the timing — and you may change your mind.

What you can trade: US stocks and ETFs (including leveraged and inverse ETFs), long or short.
Fractional shares work via notional (dollar) orders on long buys.

How you are judged: growth of the account over months, and the quality of your reasoning in the public record.
Every decision you make is published. Write like a PM whose letters people actually want to read.

Principles you hold yourself to:
- Be bold when you have edge, patient when you don't. Doing nothing is a valid decision.
- Size to conviction, but never so concentrated that one bad call ends the game.
- Every position needs a thesis and an exit condition (what would make you wrong).
- Revisit open positions: is the original thesis still intact? Cut losers that broke thesis; don't marry positions.
- Learn from your own journal — note what worked, what didn't, and adapt your strategy.
- Your research team runs a scan each morning. Use it, question it, and tell it what to dig into next.
- Check prices with get_quote before sizing an order.
"""

TRADING_TOOLS = [
    {
        "name": "get_portfolio",
        "description": "Current account (equity, cash, buying power), open positions with P&L, open orders, and market clock",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_quote",
        "description": "Latest bid/ask for a symbol",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "place_order",
        "description": "Submit a paper order. Provide qty (shares) OR notional (dollars, long buys only). Orders are DAY orders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "qty": {"type": "number"},
                "notional": {"type": "number"},
                "order_type": {"type": "string", "enum": ["market", "limit"], "default": "market"},
                "limit_price": {"type": "number"},
                "rationale": {"type": "string", "description": "Why — this is published in the trade log"},
            },
            "required": ["symbol", "side", "rationale"],
        },
    },
    {
        "name": "close_position",
        "description": "Close all or a percentage of an open position",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "percentage": {"type": "number", "description": "0-100; omit to close fully"},
                "rationale": {"type": "string"},
            },
            "required": ["symbol", "rationale"],
        },
    },
    {
        "name": "cancel_order",
        "description": "Cancel an open order by id",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "read_scan",
        "description": "Read the full research scan for a date (YYYY-MM-DD)",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
    },
    {
        "name": "read_journal",
        "description": "Read your own journal entry for a past date (YYYY-MM-DD)",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
    },
]


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _read(path: str, default: str = "") -> str:
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return default


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_directives() -> list[dict]:
    return _load_json(DIRECTIVES_PATH, {}).get("directives", [])


def _recent_files(directory: str, prefix: str, n: int) -> list[str]:
    if not os.path.exists(directory):
        return []
    names = sorted(f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".md"))
    return names[-n:]


def _portfolio_snapshot() -> dict:
    return {
        "account": alpaca.get_account(),
        "positions": alpaca.get_positions(),
        "open_orders": alpaca.get_open_orders(),
        "clock": alpaca.get_clock(),
    }


class TradingSession:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.actions: list[dict] = []

    def _record(self, kind: str, inputs: dict, order: dict | None = None, error: str | None = None):
        self.actions.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "action": kind,
            "symbol": (inputs.get("symbol") or "").upper(),
            "rationale": inputs.get("rationale", ""),
            "request": {k: v for k, v in inputs.items() if k != "rationale"},
            "order": order,
            "error": error,
        })

    def dispatch(self, name: str, inputs: dict) -> str:
        try:
            if name == "get_portfolio":
                return json.dumps(_portfolio_snapshot(), indent=2)
            if name == "get_quote":
                return json.dumps(alpaca.get_latest_quote(inputs["symbol"].upper()))
            if name == "place_order":
                try:
                    order = alpaca.place_order(
                        inputs["symbol"], inputs["side"],
                        qty=inputs.get("qty"), notional=inputs.get("notional"),
                        order_type=inputs.get("order_type", "market"),
                        limit_price=inputs.get("limit_price"),
                    )
                except Exception as e:
                    self._record("order", inputs, error=str(e))
                    raise
                self._record("order", inputs, order=order)
                return json.dumps(order)
            if name == "close_position":
                try:
                    order = alpaca.close_position(inputs["symbol"], inputs.get("percentage"))
                except Exception as e:
                    self._record("close", inputs, error=str(e))
                    raise
                self._record("close", inputs, order=order)
                return json.dumps(order)
            if name == "cancel_order":
                alpaca.cancel_order(inputs["order_id"])
                return "cancelled"
            if name == "read_scan":
                text = _read(os.path.join(ASSETS_DIR, f"scan-{inputs['date']}.md"))
                return text or f"No scan for {inputs['date']}"
            if name == "read_journal":
                text = _read(os.path.join(JOURNAL_DIR, f"{inputs['date']}.md"))
                return text or f"No journal entry for {inputs['date']}"
        except Exception as e:
            return f"[tool error: {e}]"
        return research_dispatch(name, inputs)

    def refresh_orders(self):
        """Re-fetch submitted orders so the ledger records fills, not just submissions."""
        for a in self.actions:
            if a.get("order") and a["order"].get("id"):
                try:
                    a["order"] = alpaca.get_order(a["order"]["id"])
                except Exception:
                    pass


def _build_briefing(snapshot: dict) -> str:
    today = _today()
    strategy = _read(STRATEGY_PATH, "(No strategy yet — this is your first session. Define one.)")

    journal_bits = []
    for fname in _recent_files(JOURNAL_DIR, "", 5):
        raw = _read(os.path.join(JOURNAL_DIR, fname))
        summary = raw.split("## Full reasoning")[0]
        journal_bits.append(f"### {fname[:-3]}\n{summary[:2500]}")

    scan_bits = []
    for fname in _recent_files(ASSETS_DIR, "scan-", 3):
        raw = _read(os.path.join(ASSETS_DIR, fname))
        m = re.search(r"```json\s*(\{.*\})\s*```", raw, re.DOTALL)
        scan_bits.append(f"### {fname[5:-3]}\n{(m.group(1) if m else raw)[:5000]}")

    equity = _load_json(EQUITY_PATH, [])
    perf = ""
    if equity:
        first = equity[0]
        perf = (f"Inception {first['date']} at ${first['equity']:,.2f}. "
                f"Recent closes: " + ", ".join(f"{e['date']} ${e['equity']:,.0f}" for e in equity[-10:]))

    return f"""TRADING SESSION — {today}

## Account right now
```json
{json.dumps(snapshot, indent=2)}
```

## Performance history
{perf or "No history yet — this is the first session."}

## Your current strategy
{strategy}

## Your recent journal (newest last)
{chr(10).join(journal_bits) or "(empty)"}

## Latest research scans from your team (newest last)
{chr(10).join(scan_bits) or "(none)"}

---

Run your session. Research whatever you need, then act: buy, sell, short, trim, add, or hold.
Every trade must go through the tools — only executed tool calls count.

When done, output a final JSON block wrapped in ```json ... ``` with:
{{
  "headline": "one-line summary of today's session",
  "market_view": "your read on the market today, a short paragraph",
  "decisions": [{{"symbol": "...", "action": "buy|sell|short|cover|trim|add|hold|watch", "reasoning": "...", "exit_condition": "..."}}],
  "lessons": "what your past decisions taught you (or null)",
  "strategy": "your full strategy document in markdown if you are changing it, else null",
  "strategy_change_note": "why you changed it (or null)",
  "research_directives": [{{"topic": "...", "why": "...", "tickers": ["..."]}}]
}}
research_directives are instructions to tomorrow's research scan: what you want investigated next."""


def _extract_json(text: str) -> dict:
    for block in reversed(re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    return {}


def _format_action(a: dict) -> str:
    o = a.get("order") or {}
    req = a["request"]
    size = f"{req['qty']} sh" if req.get("qty") else (f"${req['notional']:,.2f}" if req.get("notional") else
                                                      (f"{req.get('percentage')}%" if req.get("percentage") else "all"))
    if a.get("error"):
        status = f"REJECTED: {a['error']}"
    else:
        fill = f" @ ${o['filled_avg_price']:.2f}" if o.get("filled_avg_price") else ""
        status = f"{o.get('status', '?')}{fill}"
    side = req.get("side", "close")
    return f"- **{side.upper()} {a['symbol']}** ({size}) — {status}. {a['rationale']}"


def _save(session: TradingSession, result: dict, full_text: str, snapshot_after: dict):
    today = _today()
    os.makedirs(JOURNAL_DIR, exist_ok=True)

    with open(LEDGER_PATH, "a") as f:
        for a in session.actions:
            f.write(json.dumps({"date": today, **a}) + "\n")

    equity = [e for e in _load_json(EQUITY_PATH, []) if e["date"] != today]
    acct = snapshot_after["account"]
    equity.append({
        "date": today,
        "equity": acct["equity"],
        "cash": acct["cash"],
        "positions": snapshot_after["positions"],
    })
    with open(EQUITY_PATH, "w") as f:
        json.dump(equity, f, indent=2)

    if result.get("strategy"):
        with open(STRATEGY_PATH, "w") as f:
            f.write(f"*Last revised: {today}*\n\n{result['strategy'].strip()}\n")
        with open(STRATEGY_HISTORY_PATH, "a") as f:
            f.write(f"\n## {today}\n{result.get('strategy_change_note') or 'Revised.'}\n")

    with open(DIRECTIVES_PATH, "w") as f:
        json.dump({"date": today, "directives": result.get("research_directives") or []}, f, indent=2)

    decisions = "\n".join(
        f"- **{d.get('action', '').upper()} {d.get('symbol', '')}** — {d.get('reasoning', '')}"
        + (f" *Exit if:* {d['exit_condition']}" if d.get("exit_condition") else "")
        for d in result.get("decisions") or []
    )
    directives = "\n".join(
        f"- **{d.get('topic', '')}** — {d.get('why', '')}"
        + (f" ({', '.join(d['tickers'])})" if d.get("tickers") else "")
        for d in result.get("research_directives") or []
    )
    executed = "\n".join(_format_action(a) for a in session.actions) or "No trades executed."
    entry = f"""# {result.get('headline') or f'Trading session {today}'}
*Date: {today} · Equity after session: ${acct['equity']:,.2f}*

## Market view
{result.get('market_view') or ''}

## Executed trades
{executed}

## Decisions
{decisions or 'No decisions recorded.'}

## Lessons
{result.get('lessons') or '—'}

## Research directives for tomorrow
{directives or '—'}

## Full reasoning
{full_text.strip()}
"""
    with open(os.path.join(JOURNAL_DIR, f"{today}.md"), "w") as f:
        f.write(entry)


def run_session(max_turns: int = 60, verbose: bool = True) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    session = TradingSession(verbose=verbose)
    snapshot = _portfolio_snapshot()
    messages = [{"role": "user", "content": _build_briefing(snapshot)}]
    full_text = run_agent_loop(
        client, SYSTEM_PROMPT, RESEARCH_TOOLS + TRADING_TOOLS, session.dispatch,
        messages, max_turns, verbose,
    )
    result = _extract_json(full_text)

    if session.actions:
        time.sleep(10)
        session.refresh_orders()
    snapshot_after = _portfolio_snapshot()
    _save(session, result, full_text, snapshot_after)
    return {"result": result, "actions": session.actions, "account": snapshot_after["account"]}
