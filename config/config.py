"""
config/config.py
Central configuration — all secrets loaded from environment variables.
NEVER hardcode credentials. Use .env file locally, env vars in production.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Zerodha Kite Connect ─────────────────────────────────────────────────────
KITE_API_KEY        = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET     = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN   = os.getenv("KITE_ACCESS_TOKEN", "")   # refreshed daily

# ─── Anthropic (Claude AI) ────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL        = "claude-sonnet-4-20250514"

# ─── Telegram Notifications ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Trading Capital & Risk Management ───────────────────────────────────────
TRADING_CAPITAL     = float(os.getenv("TRADING_CAPITAL", "10000"))   # changeable
MAX_RISK_PER_TRADE  = float(os.getenv("MAX_RISK_PER_TRADE", "0.02")) # 2% of capital
MAX_OPEN_POSITIONS  = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MAX_CAPITAL_DEPLOY  = float(os.getenv("MAX_CAPITAL_DEPLOY", "0.80")) # use max 80% of capital
MIN_CONFIDENCE      = float(os.getenv("MIN_CONFIDENCE", "7.0"))      # Claude min score
MIN_RISK_REWARD     = float(os.getenv("MIN_RISK_REWARD", "2.0"))     # 1:2 minimum

# ─── Paper Trading Configuration ──────────────────────────────────────────────
PAPER_TRADING_MODE     = os.getenv("PAPER_TRADING_MODE", "False").lower() in ("true", "1", "yes")
PAPER_TRADING_CAPITAL  = float(os.getenv("PAPER_TRADING_CAPITAL", str(TRADING_CAPITAL)))  # Default to same as live capital
PAPER_SLIPPAGE_PCT     = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.002"))  # 0.2% slippage simulation
PAPER_FILL_DELAY       = int(os.getenv("PAPER_FILL_DELAY", "3"))  # Seconds delay for order fills

# ─── Exchange & Product Settings ─────────────────────────────────────────────
EXCHANGE            = "NSE"
PRODUCT_TYPE        = "CNC"      # CNC = delivery (swing trading)
ORDER_VALIDITY      = "DAY"

# ─── Active Strategies ───────────────────────────────────────────────────────
# Add/remove strategy names to enable/disable them
ACTIVE_STRATEGIES = os.getenv("ACTIVE_STRATEGIES",
    "ema_crossover,rsi_reversal,macd_momentum,breakout,claude_ai"
).split(",")

# ─── Watchlist (editable from env or override in watchlist.txt) ──────────────
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "AXISBANK", "SBIN", "KOTAKBANK", "WIPRO", "LT",
    "TATAMTRDVR", "BAJFINANCE", "ADANIPORTS", "SUNPHARMA", "MARUTI"
]

# ─── Bulk Scanning (Top 1000 NSE stocks) ─────────────────────────────────────
ENABLE_BULK_SCAN     = os.getenv("ENABLE_BULK_SCAN", "False").lower() in ("true", "1", "yes")
BULK_SCAN_SIZE       = int(os.getenv("BULK_SCAN_SIZE", "1000"))
PREFILTER_MIN_PRICE  = float(os.getenv("PREFILTER_MIN_PRICE", "50"))
PREFILTER_MAX_PRICE  = float(os.getenv("PREFILTER_MAX_PRICE", "10000"))
PREFILTER_MIN_VOLUME = int(os.getenv("PREFILTER_MIN_VOLUME", "50000"))
MAX_STAGE2_STOCKS    = int(os.getenv("MAX_STAGE2_STOCKS", "200"))
CACHE_DURATION_HOURS = float(os.getenv("CACHE_DURATION_HOURS", "1.0"))

# ─── Two-Tier Claude Scanning (Cost Optimization) ────────────────────────────
# For bulk scans: Run fast technical strategies first, then Claude on top picks only
ENABLE_TWO_TIER_CLAUDE = os.getenv("ENABLE_TWO_TIER_CLAUDE", "True").lower() in ("true", "1", "yes")
# Strategies for Stage 2 (technical analysis only, fast & free)
BULK_SCAN_STRATEGIES = os.getenv("BULK_SCAN_STRATEGIES",
    "ema_crossover,rsi_reversal,macd_momentum,breakout,52w_breakout"
).split(",")
# How many top technical signals to send to Claude for final analysis
MAX_CLAUDE_STOCKS = int(os.getenv("MAX_CLAUDE_STOCKS", "20"))
# Minimum confidence from technical strategies to qualify for Claude analysis
MIN_CONFIDENCE_FOR_CLAUDE = float(os.getenv("MIN_CONFIDENCE_FOR_CLAUDE", "6.0"))

# ─── Scheduling (IST times) ──────────────────────────────────────────────────
SCAN_TIME_MORNING   = "09:20"   # post market open
SCAN_TIME_EOD       = "15:10"   # pre market close
TOKEN_REFRESH_TIME  = "08:30"   # daily token refresh

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR         = os.path.join(BASE_DIR, "logs")
DATA_DIR        = os.path.join(BASE_DIR, "data")
TOKEN_FILE      = os.path.join(DATA_DIR, "access_token.enc")
TRADE_LOG_FILE  = os.path.join(LOG_DIR, "trades.csv")
STATE_FILE      = os.path.join(DATA_DIR, "state.json")

# ─── Validation ───────────────────────────────────────────────────────────────
def validate_config():
    missing = []
    required = {
        "KITE_API_KEY": KITE_API_KEY,
        "KITE_API_SECRET": KITE_API_SECRET,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    for key, val in required.items():
        if not val:
            missing.append(key)
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")
    if TRADING_CAPITAL < 1000:
        raise ValueError("TRADING_CAPITAL must be at least ₹1000")
    return True

# ─── Trade Direction Filter ──────────────────────────────────────────────────
# Set which signals to trade: "BUY", "SELL", or "BOTH"
TRADE_DIRECTION = os.getenv("TRADE_DIRECTION", "BUY").upper()  # Default: BUY only
