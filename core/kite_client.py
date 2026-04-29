"""
core/kite_client.py
Zerodha Kite Connect wrapper with auto-reconnect, rate limiting,
watchlist management, and order execution.

Supports both LIVE and PAPER trading modes via PAPER_TRADING_MODE toggle.
"""

import os
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Union
from kiteconnect import KiteConnect, KiteTicker
from config.config import (
    KITE_API_KEY, KITE_API_SECRET, EXCHANGE,
    PRODUCT_TYPE, ORDER_VALIDITY, DATA_DIR, PAPER_TRADING_MODE
)
from utils.security import save_access_token, load_access_token, audit_log

logger = logging.getLogger(__name__)
_kite: Optional[Union[KiteConnect, 'PaperTradingClient']] = None


# ─────────────────────────────────────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────────────────────────────────────

def get_kite() -> Union[KiteConnect, 'PaperTradingClient']:
    """
    Get KiteConnect client (live or paper mode based on PAPER_TRADING_MODE).
    Returns PaperTradingClient if PAPER_TRADING_MODE=true, else real KiteConnect.
    """
    global _kite
    if _kite is None:
        if PAPER_TRADING_MODE:
            # Import here to avoid circular dependency
            from core.paper_trading_client import PaperTradingClient
            _kite = PaperTradingClient(api_key=KITE_API_KEY)
            token = load_access_token()
            if token:
                _kite.set_access_token(token)
            logger.warning("🟡 PAPER TRADING MODE ACTIVE - No real trades will be placed")
        else:
            _kite = KiteConnect(api_key=KITE_API_KEY)
            token = load_access_token()
            if token:
                _kite.set_access_token(token)
            logger.info("🔴 LIVE TRADING MODE ACTIVE - Real trades will be placed")
    return _kite


def is_paper_mode() -> bool:
    """Check if system is in paper trading mode"""
    return PAPER_TRADING_MODE


def get_login_url() -> str:
    return get_kite().login_url()


def complete_login(request_token: str) -> str:
    """Exchange request_token for access_token. Call once per day."""
    kite = get_kite()
    data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
    access_token = data["access_token"]
    kite.set_access_token(access_token)
    save_access_token(access_token)
    audit_log("LOGIN", {"user": data.get("user_id", "unknown"), "status": "success"})
    logger.info(f"Login complete for user: {data.get('user_id')}")
    return access_token


def is_authenticated() -> bool:
    try:
        get_kite().profile()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Instrument Lookup
# ─────────────────────────────────────────────────────────────────────────────

_instrument_cache: dict = {}


def _load_instruments():
    global _instrument_cache
    if _instrument_cache:
        return
    instruments = get_kite().instruments("NSE")
    for inst in instruments:
        _instrument_cache[inst["tradingsymbol"]] = inst["instrument_token"]
    logger.info(f"Loaded {len(_instrument_cache)} NSE instruments.")


def get_token(symbol: str) -> int:
    _load_instruments()
    token = _instrument_cache.get(symbol)
    if not token:
        # Try common variations for NSE symbols
        variations = [
            f"{symbol}-EQ",
            f"{symbol}DVR",
            symbol.replace("MOTORS", "MTR"),
        ]
        for var in variations:
            token = _instrument_cache.get(var)
            if token:
                logger.info(f"Found {symbol} as {var}")
                return token
        raise ValueError(f"Instrument token not found for: {symbol}")
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Market Data
# ─────────────────────────────────────────────────────────────────────────────

def get_historical_data(symbol: str, interval: str = "day", days: int = 365) -> pd.DataFrame:
    """
    Fetch OHLCV data. interval: minute, 5minute, 15minute, 30minute, 60minute, day
    """
    kite = get_kite()
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    token = get_token(symbol)

    try:
        raw = kite.historical_data(
            instrument_token=token,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            interval=interval,
            continuous=False,
            oi=False
        )
        df = pd.DataFrame(raw)
        df["symbol"] = symbol
        df.rename(columns={"date": "datetime"}, inplace=True)
        df.set_index("datetime", inplace=True)
        logger.info(f"Fetched {len(df)} {interval} bars for {symbol}")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch data for {symbol}: {e}")
        return pd.DataFrame()


def get_ltp(symbols: list) -> dict:
    """Get last traded prices for a list of symbols."""
    kite = get_kite()
    exchange_symbols = [f"NSE:{s}" for s in symbols]
    quotes = kite.quote(exchange_symbols)
    return {
        s: quotes[f"NSE:{s}"]["last_price"]
        for s in symbols
        if f"NSE:{s}" in quotes
    }


def get_quote(symbol: str) -> dict:
    """Full quote data for one symbol."""
    data = get_kite().quote(f"NSE:{symbol}")
    return data.get(f"NSE:{symbol}", {})


# ─────────────────────────────────────────────────────────────────────────────
# Order Management
# ─────────────────────────────────────────────────────────────────────────────

def place_order(symbol: str, transaction_type: str, quantity: int,
                price: float = 0, order_type: str = "MARKET") -> Optional[str]:
    """
    Place a CNC order. Returns order_id or None on failure.
    transaction_type: "BUY" or "SELL"
    order_type: "MARKET" or "LIMIT"
    """
    kite = get_kite()
    try:
        params = dict(
            tradingsymbol=symbol,
            exchange=kite.EXCHANGE_NSE,
            transaction_type=kite.TRANSACTION_TYPE_BUY if transaction_type == "BUY"
                             else kite.TRANSACTION_TYPE_SELL,
            quantity=quantity,
            product=kite.PRODUCT_CNC,
            order_type=kite.ORDER_TYPE_MARKET if order_type == "MARKET"
                       else kite.ORDER_TYPE_LIMIT,
            validity=kite.VALIDITY_DAY,
        )
        if order_type == "LIMIT" and price > 0:
            params["price"] = round(price, 2)

        order_id = kite.place_order(variety=kite.VARIETY_REGULAR, **params)
        audit_log("ORDER_PLACED", {
            "symbol": symbol, "type": transaction_type,
            "qty": quantity, "price": price, "order_id": str(order_id)
        })
        logger.info(f"Order placed: {symbol} {transaction_type} {quantity} @ ₹{price} → ID {order_id}")
        return str(order_id)
    except Exception as e:
        audit_log("ORDER_REJECTED", {"symbol": symbol, "error": str(e)})
        logger.error(f"Order failed for {symbol}: {e}")
        return None


def place_gtt_oco(symbol: str, quantity: int, entry_price: float,
                  stop_loss: float, target: float) -> Optional[str]:
    """
    Place GTT (Good Till Triggered) OCO order — auto SL + Target.
    Remains active even if your system is offline.
    """
    kite = get_kite()
    try:
        gtt_id = kite.place_gtt(
            trigger_type=kite.GTT_TYPE_OCO,
            tradingsymbol=symbol,
            exchange="NSE",
            trigger_values=[round(stop_loss, 2), round(target, 2)],
            last_price=entry_price,
            orders=[
                {
                    "transaction_type": "SELL",
                    "quantity": quantity,
                    "product": "CNC",
                    "order_type": "LIMIT",
                    "price": round(stop_loss * 0.99, 2),   # slight buffer for SL
                },
                {
                    "transaction_type": "SELL",
                    "quantity": quantity,
                    "product": "CNC",
                    "order_type": "LIMIT",
                    "price": round(target, 2),
                }
            ]
        )
        logger.info(f"GTT OCO placed for {symbol}: SL={stop_loss}, Target={target}, ID={gtt_id}")
        return str(gtt_id)
    except Exception as e:
        logger.error(f"GTT failed for {symbol}: {e}")
        return None


def get_positions() -> pd.DataFrame:
    """Return all open CNC positions."""
    kite = get_kite()
    try:
        positions = kite.positions()
        day_pos = positions.get("day", []) + positions.get("net", [])
        df = pd.DataFrame(day_pos)
        if not df.empty:
            df = df[df["quantity"] != 0]
        return df
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        return pd.DataFrame()


def get_holdings() -> pd.DataFrame:
    """Return holdings (overnight CNC positions)."""
    try:
        return pd.DataFrame(get_kite().holdings())
    except Exception as e:
        logger.error(f"Failed to fetch holdings: {e}")
        return pd.DataFrame()


def get_portfolio_value() -> float:
    """Total current portfolio value (holdings + cash)."""
    try:
        margins = get_kite().margins("equity")
        cash = margins.get("net", 0)
        holdings = get_holdings()
        stocks_value = (holdings["last_price"] * holdings["quantity"]).sum() if not holdings.empty else 0
        return round(cash + stocks_value, 2)
    except Exception as e:
        logger.error(f"Failed to fetch portfolio value: {e}")
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist Management
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: Kite Connect API v5+ does not support watchlist management
# Users must manually update watchlists through Kite web/app
# ─────────────────────────────────────────────────────────────────────────────

def get_watchlists() -> list:
    """
    Fetch all watchlists from Kite.
    NOTE: This feature is not available in Kite Connect API v5+.
    """
    logger.warning("⚠️  Watchlist API is not supported in Kite Connect v5+")
    logger.warning("   Please manage watchlists manually at https://kite.zerodha.com")
    return []


def get_or_create_watchlist(name: str = "AlgoTrader Picks") -> Optional[int]:
    """
    Get watchlist ID by name, or create it if it doesn't exist.
    NOTE: This feature is not available in Kite Connect API v5+.
    """
    logger.warning(f"⚠️  Watchlist management not supported in Kite Connect API v5+")
    logger.warning(f"   Shortlisted symbols will be logged but not added to Kite watchlist")
    logger.warning(f"   You can manually add them at: https://kite.zerodha.com")
    return None


def add_to_watchlist(symbols: list, watchlist_name: str = "AlgoTrader Picks") -> list:
    """
    Add shortlisted symbols to Zerodha watchlist.
    NOTE: Kite Connect API v5+ does not support watchlist management.
    This function will log the symbols that would be added.
    """
    if not symbols:
        return []
    
    logger.warning(f"⚠️  Watchlist API not supported - cannot auto-update Kite watchlist")
    logger.info(f"📋 Shortlisted symbols (add manually to Kite):")
    for i, symbol in enumerate(symbols, 1):
        logger.info(f"   {i}. {symbol}")
    
    logger.info(f"\n   → Go to https://kite.zerodha.com")
    logger.info(f"   → Open watchlist '{watchlist_name}'")
    logger.info(f"   → Add these {len(symbols)} stocks manually\n")
    
    # Return empty list since we can't actually add them
    return []


def clear_watchlist(watchlist_name: str = "AlgoTrader Picks") -> bool:
    """
    Clear all items from the algo watchlist.
    NOTE: This feature is not available in Kite Connect API v5+.
    """
    logger.warning(f"⚠️  Watchlist management not supported in Kite Connect v5+")
    return False
