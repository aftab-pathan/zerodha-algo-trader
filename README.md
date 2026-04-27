# 📈 Zerodha Algo Trader — Powered by Claude AI

A production-grade, multi-strategy swing trading system for NSE/BSE via Zerodha Kite Connect.  
Includes **Claude AI analysis**, **5 trading strategies**, **Telegram notifications**, **auto watchlist**, and **dynamic capital management**.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SCHEDULER (APScheduler)                  │
│          Morning 9:20 AM  │  EOD 3:10 PM  │  Health check   │
└──────────────┬─────────────────────┬───────────────────────-┘
               ↓                     ↓
     ┌──────────────────┐   ┌─────────────────────────────┐
     │  TRADING ENGINE  │   │     MANAGEMENT CLI          │
     │  scan_and_trade  │   │  python manage.py <cmd>     │
     └────────┬─────────┘   └─────────────────────────────┘
              ↓
     ┌────────────────────────────────────────────┐
     │           STRATEGY ENGINE                   │
     │  ┌───────────┐  ┌──────────┐  ┌─────────┐ │
     │  │EMA Cross  │  │RSI Revrs │  │  MACD   │ │
     │  └───────────┘  └──────────┘  └─────────┘ │
     │  ┌───────────┐  ┌──────────────────────┐  │
     │  │ Breakout  │  │   Claude AI (LLM)    │  │
     │  └───────────┘  └──────────────────────┘  │
     └────────────────────┬───────────────────────┘
                          ↓
            ┌─────────────────────────┐
            │     RISK MANAGER        │
            │  Capital × risk% / ATR  │
            │  = Position size (qty)  │
            └────────────┬────────────┘
                         ↓
       ┌─────────────────────────────────────┐
       │         KITE CONNECT API            │
       │  Order → GTT OCO (SL + Target)      │
       │  Watchlist update                   │
       └────────────┬────────────────────────┘
                    ↓
       ┌────────────────────────────────┐
       │      TELEGRAM BOT              │
       │  Signal alerts │ Order fills   │
       │  Daily summary │ Error alerts  │
       └────────────────────────────────┘
```

---

## 🚀 Quick Start

### Step 1 — Get API Keys

| Service | Where | Cost |
|---|---|---|
| Zerodha Kite Connect | [kite.trade](https://kite.trade) | ₹500/month |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com) | Pay-per-use |
| Telegram Bot | Message @BotFather on Telegram | Free |

### Step 2 — Setup

```bash
git clone <your-repo>
cd zerodha-algo-trader

# Create virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
nano .env   # Fill in all values
```

### Step 3 — First Login

```bash
python login.py
# Follow the on-screen instructions to get your Kite access token
```

### Step 4 — Dry Run (Recommended First!)

```bash
# Edit .env: set DRY_RUN=true
python manage.py scan
# Verify you get Telegram notifications without real orders
```

### Step 5 — Go Live

```bash
# Edit .env: set DRY_RUN=false
python manage.py scan --live
# Or start the full scheduler:
python scheduler.py
```

---

## 💰 Capital Management

Change your trading capital at any time without restarting:

```bash
# Start with ₹10,000
python manage.py capital 10000

# Increase to ₹25,000
python manage.py capital 25000

# Or set in .env:
TRADING_CAPITAL=10000
```

**How position sizing works:**
```
Risk Amount   = Capital × MAX_RISK_PER_TRADE (default 2%)
Risk/Share    = Entry Price - Stop Loss
Quantity      = min(Risk Amount / Risk/Share, Slot Capital / Entry Price)
Slot Capital  = (Capital × 0.80) / MAX_OPEN_POSITIONS
```

**Example with ₹10,000 capital:**
```
Risk/trade    = ₹200 (2%)
Capital/slot  = ₹1,600 (8,000 ÷ 5 slots)
If entry=₹500, SL=₹480 → risk/share=₹20
Qty by risk   = 200 ÷ 20 = 10 shares
Qty by capital= 1600 ÷ 500 = 3 shares
Final qty     = min(10, 3) = 3 shares ✅
```

---

## 📊 Strategies

| # | Strategy | Signal Logic | Best For |
|---|---|---|---|
| 1 | **EMA Crossover** | EMA 9/20 cross + EMA50 filter | Trending markets |
| 2 | **RSI Reversal** | RSI < 35 / > 65 + BB touch | Range-bound stocks |
| 3 | **MACD Momentum** | MACD/Signal crossover + histogram | Momentum plays |
| 4 | **Breakout** | 20-day range breakout + volume surge | Post-consolidation |
| 5 | **Claude AI** | Holistic LLM analysis of all indicators | Complex setups |

Enable/disable strategies in `.env`:
```bash
ACTIVE_STRATEGIES=ema_crossover,rsi_reversal,claude_ai
# Remove any you don't want
```

**Consensus Boost:** If 2+ strategies agree → confidence boosted automatically.

---

## 📱 Telegram Notifications

You'll receive:
- 🟢/🔴 **Trade Signal** — Entry, SL, Target, R:R, Confidence
- ✅ **Order Placed** — Order ID confirmation
- 🏆/📉 **Exit Alert** — P&L on close
- 📋 **Watchlist Updated** — Shortlisted stocks added to Zerodha
- 📈 **Daily Summary** — EOD P&L, win rate, portfolio value
- ⚠️ **Error Alerts** — Any system failures

---

## 🛡️ Security

| Feature | Implementation |
|---|---|
| Encrypted token storage | Fernet symmetric encryption |
| No secrets in code | All credentials via `.env` |
| Audit log | Every order/login logged to `logs/audit.log` |
| File permissions | `data/` dir = 700, token files = 600 |
| `.gitignore` | Prevents accidental secret commits |
| Firewall (production) | UFW: only SSH allowed |
| Fail2ban | Brute force protection |
| Systemd hardening | `NoNewPrivileges`, `PrivateTmp` |

---

## ☁️ Deployment — Oracle Cloud Free Tier (Recommended)

**Oracle Cloud Always-Free** is the best option — includes:
- 2x AMD VMs (1 OCPU, 1GB RAM each) — **forever free**
- 4x Arm VMs (24GB RAM total) — **forever free**
- No credit card auto-charges

```bash
# 1. Create free account at cloud.oracle.com
# 2. Launch Ubuntu 22.04 VM (AMD or ARM — both free)
# 3. SSH into your VM
# 4. Clone repo and run:
bash deploy_oracle.sh

# 5. Edit credentials:
nano .env

# 6. Start service:
sudo systemctl start algo-trader
sudo systemctl status algo-trader
```

### Other Free Hosting Options

| Provider | Free Tier | Notes |
|---|---|---|
| **Oracle Cloud** ⭐ | Always free, 1GB RAM | Best option |
| Railway.app | $5/month credit | Easy deploy, but limited |
| Render.com | Free tier (sleeps) | Not suitable — needs 24/7 |
| Google Cloud | 3-month free trial | E2-micro always free after |
| AWS | 12-month free trial | t2.micro (1GB RAM) |

---

## 🖥️ Management Commands

```bash
# Check system status
python manage.py status

# Update capital (takes effect immediately)
python manage.py capital 50000

# Run a dry-run scan
python manage.py scan

# Run a LIVE scan (places real orders!)
python manage.py scan --live

# View open positions with LTP
python manage.py positions

# Refresh Zerodha watchlist
python manage.py watchlist --refresh

# Send daily summary to Telegram
python manage.py summary
```

---

## 📁 File Structure

```
zerodha-algo-trader/
├── config/
│   └── config.py          # All settings (from .env)
├── core/
│   ├── kite_client.py     # Zerodha API wrapper
│   ├── risk_manager.py    # Position sizing engine
│   └── trading_engine.py  # Main orchestrator
├── strategies/
│   └── strategies.py      # All 5 trading strategies
├── utils/
│   ├── security.py        # Encryption, audit logging
│   └── telegram_notifier.py
├── logs/                  # scheduler.log, trades.csv, audit.log
├── data/                  # Encrypted token, state.json
├── scheduler.py           # APScheduler runner
├── login.py               # Daily login helper
├── manage.py              # CLI management tool
├── requirements.txt
├── .env.example           # Template — copy to .env
├── .gitignore
└── deploy_oracle.sh       # One-click Oracle Cloud setup
```

---

## ⚠️ Important Disclaimers

1. **Kite Connect costs ₹500/month** — subscribe at kite.trade before running
2. **Always test with DRY_RUN=true first** — at least 2-4 weeks of paper trading
3. **GTT orders are your safety net** — they persist even if your VM crashes
4. **Kite access token expires daily** — login.py must run each morning at 8:30 AM IST
5. **Start with small capital** — ₹10,000 is a good starting point
6. **No algo trading strategy guarantees profit** — past signals ≠ future results

---

## 🔄 Daily Operations Checklist

- [ ] 8:30 AM — Run `python login.py` (or automated)
- [ ] 9:20 AM — Morning scan runs automatically
- [ ] 3:10 PM — EOD scan runs automatically  
- [ ] 3:45 PM — Daily summary on Telegram
- [ ] Evening — Review `python manage.py positions`
