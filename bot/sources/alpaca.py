from datetime import datetime, timedelta
from typing import Optional

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from bot.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL


def _client():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def _trading_client():
    from alpaca.trading.client import TradingClient
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)


def get_bars(symbol: str, start: datetime, end: Optional[datetime] = None, timeframe: str = "1Day"):
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
        "last_equity": float(acct.last_equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "long_market_value": float(acct.long_market_value),
        "short_market_value": float(acct.short_market_value),
        "shorting_enabled": bool(acct.shorting_enabled),
    }


def get_positions() -> list[dict]:
    positions = _trading_client().get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "side": p.side.value,
            "qty": float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
        }
        for p in positions
    ]


def get_clock() -> dict:
    c = _trading_client().get_clock()
    return {
        "is_open": bool(c.is_open),
        "timestamp": c.timestamp.isoformat(),
        "next_open": c.next_open.isoformat(),
        "next_close": c.next_close.isoformat(),
    }


def _order_dict(o) -> dict:
    return {
        "id": str(o.id),
        "symbol": o.symbol,
        "side": o.side.value,
        "type": o.order_type.value if o.order_type else None,
        "qty": float(o.qty) if o.qty is not None else None,
        "notional": float(o.notional) if o.notional is not None else None,
        "limit_price": float(o.limit_price) if o.limit_price is not None else None,
        "status": o.status.value,
        "filled_qty": float(o.filled_qty or 0),
        "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price is not None else None,
        "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
    }


def get_open_orders() -> list[dict]:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    orders = _trading_client().get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    return [_order_dict(o) for o in orders]


def get_order(order_id: str) -> dict:
    return _order_dict(_trading_client().get_order_by_id(order_id))


def cancel_order(order_id: str) -> None:
    _trading_client().cancel_order_by_id(order_id)


def place_order(
    symbol: str,
    side: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    order_type: str = "market",
    limit_price: Optional[float] = None,
) -> dict:
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    # Fractional/notional orders must be DAY; whole-share orders can be GTC
    common = dict(symbol=symbol.upper(), side=side_enum, time_in_force=TimeInForce.DAY)
    if notional is not None:
        common["notional"] = round(float(notional), 2)
    else:
        common["qty"] = qty
    if order_type == "limit":
        req = LimitOrderRequest(limit_price=round(float(limit_price), 2), **common)
    else:
        req = MarketOrderRequest(**common)
    return _order_dict(_trading_client().submit_order(req))


def close_position(symbol: str, percentage: Optional[float] = None) -> dict:
    from alpaca.trading.requests import ClosePositionRequest
    opts = ClosePositionRequest(percentage=str(percentage)) if percentage else None
    return _order_dict(_trading_client().close_position(symbol.upper(), close_options=opts))


def summarize_bars(df, symbol: str) -> str:
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
