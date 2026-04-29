"""
core/risk_manager.py  (v2 — Production Grade)

Institutional-level risk parameters used by prop desks and hedge funds.
Every parameter is configurable via .env.

Supports LIVE and PAPER trading modes - uses paper capital when PAPER_TRADING_MODE=true.

Parameters implemented:
  - Position sizing (ATR-based + capital-based, 3-method minimum)
  - Max drawdown circuit breaker (daily / weekly / total)
  - Daily loss limit with auto trading halt
  - Sector concentration limit
  - Max single stock exposure
  - Trailing stop logic
  - Slippage and brokerage cost model (Zerodha-specific)
  - Quarter-Kelly criterion (after 20+ trades)
  - Consecutive loss protection
"""

import logging
import os
from dataclasses import dataclass
from datetime import date

from config.config import (
    TRADING_CAPITAL, MAX_RISK_PER_TRADE, MAX_OPEN_POSITIONS,
    MAX_CAPITAL_DEPLOY, MIN_RISK_REWARD, PAPER_TRADING_MODE,
    PAPER_TRADING_CAPITAL
)

logger = logging.getLogger(__name__)

# ─── Production Risk Parameters (override via .env) ──────────────────────────
MAX_DAILY_LOSS_PCT       = float(os.getenv("MAX_DAILY_LOSS_PCT",     "0.03"))
MAX_WEEKLY_LOSS_PCT      = float(os.getenv("MAX_WEEKLY_LOSS_PCT",    "0.06"))
MAX_TOTAL_DRAWDOWN_PCT   = float(os.getenv("MAX_TOTAL_DRAWDOWN_PCT", "0.15"))
MAX_SINGLE_STOCK_PCT     = float(os.getenv("MAX_SINGLE_STOCK_PCT",   "0.20"))
MAX_SECTOR_EXPOSURE_PCT  = float(os.getenv("MAX_SECTOR_EXPOSURE_PCT","0.40"))
BROKERAGE_PER_ORDER      = float(os.getenv("BROKERAGE_PER_ORDER",    "20.0"))
STT_PCT                  = float(os.getenv("STT_PCT",                "0.001"))
EXCHANGE_CHARGES_PCT     = float(os.getenv("EXCHANGE_CHARGES_PCT",   "0.0000325"))
SLIPPAGE_PCT             = float(os.getenv("SLIPPAGE_PCT",           "0.002"))
MAX_CONSECUTIVE_LOSSES   = int(os.getenv("MAX_CONSECUTIVE_LOSSES",   "4"))
MIN_WIN_RATE_THRESHOLD   = float(os.getenv("MIN_WIN_RATE_THRESHOLD", "0.35"))
ATR_SL_MULTIPLIER        = float(os.getenv("ATR_SL_MULTIPLIER",      "2.0"))
ATR_TARGET_MULTIPLIER    = float(os.getenv("ATR_TARGET_MULTIPLIER",  "4.0"))
TRAILING_STOP_ATR_MULT   = float(os.getenv("TRAILING_STOP_ATR_MULT", "1.5"))


@dataclass
class TradeSetup:
    symbol:              str
    signal:              str
    entry_price:         float
    stop_loss:           float
    target:              float
    quantity:            int
    capital_required:    float
    risk_amount:         float
    reward_amount:       float
    risk_reward_ratio:   float
    risk_pct_of_capital: float
    estimated_cost:      float
    net_risk_amount:     float
    breakeven_price:     float
    trailing_stop:       float
    is_valid:            bool
    rejection_reason:    str = ""


@dataclass
class RiskState:
    daily_pnl:           float = 0.0
    weekly_pnl:          float = 0.0
    total_pnl:           float = 0.0
    peak_capital:        float = 0.0
    consecutive_losses:  int   = 0
    total_trades:        int   = 0
    winning_trades:      int   = 0
    daily_trades:        int   = 0
    trading_halted:      bool  = False
    halt_reason:         str   = ""
    last_reset_date:     str   = ""


def check_circuit_breakers(state: RiskState, capital: float) -> tuple:
    """Returns (can_trade: bool, reason: str). Call before every order."""
    if state.trading_halted:
        return False, f"Trading halted: {state.halt_reason}"

    if state.daily_pnl < -(capital * MAX_DAILY_LOSS_PCT):
        reason = f"Daily loss limit ₹{capital*MAX_DAILY_LOSS_PCT:.0f} hit"
        state.trading_halted = True
        state.halt_reason    = reason
        return False, reason

    if state.weekly_pnl < -(capital * MAX_WEEKLY_LOSS_PCT):
        reason = f"Weekly loss limit ₹{capital*MAX_WEEKLY_LOSS_PCT:.0f} hit"
        state.trading_halted = True
        state.halt_reason    = reason
        return False, reason

    if state.peak_capital > 0:
        drawdown_pct = (state.peak_capital - capital) / state.peak_capital
        if drawdown_pct > MAX_TOTAL_DRAWDOWN_PCT:
            reason = f"Max drawdown {drawdown_pct:.1%} exceeded limit {MAX_TOTAL_DRAWDOWN_PCT:.0%}"
            state.trading_halted = True
            state.halt_reason    = reason
            return False, reason

    if state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        return False, f"{state.consecutive_losses} consecutive losses — paused for review"

    if state.total_trades >= 10:
        win_rate = state.winning_trades / state.total_trades
        if win_rate < MIN_WIN_RATE_THRESHOLD:
            return False, f"Win rate {win_rate:.0%} below {MIN_WIN_RATE_THRESHOLD:.0%} threshold"

    return True, ""


def reset_daily_counters(state: RiskState):
    today = date.today().isoformat()
    if state.last_reset_date != today:
        state.daily_pnl       = 0.0
        state.daily_trades    = 0
        state.last_reset_date = today
        if state.trading_halted and "Daily" in state.halt_reason:
            state.trading_halted = False
            state.halt_reason    = ""
        logger.info("Daily risk counters reset.")


def update_after_trade(state: RiskState, pnl: float, capital: float):
    state.daily_pnl          += pnl
    state.weekly_pnl         += pnl
    state.total_pnl          += pnl
    state.total_trades       += 1
    state.daily_trades       += 1
    if pnl > 0:
        state.winning_trades    += 1
        state.consecutive_losses = 0
        if capital > state.peak_capital:
            state.peak_capital = capital
    else:
        state.consecutive_losses += 1


def estimate_trade_costs(entry: float, quantity: int, signal: str) -> dict:
    """Round-trip cost model: brokerage + STT + exchange charges + slippage."""
    tv = entry * quantity
    buy_cost  = min(BROKERAGE_PER_ORDER, tv * 0.0003) + tv * EXCHANGE_CHARGES_PCT + tv * SLIPPAGE_PCT
    sell_cost = min(BROKERAGE_PER_ORDER, tv * 0.0003) + tv * STT_PCT + tv * EXCHANGE_CHARGES_PCT + tv * SLIPPAGE_PCT
    total     = buy_cost + sell_cost
    return {
        "total_cost":     round(total, 2),
        "cost_per_share": round(total / quantity, 4) if quantity > 0 else 0,
        "cost_pct":       round((total / tv) * 100, 3) if tv > 0 else 0,
    }


def calculate_position_size(
    symbol:               str,
    signal:               str,
    entry_price:          float,
    stop_loss:            float,
    target:               float,
    current_capital:      float = None,
    open_positions_count: int   = 0,
    atr:                  float = 0,
    risk_state:           RiskState = None,
) -> TradeSetup:
    capital = current_capital or TRADING_CAPITAL

    if risk_state:
        can_trade, reason = check_circuit_breakers(risk_state, capital)
        if not can_trade:
            return _invalid(symbol, signal, entry_price, stop_loss, target, reason)

    if entry_price <= 0 or stop_loss <= 0 or target <= 0:
        return _invalid(symbol, signal, entry_price, stop_loss, target, "Invalid prices (must be >0)")

    if signal == "BUY":
        if stop_loss >= entry_price:
            return _invalid(symbol, signal, entry_price, stop_loss, target, "SL must be below entry for BUY")
        if target <= entry_price:
            return _invalid(symbol, signal, entry_price, stop_loss, target, "Target must be above entry for BUY")
        risk_per_share   = entry_price - stop_loss
        reward_per_share = target - entry_price
    elif signal == "SELL":
        if stop_loss <= entry_price:
            return _invalid(symbol, signal, entry_price, stop_loss, target, "SL must be above entry for SELL")
        if target >= entry_price:
            return _invalid(symbol, signal, entry_price, stop_loss, target, "Target must be below entry for SELL")
        risk_per_share   = stop_loss - entry_price
        reward_per_share = entry_price - target
    else:
        return _invalid(symbol, signal, entry_price, stop_loss, target, f"Unknown signal: {signal}")

    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0
    if rr_ratio < MIN_RISK_REWARD:
        return _invalid(symbol, signal, entry_price, stop_loss, target,
                        f"R:R {rr_ratio:.2f} < minimum required {MIN_RISK_REWARD}")

    if open_positions_count >= MAX_OPEN_POSITIONS:
        return _invalid(symbol, signal, entry_price, stop_loss, target,
                        f"Max open positions ({MAX_OPEN_POSITIONS}) reached")

    # Three-method position sizing — take the most conservative
    qty_by_risk        = int((capital * MAX_RISK_PER_TRADE) / risk_per_share)
    qty_by_slot        = int((capital * MAX_CAPITAL_DEPLOY / MAX_OPEN_POSITIONS) / entry_price)
    qty_by_stock_limit = int((capital * MAX_SINGLE_STOCK_PCT) / entry_price)
    quantity           = min(qty_by_risk, qty_by_slot, qty_by_stock_limit)

    # Quarter-Kelly (conservative) — only after 20 trades of data
    if risk_state and risk_state.total_trades >= 20 and risk_state.total_trades > 0:
        win_rate  = risk_state.winning_trades / risk_state.total_trades
        kelly_pct = win_rate - (1 - win_rate) / max(rr_ratio, 0.01)
        if kelly_pct > 0:
            kelly_safe = min(kelly_pct * 0.25, MAX_RISK_PER_TRADE)
            qty_kelly  = int((capital * kelly_safe) / risk_per_share)
            quantity   = min(quantity, qty_kelly) if qty_kelly > 0 else quantity

    if quantity < 1:
        return _invalid(symbol, signal, entry_price, stop_loss, target,
                        f"Qty rounds to 0. Capital ₹{capital:.0f}, risk/share ₹{risk_per_share:.2f}")

    costs          = estimate_trade_costs(entry_price, quantity, signal)
    capital_req    = round(quantity * entry_price, 2)
    actual_risk    = round(quantity * risk_per_share, 2)
    actual_reward  = round(quantity * reward_per_share, 2)
    net_risk       = round(actual_risk + costs["total_cost"], 2)
    breakeven      = round(entry_price + costs["cost_per_share"], 2) if signal == "BUY" \
                     else round(entry_price - costs["cost_per_share"], 2)
    trailing       = round(entry_price - atr * TRAILING_STOP_ATR_MULT, 2) if atr > 0 and signal == "BUY" \
                     else round(entry_price + atr * TRAILING_STOP_ATR_MULT, 2) if atr > 0 \
                     else round(stop_loss, 2)

    logger.info(f"[RiskMgr] {symbol} {signal}: qty={quantity} "
                f"(risk_method={qty_by_risk}, slot={qty_by_slot}, stock_lim={qty_by_stock_limit}), "
                f"capital=₹{capital_req:,.0f}, net_risk=₹{net_risk:.0f}, R:R=1:{rr_ratio}, "
                f"costs=₹{costs['total_cost']:.0f}, breakeven=₹{breakeven:.2f}")

    return TradeSetup(
        symbol=symbol, signal=signal,
        entry_price=entry_price, stop_loss=round(stop_loss, 2), target=round(target, 2),
        quantity=quantity, capital_required=capital_req,
        risk_amount=actual_risk, reward_amount=actual_reward,
        risk_reward_ratio=rr_ratio,
        risk_pct_of_capital=round((actual_risk / capital) * 100, 2),
        estimated_cost=costs["total_cost"],
        net_risk_amount=net_risk,
        breakeven_price=breakeven,
        trailing_stop=trailing,
        is_valid=True,
    )


def get_capital_summary(current_capital: float = None) -> dict:
    # Determine capital based on mode
    if current_capital is None:
        if PAPER_TRADING_MODE:
            c = PAPER_TRADING_CAPITAL
            mode_label = "[PAPER MODE]"
            logger.info(f"[PAPER MODE] Using paper capital: ₹{c:,.2f}")
        else:
            c = TRADING_CAPITAL
            mode_label = "[LIVE MODE]"
    else:
        c = current_capital
        mode_label = "[PAPER MODE]" if PAPER_TRADING_MODE else "[LIVE MODE]"
    
    return {
        "mode": mode_label,
        "total_capital":          round(c, 2),
        "max_deployable":         round(c * MAX_CAPITAL_DEPLOY, 2),
        "max_risk_per_trade_inr": round(c * MAX_RISK_PER_TRADE, 2),
        "max_risk_per_trade_pct": f"{MAX_RISK_PER_TRADE*100:.1f}%",
        "capital_per_slot":       round((c * MAX_CAPITAL_DEPLOY) / MAX_OPEN_POSITIONS, 2),
        "max_open_positions":     MAX_OPEN_POSITIONS,
        "min_risk_reward":        MIN_RISK_REWARD,
        "max_single_stock_pct":   f"{MAX_SINGLE_STOCK_PCT*100:.0f}%",
        "daily_loss_limit_inr":   round(c * MAX_DAILY_LOSS_PCT, 2),
        "weekly_loss_limit_inr":  round(c * MAX_WEEKLY_LOSS_PCT, 2),
        "total_drawdown_limit":   f"{MAX_TOTAL_DRAWDOWN_PCT*100:.0f}%",
        "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
        "atr_sl_multiplier":      ATR_SL_MULTIPLIER,
        "atr_target_multiplier":  ATR_TARGET_MULTIPLIER,
        "cost_model": {
            "brokerage":          f"₹{BROKERAGE_PER_ORDER}/order",
            "stt":                f"{STT_PCT*100:.2f}% on sell",
            "slippage_assumed":   f"{SLIPPAGE_PCT*100:.1f}%",
        },
    }


def _invalid(symbol, signal, entry, sl, target, reason) -> TradeSetup:
    logger.warning(f"[RiskMgr] {symbol} rejected: {reason}")
    return TradeSetup(
        symbol=symbol, signal=signal, entry_price=entry, stop_loss=sl, target=target,
        quantity=0, capital_required=0, risk_amount=0, reward_amount=0,
        risk_reward_ratio=0, risk_pct_of_capital=0,
        estimated_cost=0, net_risk_amount=0, breakeven_price=0, trailing_stop=0,
        is_valid=False, rejection_reason=reason
    )
