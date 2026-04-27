"""
login.py
Daily login flow for Zerodha Kite Connect.
Run this once each morning before market opens OR automate with Playwright.
"""

import sys
import logging
from config.config import KITE_API_KEY, validate_config
from core.kite_client import get_kite, complete_login

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def manual_login():
    """Interactive login: user pastes request_token from browser redirect."""
    validate_config()
    kite = get_kite()
    login_url = kite.login_url()

    print("\n" + "═"*60)
    print("  ZERODHA KITE LOGIN")
    print("═"*60)
    print(f"\n1. Open this URL in your browser:\n\n   {login_url}\n")
    print("2. Login with your Zerodha credentials + 2FA PIN")
    print("3. After redirect, copy the 'request_token' from the URL bar")
    print("   Example: https://yourapp.com/?request_token=abc123xyz&action=login&status=success")
    print("            ↑ Copy: abc123xyz\n")

    request_token = input("Paste request_token here: ").strip()
    if not request_token:
        print("ERROR: No token provided.")
        sys.exit(1)

    access_token = complete_login(request_token)
    print(f"\n✅ Login successful! Access token saved (encrypted).")
    print("   The scheduler will use this token for today's trading.")
    return access_token


def automated_login_guide():
    """
    Print instructions for fully automated daily login using Playwright.
    For production use on Oracle Cloud.
    """
    print("""
═══════════════════════════════════════════════════════════
  AUTOMATED LOGIN SETUP (Production / Oracle Cloud)
═══════════════════════════════════════════════════════════

To avoid daily manual login, set up Playwright automation:

  pip install playwright
  playwright install chromium

Then create automated_login.py:

  from playwright.sync_api import sync_playwright
  import re, os

  def auto_login():
      with sync_playwright() as p:
          browser = p.chromium.launch(headless=True)
          page = browser.new_page()
          page.goto(f"https://kite.trade/connect/login?api_key={os.getenv('KITE_API_KEY')}&v=3")
          page.fill("#userid", os.getenv("ZERODHA_USER_ID"))
          page.fill("#password", os.getenv("ZERODHA_PASSWORD"))
          page.click("button[type=submit]")
          page.wait_for_selector(".tpin-input")
          page.fill(".tpin-input", os.getenv("ZERODHA_TOTP"))  # TOTP/PIN
          page.click("button[type=submit]")
          page.wait_for_url("*request_token*")
          token = re.search(r"request_token=([^&]+)", page.url).group(1)
          browser.close()
          from core.kite_client import complete_login
          complete_login(token)

  ⚠️  Store ZERODHA_USER_ID, ZERODHA_PASSWORD, ZERODHA_TOTP in .env
  ⚠️  Use TOTP (time-based OTP) from your authenticator app
  ⚠️  Schedule this in cron at 08:30 AM IST daily
""")


if __name__ == "__main__":
    if "--guide" in sys.argv:
        automated_login_guide()
    else:
        manual_login()
