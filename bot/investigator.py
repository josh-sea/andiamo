"""
The main agentic investigator. Given a hypothesis or topic, it:
1. Plans what to investigate
2. Pulls data from Alpaca, Reddit, web search
3. Runs lookback analysis (date-filtered evidence)
4. Validates against subsequent price/event history
5. Updates the brain knowledge graph
6. Returns a structured report
"""

import json
from datetime import datetime, timedelta
from typing import Optional
import anthropic

from bot.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import bot.brain as brain
from bot.sources import alpaca, reddit, web


SYSTEM_PROMPT = """You are Andiamo, an agentic financial research bot. You think like a disciplined analyst:
- You distill hypotheses to their testable core
- You pull real data and compare to the narrative
- You are skeptical — you look for what the thesis gets wrong as hard as what it gets right
- You identify historical parallels and structural patterns
- You connect current theses to prior ones you've researched
- You rate confidence numerically (0–100) and flag uncertainty honestly
- You write in clear, dense prose — no filler, no cheerleading
- You ALWAYS look at the base rate: how often does this pattern actually play out?

Your output is always structured JSON for the caller to process."""

TOOLS = [
    {
        "name": "search_web",
        "description": "Search the web via DuckDuckGo for articles, analysis, commentary",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
                "time_filter": {"type": "string", "description": "d=day, w=week, m=month, y=year, null=all time"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_news",
        "description": "Search recent news headlines and summaries",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 15},
                "time_filter": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "Fetch and extract the text content of a specific URL",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "search_reddit",
        "description": "Search Reddit posts across finance subreddits",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "subreddits": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 15},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_price_history",
        "description": "Get historical OHLCV bars for a stock/ETF symbol from Alpaca",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, optional"},
                "timeframe": {"type": "string", "default": "1Day"},
            },
            "required": ["symbol", "start_date"],
        },
    },
    {
        "name": "get_account_status",
        "description": "Get current paper trading account equity, cash, and open positions",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_brain",
        "description": "Read an existing thesis or the knowledge index from the brain",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Thesis slug or 'index' for the full index"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "list_theses",
        "description": "List all theses currently in the knowledge graph",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _dispatch_tool(name: str, inputs: dict) -> str:
    try:
        if name == "search_web":
            results = web.ddg_search(inputs["query"], inputs.get("max_results", 10), inputs.get("time_filter"))
            return json.dumps(results[:8], indent=2)

        elif name == "search_news":
            results = web.ddg_news(inputs["query"], inputs.get("max_results", 15), inputs.get("time_filter"))
            return json.dumps(results[:10], indent=2)

        elif name == "fetch_page":
            text = web.fetch_page_text(inputs["url"], max_chars=6000)
            return text

        elif name == "search_reddit":
            posts = reddit.search_reddit(inputs["query"], inputs.get("subreddits"), inputs.get("limit", 15))
            return json.dumps(posts[:10], indent=2)

        elif name == "get_price_history":
            start = datetime.strptime(inputs["start_date"], "%Y-%m-%d")
            end = datetime.strptime(inputs["end_date"], "%Y-%m-%d") if inputs.get("end_date") else None
            df = alpaca.get_bars(inputs["symbol"], start, end, inputs.get("timeframe", "1Day"))
            summary = alpaca.summarize_bars(df, inputs["symbol"])
            if not df.empty:
                tail = df.tail(10)[["open", "high", "low", "close", "volume"]].to_string()
                return f"{summary}\n\nRecent bars:\n{tail}"
            return summary

        elif name == "get_account_status":
            acct = alpaca.get_account()
            positions = alpaca.get_positions()
            return json.dumps({"account": acct, "positions": positions}, indent=2)

        elif name == "read_brain":
            slug = inputs["slug"]
            if slug == "index":
                idx_path = __import__("os").path.join(__import__("bot.config", fromlist=["BRAIN_DIR"]).BRAIN_DIR, "index.md")
                if __import__("os").path.exists(idx_path):
                    with open(idx_path) as f:
                        return f.read()
                return "Brain index not yet created."
            content = brain.get_thesis(slug)
            return content if content else f"No thesis found with slug: {slug}"

        elif name == "list_theses":
            theses = brain.list_theses()
            return json.dumps(theses, indent=2)

    except Exception as e:
        return f"[tool error: {e}]"

    return "[unknown tool]"


def investigate(
    hypothesis: str,
    mode: str = "full",  # full | lookback | validate | scan
    lookback_date: Optional[str] = None,
    max_turns: int = 20,
    verbose: bool = True,
) -> dict:
    """
    Run an investigation. Returns a structured result dict.

    mode:
      full      - full investigation + write to brain
      lookback  - analyze hypothesis as if it were the given date
      validate  - find an existing thesis and check how it played out
      scan      - surface scan for interesting signals (no deep dive)
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = []

    if mode == "lookback" and lookback_date:
        user_content = f"""LOOKBACK ANALYSIS — Date filter: {lookback_date}

Hypothesis: {hypothesis}

Investigate this thesis as if today were {lookback_date}. Only use evidence that would have been available on or before that date. Then separately, look ahead and assess: how did this actually play out? What was the outcome?

Produce a structured analysis with sections: Evidence (date-filtered), Verdict (as of {lookback_date}), Actual Outcome, Accuracy Assessment."""
    elif mode == "validate":
        user_content = f"""VALIDATION RUN

Find the thesis matching: "{hypothesis}"
Check the brain index for it, then look at what has happened since it was written. Pull price data, recent news, Reddit sentiment. Was the thesis correct? Partially correct? Completely wrong?

Update the verdict with a clear VALIDATED / INVALIDATED / MIXED + explanation."""
    elif mode == "scan":
        user_content = f"""SURFACE SCAN

Scan for interesting financial signals and emerging narratives around: {hypothesis}
Check Reddit, news, web. Identify 3–5 most interesting leads worth investigating further. Rate each by signal strength. Do not deep-dive — just surface."""
    else:
        user_content = f"""FULL INVESTIGATION

Hypothesis: {hypothesis}

Run a complete investigation:
1. Distill the core testable claim
2. Search web, news, Reddit for evidence + counterevidence
3. Pull relevant price history from Alpaca for any tickers involved
4. Look for historical parallels — similar setups, how they resolved
5. Check the brain for connected prior theses
6. Build a structured thesis: bull case, bear case, base case, confidence 0–100
7. Identify what data would change your mind
8. Suggest any paper trade position if conviction is high enough (>65 confidence)

At the end, output a JSON block wrapped in ```json ... ``` with:
{{
  "title": "...",
  "hypothesis": "...",
  "verdict": "bullish|bearish|neutral|mixed",
  "confidence": 0-100,
  "tickers": [...],
  "tags": [...],
  "summary": "2-3 sentence summary",
  "bull_case": "...",
  "bear_case": "...",
  "key_risks": [...],
  "suggested_trade": null or {{"symbol": "...", "side": "buy|sell", "qty": ..., "rationale": "..."}},
  "connections": [...]
}}"""

    messages.append({"role": "user", "content": user_content})

    full_text = ""
    structured = {}

    for turn in range(max_turns):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        tool_calls = []
        text_parts = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        turn_text = "\n".join(text_parts)
        full_text += turn_text + "\n"

        if verbose and turn_text.strip():
            print(f"\n[turn {turn+1}] {turn_text[:300]}{'...' if len(turn_text) > 300 else ''}")

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if tool_calls:
            tool_results = []
            for tc in tool_calls:
                if verbose:
                    print(f"  -> {tc.name}({json.dumps(tc.input)[:120]})")
                result = _dispatch_tool(tc.name, tc.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": str(result)[:6000],
                })
            messages.append({"role": "user", "content": tool_results})

    # Extract structured JSON if present
    import re
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", full_text, re.DOTALL)
    if json_match:
        try:
            structured = json.loads(json_match.group(1))
        except Exception:
            pass

    return {
        "hypothesis": hypothesis,
        "mode": mode,
        "full_text": full_text,
        "structured": structured,
        "timestamp": datetime.utcnow().isoformat(),
    }


def run_and_save(
    hypothesis: str,
    mode: str = "full",
    lookback_date: Optional[str] = None,
    paper_trade: bool = False,
    verbose: bool = True,
) -> dict:
    result = investigate(hypothesis, mode=mode, lookback_date=lookback_date, verbose=verbose)
    s = result.get("structured", {})

    if mode in ("full", "lookback") and s.get("title"):
        slug = brain.save_thesis(
            title=s["title"],
            content=result["full_text"],
            tags=s.get("tags", []),
            status="open",
        )
        result["brain_slug"] = slug
        brain.save_asset(slug, f"Hypothesis: {hypothesis}\n\nTimestamp: {result['timestamp']}")

    elif mode == "scan":
        # Save scan digest as an asset so there's always something to commit
        from datetime import date as _date
        scan_slug = f"scan-{_date.today().isoformat()}"
        brain.save_asset(scan_slug, f"# Scan: {hypothesis[:80]}\n\n{result['full_text']}")
        brain._rebuild_index()
        result["brain_slug"] = scan_slug

    elif mode == "validate" and s.get("title"):
        import re as _re
        thesis_slug = _re.sub(r"[^a-z0-9]+", "-", s["title"].lower()).strip("-")[:60]
        verdict = s.get("verdict", "mixed")
        slug = brain.save_validation(thesis_slug, result["full_text"], verdict)
        result["validation_slug"] = slug

    # Check for connections to existing theses
    if s.get("connections"):
        brain.save_connection(
            title=f"Connections from: {s.get('title', hypothesis[:40])}",
            thesis_slugs=s["connections"],
            content=f"Auto-detected connections during investigation of: {hypothesis}\n\n{s.get('summary', '')}",
        )

    # Paper trade if suggested and enabled
    if paper_trade and s.get("suggested_trade"):
        trade = s["suggested_trade"]
        if trade and s.get("confidence", 0) >= 65:
            try:
                order = alpaca.place_order(trade["symbol"], trade["qty"], trade["side"])
                result["order"] = order
                if verbose:
                    print(f"\n[paper trade] {trade['side'].upper()} {trade['qty']} {trade['symbol']}: {order}")
            except Exception as e:
                result["order_error"] = str(e)
                if verbose:
                    print(f"\n[paper trade error] {e}")

    return result
