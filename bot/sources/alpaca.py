from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from bot.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL


def _client():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def _trading_client():
    from alpaca.trading.client import TradingClient
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)


def get_bars(symbol: str, start: datetime, end: Optional[datetime] = None, timeframe: str = "1Day") -> pd.DataFrame:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    tf_map = {"1Day": TimeFrame.Day, "1Hour": TimeFrame.Hour, "1Min": TimeFrame.Minute}
    tf = tf_map.get(timeframe, TimeFrame.Day)

    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end or datetime.utcnow(),
    )
    bars = _client().get_stock_bars(req)
    df = bars.df
    if df.empty:
        return df
    if hasattr(df.index, "levels"):
        df = df.reset_index(level=0, drop=True)
    return df


def get_latest_quote(symbol: str) -> dict:
    from alpaca.data.requests import StockLatestQuoteRequest
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    result = _client().get_stock_latest_quote(req)
    q = result[symbol]
    return {"symbol": symbol, "ask": float(q.ask_price), "bid": float(q.bid_price)}


def get_account() -> dict:
    acct = _trading_client().get_account()
    return {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
    }


def get_positions() -> list[dict]:
    positions = _trading_client().get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "avg_entry_price": float(p.avg_entry_price),
        }
        for p in positions
    ]


def place_order(symbol: str, qty: float, side: str, order_type: str = "market") -> dict:
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side_enum,
        time_in_force=TimeInForce.DAY,
    )
    order = _trading_client().submit_order(req)
    return {"id": str(order.id), "symbol": order.symbol, "qty": float(order.qty), "side": order.side.value}


def summarize_bars(df: pd.DataFrame, symbol: str) -> str:
    if df.empty:
        return f"No price data available for {symbol}."
    close = df["close"]
    start_price = float(close.iloc[0])
    end_price = float(close.iloc[-1])
    pct = (end_price - start_price) / start_price * 100
    high = float(df["high"].max())
    low = float(df["low"].min())
    avg_vol = int(df["volume"].mean())
    return (
        f"{symbol}: {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}. "
        f"Start ${start_price:.2f} → End ${end_price:.2f} ({pct:+.1f}%). "
        f"Range ${low:.2f}–${high:.2f}. Avg daily volume {avg_vol:,}."
    )
