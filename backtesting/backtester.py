"""
backtesting/backtester.py

Vectorised backtesting engine for all strategies.
Supports: walk-forward testing, out-of-sample validation,
          full performance report (Sharpe, Calmar, Max Drawdown, Win Rate, etc.)

Usage:
    python -m backtesting.backtester --symbol RELIANCE --strategy ema_crossover --days 500
    python -m backtesting.backtester --symbol ALL --days 365
"""

import argparse
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd

from config.config import (
    TRADING_CAPITAL, MAX_RISK_PER_TRADE, MIN_RISK_REWARD,
    DEFAULT_WATCHLIST, ACTIVE_STRATEGIES, DATA_DIR
)
from core.kite_client import get_historical_data
from core.risk_manager import estimate_trade_costs, ATR_SL_MULTIPLIER, ATR_TARGET_MULTIPLIER
from strategies.strategies import add_all_indicators, STRATEGY_MAP

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    symbol:        str
    strategy:      str
    signal:        str
    entry_date:    str
    exit_date:     str
    entry_price:   float
    exit_price:    float
    stop_loss:     float
    target:        float
    quantity:      int
    gross_pnl:     float
    costs:         float
    net_pnl:       float
    exit_reason:   str    # TARGET_HIT / STOP_LOSS / TIME_EXIT
    holding_days:  int
    rr_achieved:   float


@dataclass
class BacktestResult:
    symbol:                str
    strategy:              str
    period_days:           int
    total_trades:          int
    winning_trades:        int
    losing_trades:         int
    win_rate:              float
    avg_win:               float
    avg_loss:              float
    profit_factor:         float
    total_net_pnl:         float
    total_pnl_pct:         float
    max_drawdown:          float
    max_drawdown_pct:      float
    sharpe_ratio:          float
    calmar_ratio:          float
    avg_holding_days:      float
    best_trade:            float
    worst_trade:           float
    expectancy:            float       # avg P&L per trade
    trades:                List[BacktestTrade]


# ─────────────────────────────────────────────────────────────────────────────
# Core Backtester
# ─────────────────────────────────────────────────────────────────────────────

def backtest_strategy(
    symbol:   str,
    strategy_name: str,
    df:       pd.DataFrame,
    capital:  float = None,
    in_sample_pct: float = 0.7,     # 70% in-sample, 30% out-of-sample
) -> BacktestResult:
    """
    Run a full backtest for one symbol + strategy.
    Uses walk-forward split to prevent overfitting.
    """
    capital = capital or TRADING_CAPITAL
    fn      = STRATEGY_MAP.get(strategy_name)
    if fn is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    df = add_all_indicators(df.copy())
    if len(df) < 60:
        raise ValueError(f"Not enough data for {symbol}: {len(df)} bars")

    # Walk-forward split
    split_idx   = int(len(df) * in_sample_pct)
    test_df     = df.iloc[split_idx:].copy()   # out-of-sample only
    logger.info(f"[Backtest] {symbol}/{strategy_name}: {len(test_df)} out-of-sample bars")

    trades      = []
    in_position = False
    entry_date  = entry_price = stop_loss = target = quantity = signal_type = None

    for i in range(20, len(test_df)):
        window = test_df.iloc[:i]
        row    = test_df.iloc[i]
        date   = str(row.name)[:10]

        if not in_position:
            # Generate signal on this bar
            result = fn(window, symbol)

            if result["signal"] in ("BUY", "SELL") and result["confidence"] >= 6:
                entry_price = result["entry"] or round(row["close"], 2)
                stop_loss   = result["stop_loss"]
                target      = result["target"]
                signal_type = result["signal"]

                if stop_loss <= 0 or target <= 0:
                    continue

                rr = abs(target - entry_price) / abs(entry_price - stop_loss) if abs(entry_price - stop_loss) > 0 else 0
                if rr < MIN_RISK_REWARD:
                    continue

                # Position sizing
                risk_per_share = abs(entry_price - stop_loss)
                max_risk       = capital * MAX_RISK_PER_TRADE
                quantity       = max(1, int(min(
                    max_risk / risk_per_share,
                    (capital * 0.20) / entry_price
                )))

                in_position = True
                entry_date  = date
                continue

        else:
            # Check exits
            high  = row["high"]
            low   = row["low"]
            close = row["close"]

            exit_price  = None
            exit_reason = None

            if signal_type == "BUY":
                if low <= stop_loss:
                    exit_price  = stop_loss
                    exit_reason = "STOP_LOSS"
                elif high >= target:
                    exit_price  = target
                    exit_reason = "TARGET_HIT"
            else:  # SELL
                if high >= stop_loss:
                    exit_price  = stop_loss
                    exit_reason = "STOP_LOSS"
                elif low <= target:
                    exit_price  = target
                    exit_reason = "TARGET_HIT"

            # Max holding: 20 trading days (swing trade limit)
            holding_days = (pd.Timestamp(date) - pd.Timestamp(entry_date)).days
            if holding_days >= 20 and exit_price is None:
                exit_price  = close
                exit_reason = "TIME_EXIT"

            if exit_price is not None:
                gross_pnl = (exit_price - entry_price) * quantity \
                            if signal_type == "BUY" \
                            else (entry_price - exit_price) * quantity

                costs     = estimate_trade_costs(entry_price, quantity, signal_type)["total_cost"]
                net_pnl   = round(gross_pnl - costs, 2)
                rr_ach    = round(abs(exit_price - entry_price) / abs(entry_price - stop_loss), 2) \
                            if abs(entry_price - stop_loss) > 0 else 0

                trades.append(BacktestTrade(
                    symbol=symbol, strategy=strategy_name, signal=signal_type,
                    entry_date=entry_date, exit_date=date,
                    entry_price=entry_price, exit_price=exit_price,
                    stop_loss=stop_loss, target=target,
                    quantity=quantity,
                    gross_pnl=round(gross_pnl, 2), costs=round(costs, 2), net_pnl=net_pnl,
                    exit_reason=exit_reason,
                    holding_days=holding_days,
                    rr_achieved=rr_ach,
                ))

                capital     += net_pnl
                in_position = False
                entry_date  = entry_price = stop_loss = target = quantity = signal_type = None

    return _compute_metrics(symbol, strategy_name, len(test_df), trades, capital)


def _compute_metrics(symbol: str, strategy: str, bars: int,
                     trades: List[BacktestTrade], final_capital: float) -> BacktestResult:
    if not trades:
        return BacktestResult(
            symbol=symbol, strategy=strategy, period_days=bars,
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, avg_win=0, avg_loss=0, profit_factor=0,
            total_net_pnl=0, total_pnl_pct=0,
            max_drawdown=0, max_drawdown_pct=0,
            sharpe_ratio=0, calmar_ratio=0,
            avg_holding_days=0, best_trade=0, worst_trade=0,
            expectancy=0, trades=[],
        )

    pnls          = [t.net_pnl for t in trades]
    winning       = [p for p in pnls if p > 0]
    losing        = [p for p in pnls if p <= 0]
    total_net_pnl = sum(pnls)
    win_rate      = len(winning) / len(pnls) if pnls else 0
    avg_win       = np.mean(winning) if winning else 0
    avg_loss      = abs(np.mean(losing)) if losing else 0
    profit_factor = (sum(winning) / abs(sum(losing))) if losing and sum(losing) != 0 else float("inf")
    expectancy    = np.mean(pnls) if pnls else 0

    # Drawdown
    cumulative    = np.cumsum(pnls)
    running_max   = np.maximum.accumulate(cumulative + TRADING_CAPITAL)
    drawdowns     = running_max - (cumulative + TRADING_CAPITAL)
    max_drawdown  = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0
    max_dd_pct    = (max_drawdown / running_max[np.argmax(drawdowns)]) * 100 if max_drawdown > 0 else 0

    # Sharpe ratio (annualised, assuming 252 trading days)
    if len(pnls) > 1 and np.std(pnls) > 0:
        daily_returns = np.array(pnls) / TRADING_CAPITAL
        sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252)
    else:
        sharpe = 0.0

    # Calmar = annualised return / max drawdown
    annualised_return = (total_net_pnl / TRADING_CAPITAL) * (252 / max(bars, 1)) * 100
    calmar = (annualised_return / max_dd_pct) if max_dd_pct > 0 else 0

    return BacktestResult(
        symbol=symbol, strategy=strategy, period_days=bars,
        total_trades=len(trades), winning_trades=len(winning), losing_trades=len(losing),
        win_rate=round(win_rate * 100, 1),
        avg_win=round(avg_win, 2), avg_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        total_net_pnl=round(total_net_pnl, 2),
        total_pnl_pct=round((total_net_pnl / TRADING_CAPITAL) * 100, 2),
        max_drawdown=round(max_drawdown, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        sharpe_ratio=round(sharpe, 2),
        calmar_ratio=round(calmar, 2),
        avg_holding_days=round(np.mean([t.holding_days for t in trades]), 1),
        best_trade=round(max(pnls), 2),
        worst_trade=round(min(pnls), 2),
        expectancy=round(expectancy, 2),
        trades=trades,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pre-trade backtest check (called by trading engine before placing order)
# ─────────────────────────────────────────────────────────────────────────────

def quick_backtest_check(symbol: str, strategy_name: str, df: pd.DataFrame,
                         min_win_rate: float = 45.0,
                         min_profit_factor: float = 1.2) -> dict:
    """
    Lightweight backtest run before placing a live order.
    Returns: {"approved": bool, "reason": str, "win_rate": float, "profit_factor": float}
    """
    try:
        result = backtest_strategy(symbol, strategy_name, df)
        if result.total_trades < 5:
            return {"approved": True, "reason": "Insufficient backtest data — proceeding", "win_rate": 0, "profit_factor": 0}

        approved = result.win_rate >= min_win_rate and result.profit_factor >= min_profit_factor
        reason   = (
            f"Win rate: {result.win_rate:.1f}% (min {min_win_rate}%), "
            f"Profit factor: {result.profit_factor:.2f} (min {min_profit_factor})"
        )
        return {
            "approved":      approved,
            "reason":        reason,
            "win_rate":      result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades":  result.total_trades,
            "sharpe":        result.sharpe_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
        }
    except Exception as e:
        logger.error(f"Quick backtest failed for {symbol}/{strategy_name}: {e}")
        return {"approved": True, "reason": f"Backtest error (proceeding): {e}", "win_rate": 0, "profit_factor": 0}


# ─────────────────────────────────────────────────────────────────────────────
# Print report
# ─────────────────────────────────────────────────────────────────────────────

def print_report(r: BacktestResult):
    rating = "🟢 GOOD" if r.sharpe_ratio > 1 and r.win_rate > 45 else \
             "🟡 AVERAGE" if r.profit_factor > 1 else "🔴 POOR"

    print(f"""
╔══════════════════════════════════════════════════════════╗
  BACKTEST REPORT — {r.symbol} / {r.strategy}  {rating}
╠══════════════════════════════════════════════════════════╣
  Period       : {r.period_days} bars (out-of-sample)
  Total Trades : {r.total_trades}  ({r.winning_trades}W / {r.losing_trades}L)
  Win Rate     : {r.win_rate:.1f}%
  Avg Win      : ₹{r.avg_win:,.0f}   Avg Loss: ₹{r.avg_loss:,.0f}
  Profit Factor: {r.profit_factor:.2f}
  Expectancy   : ₹{r.expectancy:,.0f} per trade
──────────────────────────────────────────────────────────
  Net P&L      : ₹{r.total_net_pnl:+,.0f}  ({r.total_pnl_pct:+.1f}%)
  Max Drawdown : ₹{r.max_drawdown:,.0f}  ({r.max_drawdown_pct:.1f}%)
  Sharpe Ratio : {r.sharpe_ratio:.2f}
  Calmar Ratio : {r.calmar_ratio:.2f}
──────────────────────────────────────────────────────────
  Avg Hold     : {r.avg_holding_days:.1f} days
  Best Trade   : ₹{r.best_trade:+,.0f}
  Worst Trade  : ₹{r.worst_trade:+,.0f}
╚══════════════════════════════════════════════════════════╝
""")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest trading strategies")
    parser.add_argument("--symbol",   default="RELIANCE", help="Stock symbol or ALL")
    parser.add_argument("--strategy", default="all",      help="Strategy name or all")
    parser.add_argument("--days",     type=int, default=500, help="Historical days to fetch")
    parser.add_argument("--save",     action="store_true",   help="Save results to JSON")
    args = parser.parse_args()

    symbols    = DEFAULT_WATCHLIST if args.symbol == "ALL" else [args.symbol.upper()]
    strategies = list(STRATEGY_MAP.keys()) if args.strategy == "all" else [args.strategy]
    # Skip claude_ai for backtesting (too slow + costly)
    strategies = [s for s in strategies if s != "claude_ai"]

    all_results = []

    for sym in symbols:
        print(f"\nFetching data for {sym}...")
        df = get_historical_data(sym, interval="day", days=args.days)
        if df.empty:
            print(f"  No data for {sym}, skipping.")
            continue

        for strat in strategies:
            try:
                result = backtest_strategy(sym, strat, df)
                print_report(result)
                all_results.append(asdict(result))
            except Exception as e:
                print(f"  Error: {sym}/{strat}: {e}")

    if args.save and all_results:
        os.makedirs(DATA_DIR, exist_ok=True)
        out_file = os.path.join(DATA_DIR, f"backtest_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
        # Remove trade-level detail for summary save
        for r in all_results:
            r.pop("trades", None)
        with open(out_file, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\nResults saved to {out_file}")
