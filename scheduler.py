"""
scheduler.py
Runs all jobs on schedule (IST). Handles daily token refresh,
market open scan, EOD scan, and daily P&L summary.
Uses APScheduler for reliable job scheduling.
"""

import logging
import os
import sys
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from config.config import (
    SCAN_TIME_MORNING, SCAN_TIME_EOD, TOKEN_REFRESH_TIME,
    DEFAULT_WATCHLIST, validate_config
)
from core.trading_engine import scan_and_trade, send_daily_summary
from utils.telegram_notifier import notify_startup, notify_error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/scheduler.log"),
    ]
)
logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
scheduler = BlockingScheduler(timezone=IST)


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────

def job_morning_scan():
    """Morning scan just after market open — find fresh breakouts."""
    logger.info("━━━ MORNING SCAN STARTING ━━━")
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    result = scan_and_trade(watchlist=DEFAULT_WATCHLIST, dry_run=dry_run)
    logger.info(f"Morning scan result: {result}")


def job_eod_scan():
    """EOD scan — catch late-day setups, pre-place GTT orders."""
    logger.info("━━━ EOD SCAN STARTING ━━━")
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    result = scan_and_trade(watchlist=DEFAULT_WATCHLIST, dry_run=dry_run)
    logger.info(f"EOD scan result: {result}")


def job_daily_summary():
    """Send daily P&L + portfolio summary on Telegram at 3:45 PM."""
    logger.info("━━━ SENDING DAILY SUMMARY ━━━")
    send_daily_summary()


def job_token_refresh_reminder():
    """
    Remind user to refresh access token (Kite tokens expire daily).
    In production, use a headless Selenium login or Playwright to automate this.
    """
    msg = (
        "⏰ <b>TOKEN REFRESH NEEDED</b>\n"
        "Kite access token expires daily.\n"
        "Run: <code>python login.py</code> or check automated login setup.\n"
        f"🕐 {datetime.now(IST).strftime('%H:%M IST')}"
    )
    from utils.telegram_notifier import _send
    _send(msg)
    logger.info("Token refresh reminder sent.")


def job_health_check():
    """Ping Kite and log a heartbeat every hour."""
    from core.kite_client import is_authenticated
    status = "✅ Connected" if is_authenticated() else "❌ Disconnected"
    logger.info(f"Health check: Kite = {status}")


# ─────────────────────────────────────────────────────────────────────────────
# Error handler
# ─────────────────────────────────────────────────────────────────────────────

def on_job_error(event):
    exc = event.exception
    logger.error(f"Job {event.job_id} failed: {exc}")
    notify_error(f"Scheduler/{event.job_id}", str(exc)[:300])


def on_job_done(event):
    logger.info(f"Job {event.job_id} executed successfully.")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def start():
    logger.info("Validating config…")
    validate_config()

    scheduler.add_listener(on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(on_job_done,  EVENT_JOB_EXECUTED)

    # Token refresh reminder — weekdays 8:30 AM IST
    h_r, m_r = map(int, TOKEN_REFRESH_TIME.split(":"))
    scheduler.add_job(job_token_refresh_reminder, "cron",
                      day_of_week="mon-fri", hour=h_r, minute=m_r,
                      id="token_refresh", misfire_grace_time=300)

    # Morning scan — weekdays 9:20 AM IST (post open auction)
    h_m, m_m = map(int, SCAN_TIME_MORNING.split(":"))
    scheduler.add_job(job_morning_scan, "cron",
                      day_of_week="mon-fri", hour=h_m, minute=m_m,
                      id="morning_scan", misfire_grace_time=300)

    # EOD scan — weekdays 3:10 PM IST
    h_e, m_e = map(int, SCAN_TIME_EOD.split(":"))
    scheduler.add_job(job_eod_scan, "cron",
                      day_of_week="mon-fri", hour=h_e, minute=m_e,
                      id="eod_scan", misfire_grace_time=300)

    # Daily summary — weekdays 3:45 PM IST
    scheduler.add_job(job_daily_summary, "cron",
                      day_of_week="mon-fri", hour=15, minute=45,
                      id="daily_summary", misfire_grace_time=300)

    # Hourly health check
    scheduler.add_job(job_health_check, "interval", hours=1,
                      id="health_check")

    notify_startup()
    logger.info("Scheduler started. Press Ctrl+C to stop.")
    logger.info(f"Jobs: morning={SCAN_TIME_MORNING}, eod={SCAN_TIME_EOD} IST (Mon-Fri)")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    start()


# ── Position Sync (added in v2) ───────────────────────────────────────────────
def job_position_sync():
    """Sync system state with Kite every 5 minutes during market hours."""
    from core.sync_engine import sync_positions
    changes = sync_positions()
    if changes.get("detected"):
        logger.info(f"Sync changes: {changes}")
