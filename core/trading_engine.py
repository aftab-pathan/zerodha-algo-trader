"""
core/trading_engine.py
Main orchestrator: scan watchlist → run strategies → risk check → execute orders
→ update Zerodha watchlist → send Telegram notifications.
"""

import json
import logging
import os
import csv
import time
from datetime import datetime

import pandas as pd

from config.config import (
    TRADING_CAPITAL, ACTIVE_STRATEGIES, DEFAULT_WATCHLIST,
    MIN_CONFIDENCE, STATE_FILE, TRADE_LOG_FILE, LOG_DIR, DATA_DIR,
    ENABLE_BULK_SCAN, BULK_SCAN_SIZE, ENABLE_TWO_TIER_CLAUDE,
    BULK_SCAN_STRATEGIES, MAX_CLAUDE_STOCKS, MIN_CONFIDENCE_FOR_CLAUDE,
    TRADE_DIRECTION
)
from core.kite_client import (
    get_historical_data, get_positions, get_holdings, get_portfolio_value,
    place_order, place_gtt_oco, add_to_watchlist, clear_watchlist,
    get_ltp, is_authenticated
)
from core.risk_manager import calculate_position_size, get_capital_summary, TradeSetup
from strategies.strategies import run_strategies, get_consensus_signal
from utils.telegram_notifier import (
    notify_signal, notify_order_placed, notify_exit,
    notify_daily_summary, notify_watchlist_updated, notify_error
)
from utils.security import audit_log

logger = logging.getLogger(__name__)

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# State management (open positions tracked locally)
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"open_positions": {}, "daily_stats": {}, "total_pnl": 0.0}


def _save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _log_trade(row: dict):
    """Append a trade record to trades.csv."""
    os.makedirs(LOG_DIR, exist_ok=True)
    write_header = not os.path.exists(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ─────────────────────────────────────────────────────────────────────────────
# Core Scan
# ─────────────────────────────────────────────────────────────────────────────

def scan_and_trade(watchlist: list = None, dry_run: bool = False, 
                   use_bulk_scan: bool = None, bulk_size: int = None) -> dict:
    """
    Main function: scan all watchlist stocks, generate signals, place orders.
    
    Two-tier Claude optimization for bulk scans:
    - Stage 2A: Run fast technical strategies on all stocks
    - Stage 2B: Run Claude only on top shortlisted stocks
    
    Args:
        watchlist: List of symbols to scan (default: DEFAULT_WATCHLIST)
        dry_run: If True, generate signals but don't place real orders
        use_bulk_scan: Enable 2-stage bulk scanning (default: from config.ENABLE_BULK_SCAN)
        bulk_size: Universe size for bulk scan (default: from config.BULK_SCAN_SIZE)
    
    Returns:
        Summary dict with scan results
    """
    if not is_authenticated():
        msg = "Kite not authenticated. Run login first."
        logger.error(msg)
        notify_error("Trading Engine", msg)
        return {"error": msg}

    # Determine which watchlist to use
    if use_bulk_scan is None:
        use_bulk_scan = ENABLE_BULK_SCAN
    
    if use_bulk_scan:
        # Use dynamic universe builder (2-stage filtering)
        try:
            from core.stock_universe import get_filtered_universe
            
            size = bulk_size or BULK_SCAN_SIZE
            logger.info(f"🔍 BULK SCAN MODE: Building filtered universe (target size: {size})...")
            
            watchlist = get_filtered_universe(size=size, use_cache=True)
            
            if not watchlist:
                logger.warning("Bulk scan returned empty universe, falling back to DEFAULT_WATCHLIST")
                watchlist = DEFAULT_WATCHLIST
            else:
                logger.info(f"✅ Stage 1 complete: {len(watchlist)} stocks passed pre-filters")
                
        except Exception as e:
            logger.error(f"Bulk scan failed: {e}, falling back to DEFAULT_WATCHLIST")
            watchlist = DEFAULT_WATCHLIST
            use_bulk_scan = False
    else:
        watchlist = watchlist or DEFAULT_WATCHLIST
    
    # Determine which strategies to use
    # Two-tier mode: Use technical strategies first, Claude later
    use_two_tier = use_bulk_scan and ENABLE_TWO_TIER_CLAUDE and "claude_ai" in ACTIVE_STRATEGIES
    
    if use_two_tier:
        strategies_pass1 = [s for s in BULK_SCAN_STRATEGIES if s in ["ema_crossover", "rsi_reversal", 
                           "macd_momentum", "breakout", "52w_breakout"]]
        logger.info(f"🎯 TWO-TIER MODE: Pass 1 with {len(strategies_pass1)} technical strategies, "
                   f"then Claude on top {MAX_CLAUDE_STOCKS} stocks")
    else:
        strategies_pass1 = ACTIVE_STRATEGIES
    
    state = _load_state()
    open_count = len(state.get("open_positions", {}))
    capital = TRADING_CAPITAL

    summary = {
        "scanned": 0, "signals": 0, "orders_placed": 0,
        "rejected": 0, "shortlisted": [], "errors": [],
        "bulk_scan": use_bulk_scan, "universe_size": len(watchlist),
        "two_tier": use_two_tier, "claude_analyzed": 0
    }

    # ═══════════════════════════════════════════════════════════════
    # STAGE 2A: Technical Analysis (Fast)
    # ═══════════════════════════════════════════════════════════════
    
    technical_signals = []  # Store signals with metadata
    scan_mode = "BULK SCAN (Two-Tier)" if use_two_tier else ("BULK SCAN" if use_bulk_scan else "STANDARD")
    
    logger.info(f"━━━ {scan_mode}: Stage 2A on {len(watchlist)} stocks | "
                f"Capital ₹{capital:,.0f} | Open positions: {open_count} ━━━")

    for idx, symbol in enumerate(watchlist, 1):
        try:
            df = get_historical_data(symbol, interval="day", days=500)
            
            # Rate limiting for historical_data API (3 req/sec limit)
            if idx < len(watchlist):
                time.sleep(0.35)  # 2.85 req/sec with safety margin
            
            if df.empty or len(df) < 60:
                logger.warning(f"Insufficient data for {symbol}, skipping.")
                continue

            summary["scanned"] += 1
            
            # Progress logging for bulk scans
            if use_bulk_scan and summary["scanned"] % 50 == 0:
                logger.info(f"Progress: {summary['scanned']}/{len(watchlist)} stocks analyzed...")
            
            # Run technical strategies only
            signals = run_strategies(df, symbol, strategies_pass1)

            if not signals:
                continue

            # Get best / consensus signal
            best = get_consensus_signal(signals)
            if not best or best["signal"] == "HOLD":
                continue
            
            # Store for potential Claude analysis
            technical_signals.append({
                "symbol": symbol,
                "df": df,
                "signal": best,
                "confidence": best["confidence"]
            })
            
            summary["shortlisted"].append(symbol)
            summary["signals"] += 1

        except Exception as e:
            err_msg = f"{symbol}: {str(e)}"
            logger.error(f"Error scanning {err_msg}")
            summary["errors"].append(err_msg)

    # ═══════════════════════════════════════════════════════════════
    # STAGE 2B: Claude Analysis on Top Picks (Two-Tier Mode Only)
    # ═══════════════════════════════════════════════════════════════
    
    all_signals = []
    
    if use_two_tier and technical_signals:
        # Sort by confidence and take top N
        technical_signals.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Filter by minimum confidence threshold
        qualified = [s for s in technical_signals if s["confidence"] >= MIN_CONFIDENCE_FOR_CLAUDE]
        top_picks = qualified[:MAX_CLAUDE_STOCKS]
        
        logger.info(f"━━━ Stage 2B: Claude analysis on top {len(top_picks)} stocks "
                   f"(from {len(technical_signals)} technical signals) ━━━")
        
        for pick in top_picks:
            symbol = pick["symbol"]
            try:
                # Run Claude strategy only
                claude_signals = run_strategies(pick["df"], symbol, ["claude_ai"])
                summary["claude_analyzed"] += 1
                
                if claude_signals:
                    # Use Claude's signal if it confirms, otherwise use technical
                    claude_best = get_consensus_signal(claude_signals)
                    if claude_best and claude_best["signal"] != "HOLD":
                        # Claude confirmed - use its signal
                        all_signals.append(claude_best)
                        logger.info(f"✅ Claude confirmed {symbol}: {claude_best['signal']} "
                                  f"(confidence {claude_best['confidence']})")
                    else:
                        # Claude said HOLD - use technical signal anyway
                        all_signals.append(pick["signal"])
                        logger.info(f"⚠️  Claude neutral on {symbol}, using technical signal")
                else:
                    # Claude failed - use technical signal
                    all_signals.append(pick["signal"])
                    
            except Exception as e:
                logger.error(f"Claude analysis failed for {symbol}: {e}")
                # Fallback to technical signal
                all_signals.append(pick["signal"])
                summary["errors"].append(f"{symbol} Claude: {str(e)}")
        
        # Add remaining technical signals that didn't get Claude analysis
        remaining = technical_signals[len(top_picks):]
        for pick in remaining:
            all_signals.append(pick["signal"])
        
        logger.info(f"📊 Final signals: {len(all_signals)} total "
                   f"({summary['claude_analyzed']} Claude-enhanced)")
    else:
        # Standard mode or no technical signals - use what we have
        all_signals = [s["signal"] for s in technical_signals]

    # ═══════════════════════════════════════════════════════════════
    # STAGE 3: Risk Management & Order Execution
    # ═══════════════════════════════════════════════════════════════
    
    logger.info(f"━━━ Stage 3: Processing {len(all_signals)} signals for order execution ━━━")
    
    # Filter signals by TRADE_DIRECTION
    filtered_signals = []
    for sig in all_signals:
        if TRADE_DIRECTION == "BOTH":
            filtered_signals.append(sig)
        elif TRADE_DIRECTION == sig.get("signal"):
            filtered_signals.append(sig)
        else:
            symbol = sig.get("symbol", "UNKNOWN")
            logger.info(f"Skipping {symbol} {sig.get('signal')} signal (TRADE_DIRECTION={TRADE_DIRECTION})")
    
    if len(filtered_signals) < len(all_signals):
        logger.info(f"Filtered {len(all_signals)} → {len(filtered_signals)} signals by direction ({TRADE_DIRECTION} only)")
    
    for best in filtered_signals:
        symbol = best.get("symbol", best.get("reasoning", "UNKNOWN").split()[0] if best.get("reasoning") else "UNKNOWN")
        
        try:
            # ── Risk management ─────────────────────────────────────────────
            setup: TradeSetup = calculate_position_size(
                symbol=symbol,
                signal=best["signal"],
                entry_price=best["entry"],
                stop_loss=best["stop_loss"],
                target=best["target"],
                current_capital=capital,
                open_positions_count=open_count,
            )

            # Always send signal notification
            notify_signal(
                symbol=symbol,
                signal=best["signal"],
                strategy=best["strategy"],
                entry=setup.entry_price,
                sl=setup.stop_loss,
                target=setup.target,
                qty=setup.quantity,
                capital_used=setup.capital_required,
                confidence=best["confidence"],
                reasoning=best["reasoning"],
            )

            if not setup.is_valid:
                logger.warning(f"Trade setup invalid for {symbol}: {setup.rejection_reason}")
                summary["rejected"] += 1
                continue

            if best["confidence"] < MIN_CONFIDENCE:
                logger.info(f"Confidence {best['confidence']} < {MIN_CONFIDENCE} for {symbol}, skip.")
                summary["rejected"] += 1
                continue

            # ── Order execution ─────────────────────────────────────────────
            if not dry_run:
                order_id = place_order(
                    symbol=symbol,
                    transaction_type=best["signal"],
                    quantity=setup.quantity,
                    price=setup.entry_price,
                    order_type="LIMIT",
                )

                if order_id:
                    # Place GTT for auto SL + Target (works even when system offline)
                    gtt_id = place_gtt_oco(
                        symbol=symbol,
                        quantity=setup.quantity,
                        entry_price=setup.entry_price,
                        stop_loss=setup.stop_loss,
                        target=setup.target,
                    )

                    # Track in state
                    state["open_positions"][symbol] = {
                        "order_id":  order_id,
                        "gtt_id":    gtt_id,
                        "signal":    best["signal"],
                        "entry":     setup.entry_price,
                        "stop_loss": setup.stop_loss,
                        "target":    setup.target,
                        "quantity":  setup.quantity,
                        "strategy":  best["strategy"],
                        "date":      datetime.now().isoformat(),
                    }
                    open_count += 1
                    summary["orders_placed"] += 1

                    notify_order_placed(symbol, order_id, best["signal"],
                                        setup.quantity, setup.entry_price)

                    _log_trade({
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "symbol": symbol, "signal": best["signal"],
                        "strategy": best["strategy"],
                        "entry": setup.entry_price, "sl": setup.stop_loss,
                        "target": setup.target, "qty": setup.quantity,
                        "capital": setup.capital_required,
                        "risk": setup.risk_amount, "rr": setup.risk_reward_ratio,
                        "confidence": best["confidence"], "order_id": order_id,
                        "gtt_id": gtt_id or ""
                    })
                    audit_log("TRADE_ENTRY", {
                        "symbol": symbol, "signal": best["signal"],
                        "qty": setup.quantity, "order_id": order_id
                    })
            else:
                logger.info(f"[DRY RUN] Would place {best['signal']} {symbol} "
                            f"qty={setup.quantity} @ ₹{setup.entry_price:.2f}")
                summary["orders_placed"] += 1   # count in dry run

        except Exception as e:
            err_msg = f"{symbol}: {str(e)}"
            logger.error(f"Error scanning {err_msg}")
            summary["errors"].append(err_msg)
            notify_error("Scan", err_msg)

    # ── Update Zerodha watchlist ─────────────────────────────────────────────
    if summary["shortlisted"]:
        try:
            clear_watchlist("AlgoTrader Picks")
            added = add_to_watchlist(summary["shortlisted"])
            notify_watchlist_updated(added, len(added))
        except Exception as e:
            logger.error(f"Watchlist update failed: {e}")

    _save_state(state)
    logger.info(f"Scan complete: {summary}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Daily Summary
# ─────────────────────────────────────────────────────────────────────────────

def send_daily_summary():
    """Compute and send EOD P&L summary via Telegram."""
    try:
        state = _load_state()
        holdings_df = get_holdings()
        pnl = 0.0
        if not holdings_df.empty and "pnl" in holdings_df.columns:
            pnl = holdings_df["pnl"].sum()

        portfolio_value = get_portfolio_value()
        stats = {
            "signals":        0,
            "orders":         len(state.get("open_positions", {})),
            "open_positions": len(state.get("open_positions", {})),
            "total_pnl":      round(pnl, 2),
            "capital_used":   sum(
                p.get("entry", 0) * p.get("quantity", 0)
                for p in state.get("open_positions", {}).values()
            ),
            "portfolio_value": portfolio_value,
            "win_rate": _calc_win_rate(),
        }
        notify_daily_summary(stats)
        return stats
    except Exception as e:
        logger.error(f"Daily summary failed: {e}")
        notify_error("Daily Summary", str(e))
        return {}


def _calc_win_rate() -> float:
    """Calculate win rate from trade log CSV."""
    if not os.path.exists(TRADE_LOG_FILE):
        return 0.0
    try:
        df = pd.read_csv(TRADE_LOG_FILE)
        if df.empty or "pnl" not in df.columns:
            return 0.0
        wins = (df["pnl"] > 0).sum()
        return round((wins / len(df)) * 100, 1)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Capital Management
# ─────────────────────────────────────────────────────────────────────────────

def update_capital(new_capital: float) -> dict:
    """
    Update trading capital. Changes take effect immediately on next scan.
    Also updates the .env file.
    """
    if new_capital < 1000:
        raise ValueError("Minimum capital is ₹1,000")

    # Update the running process env
    os.environ["TRADING_CAPITAL"] = str(new_capital)

    # Persist to .env
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    lines = []
    if os.path.exists(env_file):
        with open(env_file) as f:
            lines = f.readlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith("TRADING_CAPITAL="):
            lines[i] = f"TRADING_CAPITAL={new_capital}\n"
            updated = True
            break
    if not updated:
        lines.append(f"TRADING_CAPITAL={new_capital}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)

    audit_log("CONFIG_CHANGED", {"field": "TRADING_CAPITAL", "new_value": new_capital})
    summary = get_capital_summary(new_capital)
    logger.info(f"Capital updated to ₹{new_capital:,.0f}")
    return summary
