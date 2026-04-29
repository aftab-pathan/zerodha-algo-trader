"""
manage.py
CLI tool to manage the trading system without restarting the scheduler.
Usage: python manage.py <command> [options]
"""

import sys
import json
import argparse
import logging
from config.config import TRADING_CAPITAL

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


def cmd_status(args):
    """Show current system status."""
    from core.kite_client import is_authenticated, get_portfolio_value, get_holdings
    from core.risk_manager import get_capital_summary
    from core.trading_engine import _load_state
    from utils.security import sanitize_env

    auth = is_authenticated()
    state = _load_state()
    cap_summary = get_capital_summary()

    print("\n" + "═"*55)
    print("  ALGO TRADER STATUS")
    print("═"*55)
    print(f"  Kite Connected : {'✅ Yes' if auth else '❌ No — run login.py'}")
    print(f"  Open Positions : {len(state.get('open_positions', {}))}")
    print(f"\n  CAPITAL SETTINGS")
    print(f"  Total Capital  : ₹{cap_summary['total_capital']:,.0f}")
    print(f"  Max Deployable : ₹{cap_summary['max_deployable']:,.0f}")
    print(f"  Risk/Trade     : ₹{cap_summary['max_risk_per_trade_inr']:,.0f} ({cap_summary['max_risk_per_trade_pct']})")
    print(f"  Capital/Slot   : ₹{cap_summary['capital_per_slot']:,.0f}")
    print(f"  Max Positions  : {cap_summary['max_open_positions']}")
    print(f"\n  CONFIG")
    env = sanitize_env()
    for k, v in env.items():
        print(f"  {k:22s}: {v}")
    print("═"*55 + "\n")


def cmd_capital(args):
    """Update trading capital."""
    from core.trading_engine import update_capital
    new = args.amount
    summary = update_capital(new)
    print(f"\n✅ Capital updated to ₹{new:,.0f}")
    print(json.dumps(summary, indent=2))


def cmd_scan(args):
    """Run a manual scan (dry_run or live)."""
    from core.trading_engine import scan_and_trade
    from config.config import DEFAULT_WATCHLIST, BULK_SCAN_SIZE
    
    dry = not args.live
    use_bulk = args.bulk if hasattr(args, 'bulk') else False
    size = args.size if hasattr(args, 'size') and args.size else None
    
    if use_bulk:
        target_size = size or BULK_SCAN_SIZE
        print(f"\n{'[DRY RUN] ' if dry else ''}🔍 BULK SCAN MODE: Targeting top {target_size} NSE stocks...\n")
    else:
        print(f"\n{'[DRY RUN] ' if dry else ''}Running scan on {len(DEFAULT_WATCHLIST)} stocks…\n")
    
    result = scan_and_trade(dry_run=dry, use_bulk_scan=use_bulk, bulk_size=size)
    
    # Enhanced summary for bulk scans
    if use_bulk and result.get('bulk_scan'):
        print(f"\n📊 Bulk Scan Summary:")
        print(f"   Universe size: {result.get('universe_size', 0)} stocks")
        print(f"   Scanned: {result.get('scanned', 0)}")
        print(f"   Signals found: {result.get('signals', 0)}")
        
        # Two-tier mode stats
        if result.get('two_tier'):
            print(f"   🎯 Two-Tier Mode: Claude analyzed {result.get('claude_analyzed', 0)} top stocks")
            print(f"   💰 Estimated cost: ~${result.get('claude_analyzed', 0) * 0.02:.2f} (vs ${result.get('signals', 0) * 0.02:.2f} for all)")
        
        print(f"   Orders placed: {result.get('orders_placed', 0)}")
        if result.get('shortlisted'):
            print(f"   Shortlisted: {', '.join(result['shortlisted'][:10])}{' ...' if len(result['shortlisted']) > 10 else ''}")
        if result.get('errors'):
            print(f"   Errors: {len(result['errors'])}")
        print()
    
    print(json.dumps(result, indent=2))


def cmd_positions(args):
    """Show all open positions."""
    from core.trading_engine import _load_state
    from core.kite_client import get_holdings, get_ltp
    state = _load_state()
    pos = state.get("open_positions", {})

    if not pos:
        print("\nNo open positions tracked.\n")
        return

    symbols = list(pos.keys())
    ltps = get_ltp(symbols)

    print(f"\n{'Symbol':<12} {'Signal':<6} {'Entry':>8} {'LTP':>8} {'SL':>8} {'Target':>8} {'Qty':>5} {'Unrealized':>12}")
    print("─"*75)
    for sym, p in pos.items():
        ltp = ltps.get(sym, 0)
        if p["signal"] == "BUY":
            unr = (ltp - p["entry"]) * p["quantity"]
        else:
            unr = (p["entry"] - ltp) * p["quantity"]
        print(f"{sym:<12} {p['signal']:<6} {p['entry']:>8.2f} {ltp:>8.2f} "
              f"{p['stop_loss']:>8.2f} {p['target']:>8.2f} {p['quantity']:>5} "
              f"₹{unr:>+10,.0f}")
    print()


def cmd_watchlist(args):
    """Show or refresh Zerodha watchlist."""
    from core.kite_client import get_watchlists, add_to_watchlist
    from config.config import DEFAULT_WATCHLIST
    
    print("\n⚠️  IMPORTANT: Kite Connect API v5+ does not support watchlist management\n")
    print("Zerodha removed this feature from the API for security reasons.")
    print("You must manually update watchlists through Kite web/app.\n")
    
    if args.test:
        print("📋 To manually add stocks to your watchlist:")
        print("   1. Go to https://kite.zerodha.com")
        print("   2. Create/open watchlist 'AlgoTrader Picks'")
        print("   3. After each scan, check Telegram or logs for shortlisted stocks")
        print("   4. Add them manually to your watchlist\n")
        print("💡 The algo will still find signals and place orders automatically,")
        print("   but watchlist sync must be done manually.\n")
        
    elif args.refresh:
        print(f"📝 Stocks to add manually: {DEFAULT_WATCHLIST}\n")
        print("   Copy these symbols and add them to your Kite watchlist manually.\n")
    else:
        print("Available commands:")
        print("  python manage.py watchlist --test     # Show manual instructions")
        print("  python manage.py watchlist --refresh  # Show default watchlist stocks\n")


def cmd_summary():
    """Send daily summary to Telegram."""
    from core.trading_engine import send_daily_summary
    stats = send_daily_summary()
    print(f"\nSummary sent: {json.dumps(stats, indent=2)}\n")


def main():
    parser = argparse.ArgumentParser(description="Algo Trader Management CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show system status")

    p_cap = sub.add_parser("capital", help="Update trading capital")
    p_cap.add_argument("amount", type=float, help="New capital in INR (e.g. 25000)")

    p_scan = sub.add_parser("scan", help="Run a manual scan")
    p_scan.add_argument("--live", action="store_true",
                        help="Place real orders (default: dry run)")
    p_scan.add_argument("--bulk", action="store_true",
                        help="Enable bulk scan mode (scan top 1000 NSE stocks with 2-stage filtering)")
    p_scan.add_argument("--size", type=int, metavar="N",
                        help="Universe size for bulk scan (default: from config.BULK_SCAN_SIZE)")

    sub.add_parser("positions", help="Show open positions with LTP")

    p_wl = sub.add_parser("watchlist", help="Manage Zerodha watchlist")
    p_wl.add_argument("--refresh", action="store_true",
                      help="Clear and re-add default watchlist")
    p_wl.add_argument("--test", action="store_true",
                      help="Test watchlist setup and functionality")

    sub.add_parser("summary", help="Send daily summary to Telegram")

    args = parser.parse_args()

    commands = {
        "status":    cmd_status,
        "capital":   cmd_capital,
        "scan":      cmd_scan,
        "positions": cmd_positions,
        "watchlist": cmd_watchlist,
        "summary":   lambda _: cmd_summary(),
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
