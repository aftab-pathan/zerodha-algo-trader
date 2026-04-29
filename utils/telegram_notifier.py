"""
utils/telegram_notifier.py
Sends trade alerts, daily summaries, and error notifications via Telegram.
Supports PAPER and LIVE trading modes with visual indicators.
"""

import logging
import requests
from datetime import datetime
from config.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_TRADING_MODE

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _get_mode_prefix() -> str:
    """Get mode prefix for all messages"""
    return "🟡 [PAPER] " if PAPER_TRADING_MODE else "🔴 [LIVE] "


def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping notification.")
        return False
    
    # Add mode prefix to all messages
    prefixed_text = _get_mode_prefix() + text
    
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": prefixed_text, "parse_mode": parse_mode},
            timeout=10
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def notify_signal(symbol: str, signal: str, strategy: str, entry: float,
                  sl: float, target: float, qty: int, capital_used: float,
                  confidence: float, reasoning: str) -> None:
    emoji = "🟢" if signal == "BUY" else "🔴"
    rr = round(abs(target - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
    msg = (
        f"{emoji} <b>TRADE SIGNAL — {signal}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Stock:</b> {symbol}\n"
        f"🎯 <b>Strategy:</b> {strategy}\n"
        f"💰 <b>Entry:</b> ₹{entry:.2f}\n"
        f"🛑 <b>Stop Loss:</b> ₹{sl:.2f}\n"
        f"🎁 <b>Target:</b> ₹{target:.2f}\n"
        f"📊 <b>Risk:Reward:</b> 1:{rr}\n"
        f"🔢 <b>Quantity:</b> {qty} shares\n"
        f"💵 <b>Capital Used:</b> ₹{capital_used:,.0f}\n"
        f"🤖 <b>AI Confidence:</b> {confidence}/10\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 {reasoning}\n"
        f"🕐 {datetime.now().strftime('%d-%b-%Y %H:%M IST')}"
    )
    _send(msg)


def notify_order_placed(symbol: str, order_id: str, signal: str,
                        qty: int, price: float) -> None:
    emoji = "✅" if signal == "BUY" else "🔻"
    _send(
        f"{emoji} <b>ORDER PLACED</b>\n"
        f"Stock: <b>{symbol}</b> | {signal}\n"
        f"Qty: {qty} @ ₹{price:.2f}\n"
        f"Order ID: <code>{order_id}</code>\n"
        f"🕐 {datetime.now().strftime('%H:%M IST')}"
    )


def notify_order_filled(symbol: str, signal: str, avg_price: float, qty: int) -> None:
    _send(
        f"🏦 <b>ORDER EXECUTED</b>\n"
        f"{symbol} {signal} — {qty} shares @ ₹{avg_price:.2f}\n"
        f"💵 Value: ₹{avg_price * qty:,.0f}"
    )


def notify_exit(symbol: str, exit_type: str, buy_price: float,
                sell_price: float, qty: int) -> None:
    pnl = (sell_price - buy_price) * qty
    emoji = "🏆" if pnl > 0 else "📉"
    _send(
        f"{emoji} <b>POSITION CLOSED — {exit_type}</b>\n"
        f"Stock: <b>{symbol}</b>\n"
        f"Buy: ₹{buy_price:.2f} → Sell: ₹{sell_price:.2f}\n"
        f"Qty: {qty} | P&L: <b>₹{pnl:+,.0f}</b>"
    )


def notify_daily_summary(stats: dict) -> None:
    pnl = stats.get("total_pnl", 0)
    emoji = "📈" if pnl >= 0 else "📉"
    _send(
        f"{emoji} <b>DAILY SUMMARY</b> — {datetime.now().strftime('%d %b %Y')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Signals Generated: {stats.get('signals', 0)}\n"
        f"Orders Placed: {stats.get('orders', 0)}\n"
        f"Open Positions: {stats.get('open_positions', 0)}\n"
        f"Realized P&L: <b>₹{pnl:+,.0f}</b>\n"
        f"Capital Deployed: ₹{stats.get('capital_used', 0):,.0f}\n"
        f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Portfolio Value: ₹{stats.get('portfolio_value', 0):,.0f}"
    )


def notify_watchlist_updated(added: list, total: int) -> None:
    """
    Notify about shortlisted stocks.
    Note: Kite API v5+ doesn't support watchlist management,
    so this just notifies about stocks that should be added manually.
    """
    if not added:
        return
    
    stocks_list = ', '.join(added[:10])
    if len(added) > 10:
        stocks_list += f" +{len(added)-10} more"
    
    _send(
        f"📋 <b>SHORTLISTED STOCKS</b>\n"
        f"Found {len(added)} signals: {stocks_list}\n\n"
        f"⚠️ <i>Note: Add these manually to your Kite watchlist</i>\n"
        f"<i>(API doesn't support auto-update)</i>"
    )


def notify_error(component: str, error: str) -> None:
    _send(
        f"⚠️ <b>SYSTEM ERROR</b>\n"
        f"Component: {component}\n"
        f"Error: {error[:300]}\n"
        f"🕐 {datetime.now().strftime('%H:%M IST')}"
    )


def notify_startup() -> None:
    from config.config import TRADING_CAPITAL, ACTIVE_STRATEGIES
    _send(
        f"🚀 <b>ALGO TRADER STARTED</b>\n"
        f"Capital: ₹{TRADING_CAPITAL:,.0f}\n"
        f"Strategies: {', '.join(ACTIVE_STRATEGIES)}\n"
        f"🕐 {datetime.now().strftime('%d-%b-%Y %H:%M IST')}"
    )
