# Production Setup Checklist

This guide covers the setup steps needed before running the algo trader in production (live trading).

---

## ✅ **Pre-Deployment Checklist**

### **1. Zerodha Kite Connect Setup**

#### **A. Create Kite Connect App**

1. Go to https://developers.kite.trade
2. Create a new app or use existing one
3. Note down your `API Key` and `API Secret`

#### **B. Configure IP Whitelist (REQUIRED for live trading)**

1. Go to https://developers.kite.trade
2. Select your app
3. Under "Settings" → "IP Addresses"
4. Add your server/home IP address
5. **Without this**: You'll get `No IPs configured for this app` error

**How to find your IP:**

```bash
curl ifconfig.me
# Or
curl api.ipify.org
```

#### **C. Daily Login (Required)**

Run this once per day (access token expires daily):

```bash
python login.py
```

---

### **2. Create Zerodha Watchlist (REQUIRED)**

The algo trader updates a Zerodha watchlist called **"AlgoTrader Picks"** with daily signals.

**Setup:**

1. Open Kite app or web (https://kite.zerodha.com)
2. Go to Watchlists
3. Create a new watchlist named: **AlgoTrader Picks** (exact name)
4. Leave it empty - the algo will populate it

**Why needed:** Kite API doesn't support programmatic watchlist creation, only adding/removing items.

---

### **3. Environment Variables (.env)**

Copy `.env.example` to `.env` and fill in:

#### **Required for Basic Operation:**

```bash
KITE_API_KEY=your_key_here
KITE_API_SECRET=your_secret_here
TELEGRAM_BOT_TOKEN=your_bot_token  # For notifications
TELEGRAM_CHAT_ID=your_chat_id
```

#### **Optional (for Claude AI strategy):**

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Without Claude API key:**

- Standard scans will skip Claude strategy (4 technical strategies only)
- Bulk scans with two-tier mode will skip Claude confirmation (technical signals only)
- **This is fine** - you can run without Claude if you don't want AI analysis

---

### **4. Trading Capital Configuration**

Set your initial capital in `.env`:

```bash
TRADING_CAPITAL=50000  # ₹50,000 for example
```

Update anytime using:

```bash
python manage.py capital 75000  # Update to ₹75,000
```

---

### **5. Risk Management Settings**

**Recommended defaults (already in `.env.example`):**

```bash
MAX_RISK_PER_TRADE=0.02     # Risk 2% per trade
MAX_OPEN_POSITIONS=5        # Max 5 concurrent positions
MAX_CAPITAL_DEPLOY=0.80     # Deploy max 80% of capital
MIN_CONFIDENCE=7.0          # Minimum strategy confidence
MIN_RISK_REWARD=2.0         # Minimum 1:2 R:R
```

**For conservative trading:**

```bash
MAX_RISK_PER_TRADE=0.01     # 1% per trade
MAX_OPEN_POSITIONS=3        # Max 3 positions
MIN_CONFIDENCE=8.0          # Higher confidence threshold
```

---

### **6. Bulk Scanning Configuration**

**For 1000-stock scanning with two-tier Claude optimization:**

```bash
ENABLE_BULK_SCAN=true              # Enable bulk mode
ENABLE_TWO_TIER_CLAUDE=true        # Cost optimization (recommended)
MAX_CLAUDE_STOCKS=20               # Only top 20 get Claude analysis
BULK_SCAN_STRATEGIES=ema_crossover,rsi_reversal,macd_momentum,breakout,52w_breakout
```

**Cost comparison:**

- Without two-tier: ~$2-3 per scan (Claude on all 150-200 stocks)
- With two-tier: ~$0.20-0.40 per scan (Claude on top 20 only)
- **Savings: ~90%**

---

## 🚀 **Production Commands**

### **Daily Workflow:**

#### **Morning (09:15 AM IST):**

```bash
# 1. Login to Kite (daily)
python login.py

# 2. Check system status
python manage.py status

# 3. Run morning scan (9:20 AM)
python manage.py scan --bulk --live  # Live orders
# OR
python manage.py scan --live  # Standard 15-stock scan
```

#### **End of Day (15:10 PM IST):**

```bash
# Run EOD scan
python manage.py scan --bulk --live

# Check positions
python manage.py positions

# Send daily summary
python manage.py summary
```

---

## 🧪 **Testing Before Going Live**

### **1. Dry Run Testing**

Always test with dry run first:

```bash
# Test standard scan
python manage.py scan --dry-run

# Test bulk scan with two-tier Claude
python manage.py scan --bulk --dry-run

# Expected output:
# ✅ Signals generated
# ✅ Risk calculations shown
# ✅ [DRY RUN] messages for orders
# ❌ No real orders placed
```

### **2. Small Capital Test**

Start with minimal capital:

```bash
python manage.py capital 10000  # ₹10,000 test run
python manage.py scan --live    # Small position sizes
```

Monitor for 1-2 weeks, then scale up.

### **3. Check Logs**

```bash
tail -f logs/app.log           # Main log
tail -f logs/trades.csv        # Trade history
```

---

## ⚠️ **Common Errors & Solutions**

### **Error: "No IPs configured"**

**Solution:** Add your IP to Kite Connect app settings (see Step 1B above)

### **Error: "invalid x-api-key" (Anthropic)**

**Solution:**

- Add valid Claude API key to `.env`
- OR disable Claude by removing `claude_ai` from `ACTIVE_STRATEGIES`
- With two-tier mode, bulk scans work fine without Claude (technical only)

### **Error: "Watchlist 'AlgoTrader Picks' not found"**

**Solution:** Create the watchlist manually in Kite app (see Step 2 above)

### **Error: "Kite not authenticated"**

**Solution:** Run `python login.py` - token expires daily

### **Error: "Insufficient data for [SYMBOL]"**

**Solution:** Normal - some stocks have < 500 days of data. Scanner skips them.

---

## 📊 **Monitoring & Maintenance**

### **Daily Monitoring:**

1. Check Telegram notifications for signals/orders
2. Review positions: `python manage.py positions`
3. Monitor open orders in Kite app
4. Check `logs/trades.csv` for trade log

### **Weekly Review:**

1. Analyze win rate and P&L
2. Review rejected signals (low confidence, bad R:R)
3. Adjust `MIN_CONFIDENCE` or `MIN_RISK_REWARD` if needed

### **Monthly Maintenance:**

1. Update trading capital: `python manage.py capital <new_amount>`
2. Review strategy performance
3. Check for Kite API updates
4. Clear old log files: `find logs/ -mtime +30 -delete`

---

## 🔒 **Security Best Practices**

1. **Never commit `.env`** - Contains API keys
2. **Rotate API keys quarterly** - In Kite developer console
3. **Use strong password** for dashboard: `DASHBOARD_PASSWORD_HASH`
4. **Restrict server access** - Firewall, SSH keys only
5. **Enable 2FA** on Zerodha account
6. **Monitor access logs** - Check `logs/audit.log`

---

## 📞 **Support Resources**

- **Zerodha Kite API Docs:** https://kite.trade/docs/connect/v3/
- **KiteConnect Python:** https://github.com/zerodhatech/pykiteconnect
- **Anthropic Claude API:** https://docs.anthropic.com/claude/reference
- **Telegram Bot Setup:** https://core.telegram.org/bots#3-how-do-i-create-a-bot

---

## 🎯 **Production Readiness Summary**

| Component             | Status | Action Required                   |
| --------------------- | ------ | --------------------------------- |
| Kite API Keys         | ⚠️     | Add to `.env`                     |
| IP Whitelist          | ⚠️     | Configure in Kite Console         |
| Watchlist Creation    | ⚠️     | Create "AlgoTrader Picks" in Kite |
| Telegram Bot          | ⚠️     | Setup and add token to `.env`     |
| Daily Login           | ⚠️     | Run `python login.py` daily       |
| Trading Capital       | ⚠️     | Set in `.env`                     |
| Claude API (Optional) | ℹ️     | Add for AI analysis, or skip      |
| Bulk Scan Setup       | ✅     | Already configured                |
| Two-Tier Claude       | ✅     | Already configured                |
| Risk Management       | ✅     | Defaults are good                 |

**Once all ⚠️ items are complete, you're ready for live trading!**

---

## 🚀 **Quick Start (TL;DR)**

```bash
# 1. Setup
cp .env.example .env
# Edit .env with your keys

# 2. Whitelist IP at https://developers.kite.trade

# 3. Create "AlgoTrader Picks" watchlist in Kite app

# 4. Daily login
python login.py

# 5. Test with dry run
python manage.py scan --bulk --dry-run

# 6. Go live!
python manage.py scan --bulk --live
```

**That's it! Monitor Telegram for signals and check Kite for orders.**
