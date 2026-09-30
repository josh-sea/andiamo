"""
Local daily price store for the research lab.

Wide parquet frames (dates x symbols) per field under data/prices/, kept out of git
and carried between GitHub Actions runs with actions/cache. Split/dividend adjusted.
"""

import io
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from bot.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, BRAIN_DIR, REPO_ROOT

DATA_DIR = os.path.join(REPO_ROOT, "data")
PRICES_DIR = os.path.join(DATA_DIR, "prices")
META_PATH = os.path.join(PRICES_DIR, "meta.json")
UNIVERSE_PATH = os.path.join(BRAIN_DIR, "lab", "universe.json")
FIELDS = ["open", "high", "low", "close", "volume"]
HISTORY_START = datetime(2016, 1, 1, tzinfo=timezone.utc)
FULL_REFRESH_DAYS = 7
LAST_FEED = ["?"]  # adjusted history shifts on dividends/splits, so re-pull everything weekly

ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "RSP", "MDY",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "SMH", "SOXX", "IGV", "XBI", "KRE", "ITB", "XRT", "XOP", "GDX",
    "TLT", "IEF", "SHY", "TIP", "LQD", "HYG", "EMB",
    "GLD", "SLV", "USO", "UNG", "DBC", "UUP", "FXE", "FXY",
    "EFA", "EEM", "FXI", "EWJ", "VIXY", "TBT", "TMF",
]


def _fetch_sp500() -> dict[str, str]:
    r = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "andiamo-finance-bot/1.0"}, timeout=30,
    )
    r.raise_for_status()
    table = pd.read_html(io.StringIO(r.text))[0]
    # Alpaca uses dots for share classes (BRK.B), same as Wikipedia
    return dict(zip(table["Symbol"].str.strip(), table["GICS Sector"].str.strip()))


def load_universe(refresh: bool = False) -> dict:
    universe = {}
    if os.path.exists(UNIVERSE_PATH):
        with open(UNIVERSE_PATH) as f:
            universe = json.load(f)
    stale = not universe or universe.get("updated", "") < (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    if refresh or stale:
        try:
            sectors = _fetch_sp500()
            universe = {
                "updated": datetime.now(timezone.utc).date().isoformat(),
                "sp500": sorted(sectors),
                "sectors": sectors,
                "etfs": ETFS,
            }
            os.makedirs(os.path.dirname(UNIVERSE_PATH), exist_ok=True)
            with open(UNIVERSE_PATH, "w") as f:
                json.dump(universe, f, indent=1)
        except Exception as e:
            if not universe:
                raise RuntimeError(f"Could not load S&P 500 universe: {e}")
    return universe


def _read_meta() -> dict:
    try:
        with open(META_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _fetch_bars(symbols: list[str], start: datetime) -> dict[str, pd.DataFrame]:
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    # Stop at today's midnight ET so an unfinished intraday bar never enters the store
    end = pd.Timestamp.now(tz="America/New_York").normalize().tz_convert("UTC").to_pydatetime()
    frames = {f: [] for f in FIELDS}
    feeds = [os.environ.get("ALPACA_DATA_FEED", "sip"), "iex"]
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        df = None
        for feed in list(feeds):
            try:
                df = client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=chunk, timeframe=TimeFrame.Day, start=start, end=end,
                    adjustment=Adjustment.ALL, feed=feed,
                )).df
                LAST_FEED[0] = feed
                break
            except Exception as e:
                print(f"[lab-data] chunk {i // 100} feed={feed} failed: {e}")
                if feed != "iex" and len(feeds) > 1:
                    feeds.remove(feed)
        if df is None:
            continue
        if df.empty:
            continue
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
        for f in FIELDS:
            frames[f].append(df.pivot_table(index="date", columns="symbol", values=f, aggfunc="last"))
    return {f: pd.concat(v, axis=1).sort_index() if v else pd.DataFrame() for f, v in frames.items()}


def update_store(full: bool = False) -> dict:
    """Bring the local price store up to date. Returns the store metadata."""
    universe = load_universe()
    symbols = sorted(set(universe["sp500"]) | set(universe["etfs"]))
    meta = _read_meta()
    os.makedirs(PRICES_DIR, exist_ok=True)

    have_store = all(os.path.exists(os.path.join(PRICES_DIR, f"{f}.parquet")) for f in FIELDS)
    last_full = meta.get("last_full_refresh", "")
    stale_full = last_full < (datetime.now(timezone.utc) - timedelta(days=FULL_REFRESH_DAYS)).date().isoformat()
    do_full = full or not have_store or stale_full

    start = HISTORY_START if do_full else datetime.now(timezone.utc) - timedelta(days=10)
    fresh = _fetch_bars(symbols, start)
    if fresh["close"].empty:
        raise RuntimeError("No bars returned from Alpaca")

    for f in FIELDS:
        path = os.path.join(PRICES_DIR, f"{f}.parquet")
        if do_full or not os.path.exists(path):
            combined = fresh[f]
        else:
            old = pd.read_parquet(path)
            combined = fresh[f].combine_first(old)
        combined.sort_index().to_parquet(path)

    close = pd.read_parquet(os.path.join(PRICES_DIR, "close.parquet"))
    meta = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_full_refresh": datetime.now(timezone.utc).date().isoformat() if do_full else last_full,
        "first_date": str(close.index.min().date()),
        "last_date": str(close.index.max().date()),
        "symbols": int(close.shape[1]),
        "rows": int(close.shape[0]),
        "feed": LAST_FEED[0],
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[lab-data] {'full' if do_full else 'incremental'} update: {meta['symbols']} symbols, "
          f"{meta['first_date']} → {meta['last_date']}")
    return meta
