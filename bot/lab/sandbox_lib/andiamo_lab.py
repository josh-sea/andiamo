"""
Auto-imported into every lab code cell: `from andiamo_lab import *`.

In research sessions the price store handed to this sandbox ends at HOLDOUT_START; the most
recent ~year is reserved for judging proposed signals on data they were never fitted to.
"""

import glob
import json
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import quant  # noqa: E402

PRICES_DIR = os.environ["ANDIAMO_PRICES_DIR"]
ASSETS_DIR = os.environ["ANDIAMO_ASSETS_DIR"]
UNIVERSE_PATH = os.environ["ANDIAMO_UNIVERSE_PATH"]
FIG_DIR = os.environ["ANDIAMO_FIG_DIR"]
HOLDOUT_START = pd.Timestamp(os.environ["ANDIAMO_HOLDOUT_START"])

__all__ = ["np", "pd", "plt", "quant", "load_prices", "load_returns", "universe", "sectors",
           "holdout_start", "scans", "save_figure", "HOLDOUT_START"]


def holdout_start() -> pd.Timestamp:
    return HOLDOUT_START


def universe(kind: str = "all") -> list[str]:
    with open(UNIVERSE_PATH) as f:
        u = json.load(f)
    if kind == "sp500":
        return list(u["sp500"])
    if kind == "etf":
        return list(u["etfs"])
    return sorted(set(u["sp500"]) | set(u["etfs"]))


def sectors() -> dict[str, str]:
    with open(UNIVERSE_PATH) as f:
        return json.load(f)["sectors"]


def load_prices(symbols=None, field: str = "close", start=None, end=None,
                include_holdout: bool = True) -> pd.DataFrame:
    """Wide frame of split/dividend-adjusted daily prices (dates x symbols)."""
    df = pd.read_parquet(os.path.join(PRICES_DIR, f"{field}.parquet"))
    if symbols is not None:
        symbols = [symbols] if isinstance(symbols, str) else list(symbols)
        missing = [s for s in symbols if s not in df.columns]
        if missing:
            print(f"[load_prices] not in store: {missing}")
        df = df[[s for s in symbols if s in df.columns]]
    if not include_holdout:
        df = df[df.index < HOLDOUT_START]
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def load_returns(symbols=None, **kwargs) -> pd.DataFrame:
    return quant.returns(load_prices(symbols, **kwargs))


def scans() -> pd.DataFrame:
    """One row per (scan date, lead, ticker) from Andiamo's daily research scans."""
    rows = []
    for path in sorted(glob.glob(os.path.join(ASSETS_DIR, "scan-*.md"))):
        date = os.path.basename(path)[5:-3]
        with open(path) as f:
            m = re.search(r"```json\s*(\{.*?\})\s*```", f.read(), re.DOTALL)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        payload = data.get("scan", data) if isinstance(data.get("scan"), dict) else data
        for lead in payload.get("leads") or []:
            if not isinstance(lead, dict):
                continue
            tickers = next((lead[k] for k in ("tickers", "tickers_of_interest", "tickers_to_watch", "watch_tickers")
                            if isinstance(lead.get(k), list)), [])
            base = {
                "date": pd.Timestamp(date),
                "rank": lead.get("rank"),
                "title": lead.get("title") or lead.get("headline") or "",
                "signal_strength": pd.to_numeric(lead.get("signal_strength"), errors="coerce"),
                "sentiment": pd.to_numeric(lead.get("sentiment"), errors="coerce"),
                "category": lead.get("category") or lead.get("signal_type") or "",
            }
            for t in tickers or [None]:
                ticker = str(t).split()[0].strip("$()").upper() if t else None
                rows.append({**base, "ticker": ticker})
    return pd.DataFrame(rows)


def save_figure(name: str, fig=None) -> str:
    """Save the current (or given) matplotlib figure for the published lab notebook."""
    name = re.sub(r"\.png$", "", name.lower().strip())
    name = re.sub(r"[^a-z0-9_-]+", "-", name).strip("-") or "figure"
    os.makedirs(FIG_DIR, exist_ok=True)
    path = os.path.join(FIG_DIR, f"{name}.png")
    (fig or plt.gcf()).savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig or plt.gcf())
    print(f"[figure saved: {name}.png]")
    return f"{name}.png"
