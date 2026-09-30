# andiamo

Autonomous financial research agent. Investigates market theses, scans Reddit and news, pulls price history from Alpaca, maintains an Obsidian-like markdown knowledge graph, and publishes findings to a GitHub Pages site.

## Setup

1. Copy `.env.example` to `.env` and fill in your keys:
   - `ANTHROPIC_API_KEY` — Claude API key
   - `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — Alpaca paper trading credentials

2. Add the same keys as GitHub Actions secrets (`ANTHROPIC_API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`).

3. Enable GitHub Pages in repo settings → Pages → Source: `docs/` folder on `main` branch.

4. Install deps:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

```bash
# Deep-dive a hypothesis (saves to brain/, rebuilds site)
python -m bot.main investigate "copper supply is being squeezed by EV demand"

# Same but also place paper trade if confidence >= 65
python -m bot.main investigate "copper supply thesis" --trade

# Surface scan — quick signal check, no deep write
python -m bot.main scan "semiconductor sector rotation"

# Lookback — analyze thesis as if it were a past date, then validate against what happened
python -m bot.main lookback "AI chip shortage thesis" --date 2023-06-01

# Validate an existing thesis against current data
python -m bot.main validate "copper supply thesis"

# Run daily digest (top Reddit posts → scan pipeline)
python -m bot.main daily-scan

# Autonomous trading session (reads scans + its own journal, trades, publishes)
python -m bot.main trade

# Update the local price store and re-evaluate promoted signals
python -m bot.main lab-update

# Quant research lab session (writes/runs its own Python, proposes signals)
python -m bot.main lab

# Rebuild the GitHub Pages site manually
python -m bot.main build-site

# Show the knowledge graph index
python -m bot.main show-brain
```

## Automation

- **Daily scan**: GitHub Actions runs at 9am ET weekdays (`daily_scan.yml`). Results committed back to `brain/` and `docs/`.
- **Daily trading session**: runs at 11am ET weekdays (`daily_trade.yml`), after the scan. The trader reads
  the latest scans, its strategy and journal, trades the Alpaca paper account with full discretion, rewrites its
  strategy, and leaves research directives that the next morning's scan prioritizes.
- **Weekly quant lab**: runs Saturdays (`weekly_lab.yml`). The lab writes and runs Python against a local
  daily price store (S&P 500 + ~50 ETFs since 2016), saves reusable tools to its library, and proposes trading
  signals. A signal is promoted only if it passes a lookahead check and clears the gate on the most recent year
  of data, which lab research never sees. Promoted signals are re-evaluated daily before the trading session,
  shown to the trader, and retired automatically if their live record decays.
- **Manual trigger**: Use the `workflow_dispatch` input in GitHub Actions to run a specific hypothesis/mode.
- **GitHub Pages**: Auto-deploys whenever `docs/` changes on `main`.

## Structure

```
brain/
  index.md              # Master knowledge graph index
  theses/               # Individual thesis markdown files
  connections/          # Cross-thesis connection notes
  validations/          # Lookback validation results
  assets/               # Raw data snapshots + daily scans
  trader/
    strategy.md         # The trader's current self-authored strategy
    strategy_history.md # Why and when it changed its strategy
    directives.json     # Research requests for the next daily scan
    journal/            # One entry per trading session
    trades.jsonl        # Every order it placed, with rationale and fill
    equity.json         # Daily equity + positions snapshots
  lab/
    universe.json       # S&P 500 constituents, sectors, ETF list
    signals.json        # Every signal ever proposed, with gate results and live record
    signals/            # Signal code
    library/            # Reusable analysis modules the lab has written
    notebook/           # One entry per lab session
    agenda.json         # Open research questions + notes for the trader

data/prices/            # Local price store (gitignored; cached between Actions runs)

docs/                   # GitHub Pages static site (auto-generated)
  index.html
  theses/
  connections/
  validations/
  scans/
  journal/
  lab/
  portfolio.html
  assets/style.css

bot/
  main.py               # CLI entry point
  investigator.py       # Core Claude agent loop
  trader.py             # Autonomous portfolio manager
  lab/
    data.py             # Price store (Alpaca daily bars, adjusted)
    sandbox.py          # Runs model-written Python without secrets, with resource limits
    signals.py          # Signal registry, promotion gate, live tracking
    session.py          # Weekly lab research agent
    sandbox_lib/        # andiamo_lab (data helpers) + quant (toolkit) importable in the sandbox
  brain.py              # Knowledge graph manager
  config.py             # Config / env vars
  sources/
    alpaca.py           # Market data + paper trading
    reddit.py           # Reddit RSS scraping
    web.py              # DuckDuckGo search + page fetch
  site/
    builder.py          # Static HTML site generator
```

## Notes

- All trading is paper-only. No real money.
- The bot uses `claude-sonnet-4-6` by default (override with `CLAUDE_MODEL` env var).
- Reddit scanning uses the public JSON API (no API key required).
- Web search uses DuckDuckGo (no API key required).
