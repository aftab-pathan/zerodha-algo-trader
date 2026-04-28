# Oracle Cloud Free Tier Deployment Guide

Complete guide to deploy Zerodha Algo Trader on Oracle Cloud Free Tier (Ubuntu 22.04).

---

## 🚀 **Quick Deployment**

```bash
# On your Oracle Cloud VM:
git clone https://github.com/your-repo/zerodha-algo-trader.git
cd zerodha-algo-trader
bash deploy_oracle.sh
```

---

## 📋 **Prerequisites**

### **1. Oracle Cloud VM Setup**

**Specs (Free Tier):**

- **Instance**: VM.Standard.E2.1.Micro
- **RAM**: 1 GB
- **CPU**: 1 OCPU
- **Storage**: 50 GB
- **OS**: Ubuntu 22.04 LTS
- **Region**: Any (choose closest to India for latency)

### **2. Create VM Instance**

1. Go to **Oracle Cloud Console** → **Compute** → **Instances**
2. Click **Create Instance**
3. **Image**: Ubuntu 22.04 (Minimal)
4. **Shape**: VM.Standard.E2.1.Micro (Always Free)
5. **Networking**: Create new VCN or use existing
6. **SSH Keys**: Add your public key
7. **Boot Volume**: 50 GB (default)
8. Click **Create**

### **3. Configure Security List (Firewall)**

**In Oracle Cloud Console:**

1. Go to **Networking** → **Virtual Cloud Networks**
2. Select your VCN → **Security Lists**
3. **IMPORTANT**: We'll use UFW firewall on the VM, so allow all outbound and SSH inbound only:

**Ingress Rules:**

- Source: 0.0.0.0/0
- Protocol: TCP
- Port: 22 (SSH only)

**Egress Rules:**

- Destination: 0.0.0.0/0
- Protocol: All
- Ports: All

---

## 📦 **Step-by-Step Deployment**

### **Step 1: Connect to VM**

```bash
# From your local machine
ssh -i ~/.ssh/your-key.pem ubuntu@<VM_PUBLIC_IP>
```

### **Step 2: System Update & Python Setup**

```bash
sudo apt-get update
sudo apt-get upgrade -y

# Ubuntu 22.04 comes with Python 3.10 - verify it's installed
python3.10 --version

# If not installed, install it
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev
```

**Note:** Python 3.10+ is required to avoid compatibility issues. Python 3.8 is no longer supported.

### **Step 3: Clone Repository**

```bash
cd ~
git clone https://github.com/your-repo/zerodha-algo-trader.git
cd zerodha-algo-trader
```

### **Step 4: Run Deployment Script**

```bash
bash deploy_oracle.sh
```

**What it does:**

- ✓ Installs Python 3, pip, venv
- ✓ Configures UFW firewall (SSH only)
- ✓ Sets up fail2ban (brute force protection)
- ✓ Creates 2GB swap space (for 1GB RAM VM)
- ✓ Creates virtual environment
- ✓ Installs Python dependencies
- ✓ Creates systemd service
- ✓ Sets up log directories

### **Step 5: Configure Environment**

```bash
nano .env
```

**Add your credentials:**

```bash
# Zerodha Kite Connect
KITE_API_KEY=your_key_here
KITE_API_SECRET=your_secret_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Claude AI (Optional)
ANTHROPIC_API_KEY=your_claude_key

# Trading Configuration
TRADING_CAPITAL=50000

# BUY-only trading (recommended for delivery)
TRADE_DIRECTION=BUY  # Options: BUY, SELL, or BOTH

# Bulk scanning
ENABLE_BULK_SCAN=true
ENABLE_TWO_TIER_CLAUDE=true
MAX_CLAUDE_STOCKS=20

# IMPORTANT for production
DRY_RUN=true  # Set to false when ready for live trading
```

**Save:** `Ctrl+O`, Enter, `Ctrl+X`

**Secure the file:**

```bash
chmod 600 .env
```

### **Step 6: Setup Kite IP Whitelist**

```bash
# Get your VM's public IP
curl ifconfig.me
```

**Add this IP to Kite Console:**

1. Go to https://developers.kite.trade
2. Select your app
3. **Settings** → **IP Addresses**
4. Add your VM's public IP
5. Save

**Without this step:** You'll get "No IPs configured" error when placing orders.

### **Step 7: Create Kite Watchlist**

**On Kite app or web (https://kite.zerodha.com):**

1. Go to **Watchlists**
2. Create new watchlist
3. Name it: **AlgoTrader Picks** (exact name)
4. Leave it empty - the algo will populate it

**Why needed:** Kite API doesn't support programmatic watchlist creation.

### **Step 8: Initial Login**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate
python login.py
```

**Follow the prompts:**

1. Opens login URL
2. Login to Zerodha
3. Copy `request_token` from URL
4. Paste into terminal
5. Access token saved

**Note:** This needs to be done **daily** as access tokens expire.

### **Step 9: Test Run (Dry Run)**

```bash
# Test standard scan (15 stocks) - dry run is default
python manage.py scan

# Test bulk scan (1000 stocks with two-tier Claude) - dry run is default
python manage.py scan --bulk

# Check system status
python manage.py status

# View positions
python manage.py positions
```

**Expected output:**

- ✓ Signals generated
- ✓ Risk calculations shown
- ✓ `[DRY RUN]` messages for orders
- ✗ No real orders placed

### **Step 10: Start Scheduler Service**

```bash
# Start the service
sudo systemctl start algo-trader

# Check status
sudo systemctl status algo-trader

# Enable auto-start on boot
sudo systemctl enable algo-trader
```

**Check logs:**

```bash
# Live tail
sudo journalctl -u algo-trader -f

# Or
tail -f ~/zerodha-algo-trader/logs/scheduler.log

# Today's logs
sudo journalctl -u algo-trader --since today
```

---

## ⚙️ **Automated Daily Schedule**

The scheduler runs automatically:

| Time             | Action        | Description                                              |
| ---------------- | ------------- | -------------------------------------------------------- |
| **08:30 AM IST** | Token refresh | Attempts auto-refresh (manual login required first time) |
| **09:20 AM IST** | Morning scan  | Post market open scan                                    |
| **15:10 PM IST** | EOD scan      | End-of-day scan                                          |

**Important:** You must run `python login.py` manually once per day (around 8:30 AM) as Zerodha access tokens expire daily.

---

## 🔧 **Management Commands**

### **Service Management**

```bash
# Start service
sudo systemctl start algo-trader

# Stop service
sudo systemctl stop algo-trader

# Restart service
sudo systemctl restart algo-trader

# Check status
sudo systemctl status algo-trader

# View logs (live)
sudo journalctl -u algo-trader -f

# View logs (last 50 lines)
sudo journalctl -u algo-trader -n 50
```

### **Manual Operations**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate

# Daily login (REQUIRED - run at 8:30 AM daily)
python login.py

# Manual scans (dry run is default - no real orders)
python manage.py scan                              # Standard scan (dry run)
python manage.py scan --bulk                       # Bulk scan (dry run)
python manage.py scan --live                       # Standard scan (LIVE)
python manage.py scan --bulk --live                # Bulk scan (LIVE)

# System status
python manage.py status

# Update capital
python manage.py capital 75000

# View positions
python manage.py positions

# Send daily summary
python manage.py summary
```

---

## 📊 **Monitoring & Maintenance**

### **Daily Monitoring**

```bash
# Check if service is running
sudo systemctl status algo-trader

# View today's logs
sudo journalctl -u algo-trader --since today

# Check trade log
tail -n 50 ~/zerodha-algo-trader/logs/trades.csv

# Monitor live
tail -f ~/zerodha-algo-trader/logs/scheduler.log

# Check Telegram for notifications
```

### **Weekly Maintenance**

```bash
# Update code
cd ~/zerodha-algo-trader
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart algo-trader

# Clear old logs (keep last 30 days)
find ~/zerodha-algo-trader/logs -name "*.log" -mtime +30 -delete

# Clear old cache files
find ~/zerodha-algo-trader/data -name "filtered_universe_*.json" -mtime +7 -delete
```

### **Resource Monitoring**

```bash
# Check RAM usage
free -h

# Check disk usage
df -h

# Check CPU and processes
htop

# Check swap usage
swapon --show
```

**Oracle Free Tier has 1GB RAM** - the deployment script adds 2GB swap to handle bulk scans.

---

## 🔒 **Security Hardening**

### **1. SSH Key Only (Disable Password Login)**

```bash
sudo nano /etc/ssh/sshd_config
```

Set these values:

```
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
```

Restart SSH:

```bash
sudo systemctl restart sshd
```

### **2. Fail2ban Status**

```bash
# Check fail2ban status
sudo fail2ban-client status

# Check SSH jail
sudo fail2ban-client status sshd
```

### **3. Firewall Rules**

```bash
sudo ufw status verbose
```

Should show:

```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
```

### **4. Secure Credentials**

```bash
# Ensure .env is secure
chmod 600 ~/zerodha-algo-trader/.env

# Check permissions
ls -la ~/zerodha-algo-trader/.env
# Should show: -rw------- (600)
```

### **5. Regular Security Updates**

```bash
# Weekly updates
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get autoremove -y
```

---

## 🚨 **Troubleshooting**

### **Issue: Service won't start (Python 3.8 compatibility)**

If you see the service failing with exit code 1:

```bash
sudo systemctl status algo-trader
# Shows: Active: activating (auto-restart) (Result: exit-code)
```

**Check the detailed error:**

```bash
sudo journalctl -u algo-trader -n 100 --no-pager
```

**Common fixes:**

**1. Python 3.8 type hint errors** (like `TypeError: unsupported operand type(s) for |`):

```bash
cd ~/zerodha-algo-trader
git pull  # Get the Python 3.8 compatible fixes
sudo systemctl restart algo-trader
```

**Better solution:** Upgrade to Python 3.10+ to avoid all compatibility issues:

```bash
# See PYTHON_UPGRADE.md for detailed instructions
cd ~/zerodha-algo-trader
sudo systemctl stop algo-trader
rm -rf venv
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
sudo systemctl restart algo-trader
```

**2. Missing .env file:**

```bash
# Verify .env exists
ls -la ~/zerodha-algo-trader/.env

# If missing, create it:
nano ~/zerodha-algo-trader/.env
# Add your configuration (see Step 5)
```

**3. Test manually before starting service:**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate

# Test imports
python -c "from core.trading_engine import scan_and_trade; print('OK')"

# Test scheduler
python scheduler.py
# Press Ctrl+C after seeing startup logs
```

### **Issue: Service won't start**

```bash
# Check detailed logs
sudo journalctl -u algo-trader -n 100 --no-pager

# Check permissions
ls -la ~/zerodha-algo-trader

# Test manually
cd ~/zerodha-algo-trader
source venv/bin/activate
python scheduler.py
# Press Ctrl+C to stop
```

### **Issue: Out of memory**

Oracle Free Tier has 1GB RAM. Deployment script adds swap, but if issues persist:

```bash
# Check current swap
free -h
swapon --show

# If swap not active:
sudo swapon /swapfile

# Make swap permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**For very low memory:**

- Reduce `BULK_SCAN_SIZE` to 500
- Reduce `MAX_STAGE2_STOCKS` to 100
- Disable Claude: `ENABLE_TWO_TIER_CLAUDE=false`

### **Issue: Access token expired**

```bash
# Login daily (required)
cd ~/zerodha-algo-trader
source venv/bin/activate
python login.py
```

**Tip:** Set a daily reminder at 8:30 AM IST.

### **Issue: IP not whitelisted**

```bash
# Get current VM IP
curl ifconfig.me

# Add to Kite Console:
# https://developers.kite.trade → Your App → Settings → IP Addresses
```

### **Issue: Watchlist errors**

```bash
# Error: 'AlgoTrader Picks' not found
# Solution: Create it manually in Kite app
```

Go to https://kite.zerodha.com → Watchlists → Create "AlgoTrader Picks"

### **Issue: Scan taking too long**

```bash
# Reduce universe size in .env:
BULK_SCAN_SIZE=500          # Instead of 1000
MAX_STAGE2_STOCKS=100       # Instead of 200

# Restart service
sudo systemctl restart algo-trader
```

---

## 📈 **Performance Tips**

### **1. Optimize for Low RAM (1GB)**

In `.env`:

```bash
BULK_SCAN_SIZE=500           # Reduced universe
MAX_STAGE2_STOCKS=100        # Fewer stocks for full analysis
ENABLE_TWO_TIER_CLAUDE=false # Disable Claude to save memory
```

### **2. Reduce API Costs**

```bash
# Disable Claude completely
ENABLE_TWO_TIER_CLAUDE=false
ACTIVE_STRATEGIES=ema_crossover,rsi_reversal,macd_momentum,breakout,52w_breakout

# Use standard scan instead of bulk
python manage.py scan --live  # Only 15 stocks
```

### **3. Schedule Only EOD Scan**

Edit `scheduler.py` if you only want one scan per day:

```python
# Comment out morning scan
# schedule.every().day.at(SCAN_TIME_MORNING).do(run_morning_scan)

# Keep only EOD scan
schedule.every().day.at(SCAN_TIME_EOD).do(run_eod_scan)
```

### **4. Cache Optimization**

```bash
# Longer cache duration (less API calls)
CACHE_DURATION_HOURS=2.0     # Instead of 1.0
```

---

## 💰 **Cost Summary**

| Component                     | Cost (Monthly)                   |
| ----------------------------- | -------------------------------- |
| Oracle VM (Free Tier)         | **₹0**                           |
| Zerodha Kite API              | **₹0** (2000 free API calls/day) |
| Telegram Bot                  | **₹0**                           |
| Claude API (with two-tier)    | ~₹20-40                          |
| Claude API (without two-tier) | ~₹150-180                        |
| **Total**                     | **₹0-40**                        |

**Cost-saving tips:**

- Enable `TWO_TIER_CLAUDE=true` → Saves 90% on Claude costs
- Use BUY-only filter → Less signals = fewer orders
- Standard scan vs bulk → ₹0.20 vs ₹0.40 per scan

---

## 🎯 **Production Checklist**

Before going live with real money:

**Infrastructure:**

- [ ] Oracle Cloud VM created and accessible
- [ ] UFW firewall configured (SSH only)
- [ ] Fail2ban active
- [ ] 2GB swap space created
- [ ] Deployment script executed successfully

**Configuration:**

- [ ] `.env` configured with real credentials
- [ ] `.env` file secured (chmod 600)
- [ ] IP whitelisted in Kite Connect console
- [ ] "AlgoTrader Picks" watchlist created in Kite
- [ ] `TRADE_DIRECTION=BUY` for BUY-only trading
- [ ] `DRY_RUN=true` initially for testing

**Testing:**

- [ ] Daily login tested (`python login.py`)
- [ ] Dry run standard scan successful
- [ ] Dry run bulk scan successful
- [ ] Telegram notifications working
- [ ] Service started and running
- [ ] Logs monitored for errors
- [ ] Tested position management

**Go-Live:**

- [ ] Reviewed all settings
- [ ] Set appropriate capital amount
- [ ] Set `DRY_RUN=false` in `.env`
- [ ] Restarted service: `sudo systemctl restart algo-trader`
- [ ] Confirmed first live scan completed successfully
- [ ] Monitoring setup (Telegram + logs)

---

## 📱 **Remote Monitoring**

### **SSH from Mobile**

Use **Termux** (Android) or **Blink** (iOS):

```bash
ssh -i ~/.ssh/your-key ubuntu@your-vm-ip

# Quick checks
sudo systemctl status algo-trader
tail -n 20 ~/zerodha-algo-trader/logs/scheduler.log
python ~/zerodha-algo-trader/manage.py status
```

### **Telegram Commands**

All notifications go to Telegram:

- 📊 Signals discovered
- ✅ Orders placed
- ⚠️ Errors
- 📈 Daily summaries

---

## 📞 **Support Resources**

- **Oracle Cloud Console**: https://cloud.oracle.com
- **Oracle Cloud Docs**: https://docs.oracle.com/en-us/iaas/
- **Kite Connect API**: https://kite.trade/docs/connect/v3/
- **KiteConnect Python**: https://github.com/zerodhatech/pykiteconnect
- **Anthropic Claude API**: https://docs.anthropic.com/claude/reference
- **Telegram Bot Setup**: https://core.telegram.org/bots

---

## 🎓 **Learning Resources**

### **For Trading:**

- Zerodha Varsity: https://zerodha.com/varsity/
- TradingView: https://www.tradingview.com/
- Investopedia: https://www.investopedia.com/

### **For Python:**

- Python Docs: https://docs.python.org/3/
- Pandas: https://pandas.pydata.org/
- TA-Lib: https://ta-lib.org/

---

## ✅ **Deployment Complete!**

Once deployed, your algo trader will:

- ✓ Run 24/7 automatically
- ✓ Scan 1000 NSE stocks twice daily
- ✓ Filter for BUY-only signals
- ✓ Use Claude AI on top 20 picks only
- ✓ Send notifications to Telegram
- ✓ Maintain trade logs and state
- ✓ Survive VM reboots (auto-start)

**Remember:**

1. Login daily at 8:30 AM: `python login.py`
2. Monitor Telegram for notifications
3. Check logs weekly: `sudo journalctl -u algo-trader`
4. Update capital as needed: `python manage.py capital <amount>`

**🚀 Your algo trader is now live on Oracle Cloud!**
