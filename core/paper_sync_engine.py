"""
core/paper_sync_engine.py

Paper Trading Sync Engine - Simulates order fills, GTT triggers, and position management.
This runs periodically to:
1. Check pending orders and "fill" them after delay
2. Monitor open positions against live market prices
3. Trigger paper GTT exits when SL/target hit
4. Calculate unrealized and realized P&L
"""

import logging
import json
from datetime import datetime
from typing import Dict, List, Optional
from config.config import DATA_DIR, PAPER_TRADING_MODE
from core.paper_trading_client import PaperTradingClient

logger = logging.getLogger(__name__)


def sync_paper_positions():
    """
    Main synchronization function for paper trading.
    Call this periodically (every 5 minutes) via scheduler.
    """
    if not PAPER_TRADING_MODE:
        logger.debug("Not in paper mode, skipping paper sync")
        return
    
    client = PaperTradingClient()
    state = client.state
    
    logger.info("[PAPER SYNC] Starting paper trading synchronization...")
    
    # Step 1: Process pending orders (simulate fills)
    filled_count = _process_pending_orders(client, state)
    
    # Step 2: Update unrealized P&L for open positions
    pnl_updates = _update_unrealized_pnl(client, state)
    
    # Step 3: Check GTT triggers (stop loss / target)
    triggered_count = _check_gtt_triggers(client, state)
    
    # Step 4: Save state
    client._save_state()
    
    logger.info(
        f"[PAPER SYNC] Complete: {filled_count} orders filled, "
        f"{pnl_updates} positions updated, {triggered_count} GTTs triggered"
    )


def _process_pending_orders(client: PaperTradingClient, state: Dict) -> int:
    """
    Check pending orders and "fill" them after configured delay.
    Simulates order execution with realistic timing.
    """
    filled_count = 0
    now = datetime.now()
    
    symbols_to_remove = []
    
    for symbol, order_data in state["pending_orders"].items():
        order_id = order_data["order_id"]
        fill_after = datetime.fromisoformat(order_data["fill_after"])
        
        # Check if enough time has passed for fill
        if now >= fill_after:
            # Update order status to COMPLETE
            if order_id in state["orders"]:
                state["orders"][order_id]["status"] = "COMPLETE"
                state["orders"][order_id]["fill_timestamp"] = now.isoformat()
                state["orders"][order_id]["status_message"] = "Order filled (simulated)"
            
            # Move to open positions
            state["open_positions"][symbol] = {
                "symbol": symbol,
                "order_id": order_id,
                "signal": order_data["signal"],
                "entry": order_data["price"],
                "quantity": order_data["quantity"],
                "date": order_data["date"],
                "current_price": order_data["price"],  # Will be updated by price sync
                "unrealised_pnl": 0.0,
                "gtt_id": None  # Will be set if GTT is placed
            }
            
            symbols_to_remove.append(symbol)
            filled_count += 1
            
            logger.info(
                f"[PAPER SYNC] Order filled: {symbol} {order_data['signal']} "
                f"{order_data['quantity']} @ ₹{order_data['price']:.2f}"
            )
    
    # Remove filled orders from pending
    for symbol in symbols_to_remove:
        del state["pending_orders"][symbol]
    
    return filled_count


def _update_unrealized_pnl(client: PaperTradingClient, state: Dict) -> int:
    """
    Update unrealized P&L for all open positions using live market prices.
    """
    if not state["open_positions"]:
        return 0
    
    symbols = list(state["open_positions"].keys())
    
    try:
        # Get current market prices
        ltp_data = client.ltp([f"NSE:{s}" for s in symbols])
        
        updated_count = 0
        for symbol, position in state["open_positions"].items():
            key = f"NSE:{symbol}"
            if key in ltp_data and "last_price" in ltp_data[key]:
                current_price = ltp_data[key]["last_price"]
                entry_price = position["entry"]
                quantity = position["quantity"]
                signal = position["signal"]
                
                # Calculate unrealized P&L
                if signal == "BUY":
                    unrealised_pnl = (current_price - entry_price) * quantity
                else:  # SELL (short)
                    unrealised_pnl = (entry_price - current_price) * quantity
                
                # Update position
                position["current_price"] = current_price
                position["unrealised_pnl"] = round(unrealised_pnl, 2)
                updated_count += 1
        
        return updated_count
    
    except Exception as e:
        logger.error(f"[PAPER SYNC] Error updating P&L: {e}")
        return 0


def _check_gtt_triggers(client: PaperTradingClient, state: Dict) -> int:
    """
    Check if any GTT orders should be triggered based on current market prices.
    Simulates automatic stop-loss and target exits.
    """
    if not state["gtt_orders"]:
        return 0
    
    triggered_count = 0
    gtts_to_trigger = []
    
    for gtt_id, gtt in state["gtt_orders"].items():
        if gtt["status"] != "active":
            continue
        
        symbol = gtt["tradingsymbol"]
        
        # Check if we have an open position for this symbol
        if symbol not in state["open_positions"]:
            continue
        
        position = state["open_positions"][symbol]
        current_price = position.get("current_price", position["entry"])
        
        # GTT trigger values: [stop_loss, target]
        stop_loss = gtt["trigger_values"][0]
        target = gtt["trigger_values"][1]
        
        # Check if stop loss hit
        if current_price <= stop_loss:
            gtts_to_trigger.append((gtt_id, symbol, current_price, "STOP_LOSS_HIT"))
            triggered_count += 1
        
        # Check if target hit
        elif current_price >= target:
            gtts_to_trigger.append((gtt_id, symbol, current_price, "TARGET_HIT"))
            triggered_count += 1
    
    # Process triggered GTTs
    for gtt_id, symbol, exit_price, exit_type in gtts_to_trigger:
        _execute_gtt_exit(client, state, gtt_id, symbol, exit_price, exit_type)
    
    return triggered_count


def _execute_gtt_exit(
    client: PaperTradingClient,
    state: Dict,
    gtt_id: str,
    symbol: str,
    exit_price: float,
    exit_type: str
):
    """
    Execute a GTT exit - move position from open to closed and calculate realized P&L.
    """
    if symbol not in state["open_positions"]:
        logger.warning(f"[PAPER SYNC] GTT triggered for {symbol} but no open position found")
        return
    
    position = state["open_positions"][symbol]
    entry_price = position["entry"]
    quantity = position["quantity"]
    signal = position["signal"]
    
    # Calculate realized P&L
    if signal == "BUY":
        realised_pnl = (exit_price - entry_price) * quantity
    else:  # SELL (short)
        realised_pnl = (entry_price - exit_price) * quantity
    
    # Update total P&L
    state["total_pnl"] += realised_pnl
    
    # Mark GTT as triggered
    if gtt_id in state["gtt_orders"]:
        state["gtt_orders"][gtt_id]["status"] = "triggered"
        state["gtt_orders"][gtt_id]["triggered_at"] = datetime.now().isoformat()
        state["gtt_orders"][gtt_id]["trigger_price"] = exit_price
    
    # Move position to closed
    closed_position = {
        "symbol": symbol,
        "signal": signal,
        "entry": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "exit_type": exit_type,
        "exit_date": datetime.now().isoformat(),
        "realised_pnl": round(realised_pnl, 2),
        "strategy": position.get("strategy", "unknown"),
        "order_id": position.get("order_id"),
        "gtt_id": gtt_id
    }
    
    state["closed_positions"].append(closed_position)
    
    # Remove from open positions
    del state["open_positions"][symbol]
    
    logger.info(
        f"[PAPER SYNC] GTT Exit: {symbol} {exit_type} @ ₹{exit_price:.2f} "
        f"| P&L: ₹{realised_pnl:,.2f} | Total P&L: ₹{state['total_pnl']:,.2f}"
    )


def get_paper_performance_summary() -> Dict:
    """
    Get comprehensive paper trading performance metrics.
    """
    if not PAPER_TRADING_MODE:
        return {"mode": "LIVE", "message": "Not in paper trading mode"}
    
    client = PaperTradingClient()
    state = client.state
    
    closed_trades = state["closed_positions"]
    open_positions = state["open_positions"]
    
    # Calculate metrics
    total_trades = len(closed_trades)
    winning_trades = sum(1 for trade in closed_trades if trade.get("realised_pnl", 0) > 0)
    losing_trades = sum(1 for trade in closed_trades if trade.get("realised_pnl", 0) < 0)
    
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    
    total_wins = sum(trade["realised_pnl"] for trade in closed_trades if trade.get("realised_pnl", 0) > 0)
    total_losses = abs(sum(trade["realised_pnl"] for trade in closed_trades if trade.get("realised_pnl", 0) < 0))
    
    avg_win = total_wins / winning_trades if winning_trades > 0 else 0.0
    avg_loss = total_losses / losing_trades if losing_trades > 0 else 0.0
    
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf') if total_wins > 0 else 0.0
    
    # Calculate unrealized P&L
    unrealised_pnl = sum(pos.get("unrealised_pnl", 0.0) for pos in open_positions.values())
    
    # Capital and returns
    capital = state["paper_capital"]
    total_realised_pnl = state["total_pnl"]
    total_pnl = total_realised_pnl + unrealised_pnl
    return_pct = (total_pnl / capital * 100) if capital > 0 else 0.0
    
    return {
        "mode": "PAPER",
        "capital": capital,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "N/A",
        "realised_pnl": round(total_realised_pnl, 2),
        "unrealised_pnl": round(unrealised_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(return_pct, 2),
        "open_positions": len(open_positions),
        "closed_positions": len(closed_trades)
    }


def reset_paper_trading():
    """
    Reset all paper trading data. Useful for testing or starting fresh.
    WARNING: This will clear all paper positions and P&L.
    """
    if not PAPER_TRADING_MODE:
        logger.warning("Not in paper mode, nothing to reset")
        return False
    
    client = PaperTradingClient()
    client.reset_paper_state()
    logger.warning("[PAPER MODE] All paper trading data has been reset")
    return True
