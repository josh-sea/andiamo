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

# Rebuild the GitHub Pages site manually
python -m bot.main build-site

# Show the knowledge graph index
python -m bot.main show-brain
```

## Automation

- **Daily scan**: GitHub Actions runs at 9am ET weekdays (`daily_scan.yml`). Results committed back to `brain/` and `docs/`.
- **Manual trigger**: Use the `workflow_dispatch` input in GitHub Actions to run a specific hypothesis/mode.
- **GitHub Pages**: Auto-deploys whenever `docs/` changes on `main`.

## Structure

```
brain/
  index.md              # Master knowledge graph index
  theses/               # Individual thesis markdown files
  connections/          # Cross-thesis connection notes
  validations/          # Lookback validation results
  assets/               # Raw data snapshots

docs/                   # GitHub Pages static site (auto-generated)
  index.html
  theses/
  connections/
  validations/
  portfolio.html
  assets/style.css

bot/
  main.py               # CLI entry point
  investigator.py       # Core Claude agent loop
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
