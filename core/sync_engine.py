"""
core/sync_engine.py  (v2 — with Time Exit, Partial Booking, VIX Filter)

DROP-IN REPLACEMENT for core/sync_engine.py

New in v2:
  - check_time_based_exits(): exits sideways/stale positions automatically
  - check_partial_exits():    books 50% profit at T1, moves SL to breakeven, targets T2
  - get_india_vix() + vix multiplier exported for scan_and_trade()
"""

import json
import logging
import os
from datetime import datetime

import pandas as pd

from config.config import DATA_DIR, LOG_DIR
from core.kite_client import get_kite, get_holdings, get_positions, get_ltp, place_order
from utils.telegram_notifier import _send, notify_error
from utils.security import audit_log

logger = logging.getLogger(__name__)
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# ── Configurable params ───────────────────────────────────────────────────────
MAX_HOLD_DAYS        = int(os.getenv("MAX_HOLD_DAYS",         "15"))
SIDEWAYS_DAYS        = int(os.getenv("SIDEWAYS_DAYS",         "8"))
SIDEWAYS_PCT         = float(os.getenv("SIDEWAYS_PCT",        "0.005"))
PARTIAL_BOOK_PCT     = float(os.getenv("PARTIAL_BOOK_PCT",    "0.50"))
PARTIAL_TARGET_MULT  = float(os.getenv("PARTIAL_TARGET_MULT", "1.5"))
ENABLE_PARTIAL_EXIT  = os.getenv("ENABLE_PARTIAL_EXIT",  "true").lower() == "true"
VIX_REDUCE_THRESHOLD = float(os.getenv("VIX_REDUCE_THRESHOLD", "20.0"))
VIX_HALT_THRESHOLD   = float(os.getenv("VIX_HALT_THRESHOLD",   "30.0"))


# ─────────────────────────────────────────────────────────────────────────────
# State helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"open_positions": {}, "pending_orders": {}, "closed_positions": [], "total_pnl": 0.0}


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# VIX Filter
# ─────────────────────────────────────────────────────────────────────────────

def get_india_vix() -> float:
    try:
        quote = get_kite().quote("NSE:INDIA VIX")
        return float(quote.get("NSE:INDIA VIX", {}).get("last_price", 0))
    except Exception as e:
        logger.warning(f"VIX fetch failed: {e}")
        return 0.0


def get_vix_position_multiplier(vix: float) -> float:
    if vix <= 0:  return 1.0
    if vix < 20:  return 1.0
    if vix < 25:  return 0.5
    if vix < 30:  return 0.25
    return 0.0


def check_vix_before_scan() -> tuple:
    """Returns (can_trade: bool, capital_multiplier: float, vix: float)."""
    vix  = get_india_vix()
    mult = get_vix_position_multiplier(vix)
    if vix > 0:
        logger.info(f"India VIX: {vix:.1f} → multiplier: {mult:.0%}")
    if mult == 0.0:
        msg = f"India VIX={vix:.1f} ≥ {VIX_HALT_THRESHOLD}. No new entries today."
        logger.warning(msg)
        _send(f"⚠️ <b>VIX HALT</b>\n{msg}")
        return False, 0.0, vix
    if mult < 1.0:
        _send(
            f"📊 <b>VIX CAUTION</b> — India VIX={vix:.1f}\n"
            f"Position sizes reduced to {mult*100:.0f}% of normal."
        )
    return True, mult, vix


# ─────────────────────────────────────────────────────────────────────────────
# Time-Based & Sideways Exit
# ─────────────────────────────────────────────────────────────────────────────

def check_time_based_exits(state: dict, changes: dict):
    """
    Exit positions that are sideways or held too long.
    Sideways = price within 0.5% of entry after 8+ days.
    Time limit = held 15+ days regardless of price.
    """
    positions = state.get("open_positions", {})
    if not positions:
        return
    try:
        ltps = get_ltp(list(positions.keys()))
    except Exception as e:
        logger.error(f"Time exit LTP failed: {e}")
        return

    to_exit = []
    for symbol, pos in positions.items():
        raw_date = pos.get("date")
        if not raw_date:
            continue
        try:
            days_held = (pd.Timestamp(datetime.now()) - pd.Timestamp(raw_date)).days
        except Exception:
            continue

        entry = float(pos.get("entry", 0))
        ltp   = ltps.get(symbol, entry)
        if entry <= 0:
            continue

        pct_move = abs(ltp - entry) / entry

        if days_held >= SIDEWAYS_DAYS and pct_move < SIDEWAYS_PCT:
            to_exit.append((symbol, "SIDEWAYS_EXIT", ltp, days_held))
        elif days_held >= MAX_HOLD_DAYS:
            to_exit.append((symbol, "TIME_EXIT", ltp, days_held))

    for symbol, reason, ltp, days_held in to_exit:
        pos = positions.get(symbol, {})
        qty = int(pos.get("quantity", 0))
        if qty < 1:
            continue

        place_order(symbol, "SELL", qty, order_type="MARKET")
        pnl = (ltp - pos["entry"]) * qty if pos.get("signal") == "BUY" \
              else (pos["entry"] - ltp) * qty

        label  = "⏳ SIDEWAYS EXIT" if reason == "SIDEWAYS_EXIT" else "⏱ TIME LIMIT EXIT"
        detail = (f"Stock moved only {pct_move*100:.2f}% in {days_held} days — no momentum."
                  if reason == "SIDEWAYS_EXIT"
                  else f"Max hold of {MAX_HOLD_DAYS} days reached.")

        _send(
            f"{label}\n"
            f"Stock: <b>{symbol}</b>\n"
            f"Entry ₹{pos['entry']:.2f} → LTP ₹{ltp:.2f} | {days_held} days\n"
            f"P&L: <b>₹{pnl:+,.0f}</b>\n"
            f"{detail}\nCapital freed for better trades."
        )
        state.setdefault("closed_positions", []).append({
            **pos, "symbol": symbol, "exit_type": reason,
            "exit_price": ltp, "exit_date": datetime.now().isoformat(),
            "realised_pnl": round(pnl, 2),
        })
        state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 2)
        del state["open_positions"][symbol]
        audit_log(reason, {"symbol": symbol, "days": days_held, "pnl": pnl})
        changes["detected"].append(f"{symbol} {reason} after {days_held}d")
        logger.info(f"{reason}: {symbol}, days={days_held}, pnl=₹{pnl:+.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# Partial Profit Booking
# ─────────────────────────────────────────────────────────────────────────────

def check_partial_exits(state: dict):
    """
    At T1 (original target): sell 50%, move SL to breakeven, set T2.
    T2 = T1 + 1.5× original risk. GTT updated automatically.
    """
    if not ENABLE_PARTIAL_EXIT:
        return
    positions = state.get("open_positions", {})
    if not positions:
        return
    try:
        ltps = get_ltp(list(positions.keys()))
    except Exception as e:
        logger.error(f"Partial exit LTP failed: {e}")
        return

    for symbol, pos in list(positions.items()):
        if pos.get("partial_booked"):
            continue
        ltp    = ltps.get(symbol, 0)
        entry  = float(pos.get("entry", 0))
        target = float(pos.get("target", 0))
        sl     = float(pos.get("stop_loss", 0))
        qty    = int(pos.get("quantity", 0))
        signal = pos.get("signal", "BUY")

        if ltp <= 0 or entry <= 0 or target <= 0 or qty < 2:
            continue

        t1_hit = (signal == "BUY" and ltp >= target) or (signal == "SELL" and ltp <= target)
        if not t1_hit:
            continue

        sell_qty   = max(1, int(qty * PARTIAL_BOOK_PCT))
        remain_qty = qty - sell_qty
        profit     = (ltp - entry) * sell_qty if signal == "BUY" else (entry - ltp) * sell_qty
        orig_risk  = abs(entry - sl)

        order_id = place_order(symbol, "SELL", sell_qty, price=ltp, order_type="LIMIT")
        if not order_id:
            logger.error(f"Partial sell order failed: {symbol}")
            continue

        new_sl  = round(entry, 2)
        new_tgt = round(target + orig_risk * PARTIAL_TARGET_MULT, 2) if signal == "BUY" \
                  else round(target - orig_risk * PARTIAL_TARGET_MULT, 2)

        state["open_positions"][symbol].update({
            "quantity": remain_qty, "stop_loss": new_sl,
            "target": new_tgt, "partial_booked": True,
            "partial_date": datetime.now().isoformat(),
        })

        # Update GTT
        try:
            from core.kite_client import place_gtt_oco
            kite    = get_kite()
            old_gtt = pos.get("gtt_id")
            if old_gtt:
                try:
                    kite.delete_gtt(int(old_gtt))
                except Exception:
                    pass
            new_gtt = place_gtt_oco(symbol, remain_qty, ltp, new_sl, new_tgt)
            state["open_positions"][symbol]["gtt_id"] = new_gtt
        except Exception as e:
            logger.warning(f"GTT update failed partial {symbol}: {e}")

        _send(
            f"💰 <b>PARTIAL PROFIT BOOKED</b>\n"
            f"Stock: <b>{symbol}</b>\n"
            f"Sold {sell_qty} shares @ ₹{ltp:.2f}\n"
            f"Profit locked: <b>₹{profit:+,.0f}</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"Remaining: {remain_qty} shares\n"
            f"SL moved to breakeven: ₹{new_sl:.2f}\n"
            f"New target (T2): ₹{new_tgt:.2f}"
        )
        audit_log("PARTIAL_EXIT", {"symbol": symbol, "qty_sold": sell_qty, "profit": profit})
        save_state(state)


# ─────────────────────────────────────────────────────────────────────────────
# Main Sync
# ─────────────────────────────────────────────────────────────────────────────

def sync_positions() -> dict:
    state   = load_state()
    changes = {"detected": [], "resolved": []}
    try:
        _sync_open_positions(state, changes)
        _sync_pending_orders(state, changes)
        _sync_gtt_triggers(state, changes)
        check_time_based_exits(state, changes)
        check_partial_exits(state)
        state["last_sync"] = datetime.now().isoformat()
        save_state(state)
    except Exception as e:
        logger.error(f"Sync error: {e}")
        notify_error("Sync Engine", str(e))
    if changes["detected"]:
        logger.warning(f"Sync changes: {changes['detected']}")
    return changes


def _sync_open_positions(state, changes):
    system_positions = state.get("open_positions", {})
    if not system_positions:
        return
    holdings_df  = get_holdings()
    kite_symbols = set()
    if not holdings_df.empty and "tradingsymbol" in holdings_df.columns:
        kite_symbols = set(holdings_df[holdings_df["quantity"] > 0]["tradingsymbol"].tolist())
    pos_df = get_positions()
    if not pos_df.empty and "tradingsymbol" in pos_df.columns:
        kite_symbols.update(pos_df[pos_df["quantity"] != 0]["tradingsymbol"].tolist())

    for symbol, pos_data in list(system_positions.items()):
        if symbol not in kite_symbols:
            exit_type = _determine_exit_type(symbol, pos_data, holdings_df)
            pnl       = _calculate_realised_pnl(symbol, pos_data, holdings_df)
            state.setdefault("closed_positions", []).append({
                **pos_data, "symbol": symbol, "exit_type": exit_type,
                "exit_date": datetime.now().isoformat(), "realised_pnl": round(pnl, 2),
            })
            state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 2)
            del state["open_positions"][symbol]
            _notify_position_closed(symbol, pos_data, exit_type, pnl)
            audit_log("POSITION_SYNC_CLOSED", {"symbol": symbol, "exit_type": exit_type, "pnl": pnl})
            changes["detected"].append(f"{symbol} closed ({exit_type})")
            changes["resolved"].append(symbol)

    if not holdings_df.empty and "tradingsymbol" in holdings_df.columns:
        for _, row in holdings_df[holdings_df["quantity"] > 0].iterrows():
            sym = row["tradingsymbol"]
            if sym not in system_positions:
                _handle_manual_buy(state, row)
                changes["detected"].append(f"{sym} manually bought")


def _sync_pending_orders(state, changes):
    try:
        orders = get_kite().orders()
    except Exception as e:
        logger.error(f"Fetch orders failed: {e}")
        return
    kite_order_status = {str(o["order_id"]): o for o in orders}
    pending   = state.get("pending_orders", {})
    to_remove = []
    for symbol, order_data in pending.items():
        order_id   = str(order_data.get("order_id", ""))
        order_info = kite_order_status.get(order_id, {})
        status     = order_info.get("status", "")
        if status == "CANCELLED":
            _send(f"⚠️ <b>ORDER CANCELLED</b>\n{symbol} order {order_id} cancelled.\nSystem updated.")
            to_remove.append(symbol)
            changes["detected"].append(f"{symbol} order cancelled")
        elif status == "COMPLETE":
            avg_price = order_info.get("average_price", order_data.get("price", 0))
            state["open_positions"][symbol] = {**order_data, "entry": avg_price, "status": "OPEN"}
            to_remove.append(symbol)
            changes["resolved"].append(f"{symbol} filled @ ₹{avg_price}")
    for sym in to_remove:
        pending.pop(sym, None)


def _sync_gtt_triggers(state, changes):
    try:
        gtts = get_kite().get_gtts()
    except Exception as e:
        logger.error(f"GTT fetch failed: {e}")
        return
    gtt_status = {str(g["id"]): g["status"] for g in gtts}
    for symbol, pos_data in list(state.get("open_positions", {}).items()):
        gtt_id = str(pos_data.get("gtt_id", ""))
        if not gtt_id or gtt_status.get(gtt_id) != "triggered":
            continue
        ltps      = get_ltp([symbol])
        ltp       = ltps.get(symbol, pos_data["entry"])
        signal    = pos_data.get("signal", "BUY")
        sl        = pos_data.get("stop_loss", 0)
        target    = pos_data.get("target", 0)
        hit_sl    = (signal == "BUY" and ltp <= sl * 1.01) or (signal == "SELL" and ltp >= sl * 0.99)
        exit_price = sl if hit_sl else target
        exit_type  = "STOP_LOSS" if hit_sl else "TARGET_HIT"
        qty        = pos_data.get("quantity", 0)
        pnl        = (exit_price - pos_data["entry"]) * qty if signal == "BUY" \
                     else (pos_data["entry"] - exit_price) * qty
        state.setdefault("closed_positions", []).append({
            **pos_data, "symbol": symbol, "exit_type": exit_type,
            "exit_price": exit_price, "exit_date": datetime.now().isoformat(),
            "realised_pnl": round(pnl, 2),
        })
        state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 2)
        del state["open_positions"][symbol]
        _send(f"{'🏆' if pnl > 0 else '📉'} <b>GTT {exit_type}</b>\n{symbol}\nP&L: ₹{pnl:+,.0f}")
        changes["detected"].append(f"{symbol} GTT {exit_type}")
        audit_log("GTT_TRIGGERED", {"symbol": symbol, "exit_type": exit_type, "pnl": pnl})


def _determine_exit_type(symbol, pos_data, holdings_df):
    try:
        trades = get_kite().trades()
        sells  = [t for t in trades if t["tradingsymbol"] == symbol and t["transaction_type"] == "SELL"]
        if sells:
            sp = sorted(sells, key=lambda x: x["fill_timestamp"], reverse=True)[0]["average_price"]
            if abs(sp - pos_data.get("stop_loss", 0)) / max(pos_data.get("stop_loss", 1), 1) < 0.02:
                return "STOP_LOSS_HIT"
            if abs(sp - pos_data.get("target", 0)) / max(pos_data.get("target", 1), 1) < 0.02:
                return "TARGET_HIT"
            return "MANUAL_SELL"
    except Exception:
        pass
    return "UNKNOWN_EXIT"


def _calculate_realised_pnl(symbol, pos_data, holdings_df):
    try:
        trades = get_kite().trades()
        sells  = [t for t in trades if t["tradingsymbol"] == symbol and t["transaction_type"] == "SELL"]
        if sells:
            sp  = sells[-1]["average_price"]
            qty = pos_data.get("quantity", 0)
            e   = pos_data.get("entry", 0)
            return (sp - e) * qty if pos_data.get("signal") == "BUY" else (e - sp) * qty
    except Exception:
        pass
    return 0.0


def _handle_manual_buy(state, holding_row):
    symbol = holding_row["tradingsymbol"]
    qty    = holding_row.get("quantity", 0)
    entry  = holding_row.get("average_price", 0)
    state["open_positions"][symbol] = {
        "signal": "BUY", "entry": entry, "quantity": qty,
        "stop_loss": round(entry * 0.95, 2), "target": round(entry * 1.10, 2),
        "strategy": "MANUAL", "date": datetime.now().isoformat(),
        "order_id": "MANUAL", "gtt_id": None,
    }
    _send(f"📌 <b>MANUAL BUY DETECTED</b>\n<b>{symbol}</b> {qty}sh @ ₹{entry:.2f}\nTracking added. Default SL: ₹{entry*0.95:.2f}")
    audit_log("MANUAL_POSITION_DETECTED", {"symbol": symbol, "entry": entry})


def _notify_position_closed(symbol, pos_data, exit_type, pnl):
    labels = {"STOP_LOSS_HIT": "🛑 SL Hit", "TARGET_HIT": "🎯 Target", "MANUAL_SELL": "✋ Manual Sell", "UNKNOWN_EXIT": "❓ Closed"}
    _send(
        f"{'🏆' if pnl > 0 else '📉'} <b>POSITION CLOSED — {labels.get(exit_type, exit_type)}</b>\n"
        f"<b>{symbol}</b> | Entry ₹{pos_data.get('entry', 0):.2f} | Qty {pos_data.get('quantity', 0)}\n"
        f"P&L: <b>₹{pnl:+,.0f}</b> ✅"
    )


def get_sync_status() -> dict:
    state = load_state()
    return {
        "open_positions":   len(state.get("open_positions", {})),
        "pending_orders":   len(state.get("pending_orders", {})),
        "closed_positions": len(state.get("closed_positions", [])),
        "total_pnl":        state.get("total_pnl", 0),
        "last_sync":        state.get("last_sync", "Never"),
    }
