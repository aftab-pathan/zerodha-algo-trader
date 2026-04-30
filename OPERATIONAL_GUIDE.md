# Zerodha Algo Trader - Complete Operational Guide

**Single Source of Truth** for setup, daily operations, and maintenance.

---

## 📑 Table of Contents

1. [Initial Setup](#initial-setup)
2. [Daily Operations](#daily-operations)
3. [Dashboard Access](#dashboard-access)
4. [Trading Engine Management](#trading-engine-management)
5. [Paper Trading Mode](#paper-trading-mode)
6. [Monitoring & Maintenance](#monitoring--maintenance)
7. [Troubleshooting](#troubleshooting)
8. [Quick Reference Commands](#quick-reference-commands)

---

## 🚀 Initial Setup

### **1. Server Setup (One-Time)**

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.10 and dependencies
sudo apt install -y python3.10 python3.10-venv python3.10-dev python3-pip

# Install system tools
sudo apt install -y git nginx openssl fail2ban

# Clone repository
cd ~
git clone YOUR_REPO_URL zerodha-algo-trader
cd zerodha-algo-trader

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install -r requirements.txt
```

### **2. Configuration Setup**

```bash
# Create .env file from template
cp .env.example .env
nano .env
```

**Essential Configuration:**

```bash
# Zerodha Kite Connect
KITE_API_KEY=your_kite_api_key
KITE_API_SECRET=your_kite_api_secret

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Trading Capital
TRADING_CAPITAL=50000

# Trading Mode
PAPER_TRADING_MODE=false    # false for live, true for paper
DRY_RUN=false               # false for real orders, true for testing

# Claude AI (Optional)
ANTHROPIC_API_KEY=sk-ant-your-key
```

**Save:** `Ctrl+O`, Enter, `Ctrl+X`

```bash
# Secure the .env file
chmod 600 .env
```

### **3. Zerodha Setup**

#### **A. Whitelist Your Server IP**

```bash
# Get your server IP
curl ifconfig.me
```

**Then:**

1. Go to https://developers.kite.trade
2. Select your app → Settings → IP Addresses
3. Add your server IP
4. Save

#### **B. Initial Login**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate
python login.py
```

Follow the prompts to authenticate. Access token is valid for 24 hours.

### **4. Trading Engine Service Setup**

```bash
# Get your username
echo $USER

# Create trading engine service
cd ~/zerodha-algo-trader
sed "s/YOUR_USERNAME/$USER/g" algo-trader.service | sudo tee /etc/systemd/system/algo-trader.service

# If the template doesn't exist, create it:
cat << 'EOF' | sudo tee /etc/systemd/system/algo-trader.service
[Unit]
Description=Zerodha Algo Trading Engine
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/zerodha-algo-trader
Environment="PATH=/home/$USER/zerodha-algo-trader/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/$USER/zerodha-algo-trader/venv/bin/python scheduler.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=algo-trader

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable algo-trader
sudo systemctl start algo-trader

# Check status
sudo systemctl status algo-trader
```

### **5. Dashboard Service Setup**

```bash
# Get your username
echo $USER

# Create dashboard service
cd ~/zerodha-algo-trader
sed "s/YOUR_USERNAME/$USER/g" algo-dashboard.service | sudo tee /etc/systemd/system/algo-dashboard.service

# Reload systemd
sudo systemctl daemon-reload

# Enable and start dashboard
sudo systemctl enable algo-dashboard
sudo systemctl start algo-dashboard

# Check status
sudo systemctl status algo-dashboard
```

### **6. Nginx & SSL Setup (For Remote Access)**

#### **A. Generate SSL Certificate**

```bash
# Get your server IP
SERVER_IP=$(curl -s ifconfig.me)

# Create SSL certificate
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/algo-dashboard.key \
  -out /etc/ssl/certs/algo-dashboard.crt \
  -subj "/C=IN/ST=State/L=City/O=AlgoTrader/CN=$SERVER_IP"

# Set permissions
sudo chmod 600 /etc/ssl/private/algo-dashboard.key
sudo chmod 644 /etc/ssl/certs/algo-dashboard.crt
```

#### **B. Configure Nginx**

```bash
# Get your server IP
SERVER_IP=$(curl -s ifconfig.me)

# Create Nginx configuration
cat << EOF | sudo tee /etc/nginx/sites-available/algo-dashboard
# Rate limiting zones
limit_req_zone \$binary_remote_addr zone=dashboard_login:10m rate=5r/m;
limit_req_zone \$binary_remote_addr zone=dashboard_api:10m rate=30r/m;

# HTTP to HTTPS redirect
server {
    listen 80;
    server_name $SERVER_IP;
    return 301 https://\$host\$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name $SERVER_IP;

    ssl_certificate /etc/ssl/certs/algo-dashboard.crt;
    ssl_certificate_key /etc/ssl/private/algo-dashboard.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;

    server_tokens off;
    limit_req zone=dashboard_api burst=20 nodelay;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400s;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/algo-dashboard /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload Nginx
sudo nginx -t
sudo systemctl reload nginx
```

#### **C. Configure Firewall**

```bash
# Allow required ports
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS

# Enable firewall
sudo ufw --force enable

# Check status
sudo ufw status verbose
```

### **7. Cloud Provider Firewall (If using Oracle Cloud)**

**In Oracle Cloud Console:**

1. Go to **Networking** → **Virtual Cloud Networks**
2. Select your VCN → **Security Lists** → **Default Security List**
3. Add Ingress Rules:
   - **Port 80**: Source `0.0.0.0/0`, Protocol `TCP`
   - **Port 443**: Source `0.0.0.0/0`, Protocol `TCP`

### **8. Verify Setup**

```bash
# Check trading engine
sudo systemctl status algo-trader

# Check dashboard
sudo systemctl status algo-dashboard

# Check Nginx
sudo systemctl status nginx

# Test dashboard locally
curl -k https://localhost

# Get your server IP
curl ifconfig.me
```

**Access Dashboard:** `https://YOUR_SERVER_IP`

---

## 📅 Daily Operations

### **Morning Routine (08:30 - 09:15 AM IST)**

#### **1. Daily Login (REQUIRED)**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate
python login.py
```

**Why:** Kite access tokens expire every 24 hours.

**📌 Important:** Login is required EVEN in paper trading mode because the system needs real market data (prices, quotes) for simulation. Only orders are simulated - market data is real.

#### **2. Check System Status**

```bash
# Check if services are running
sudo systemctl status algo-trader
sudo systemctl status algo-dashboard

# Check recent logs
sudo journalctl -u algo-trader --since today -n 50

# Check system status
python manage.py status
```

#### **3. Verify Configuration**

```bash
# Check current mode
grep -E "PAPER_TRADING_MODE|DRY_RUN" .env

# Check capital
python manage.py status | grep Capital
```

### **Market Hours (09:15 AM - 03:30 PM IST)**

#### **Automated Scans (No Action Required)**

- **09:20 AM:** Morning scan (automatic)
- **03:10 PM:** End-of-day scan (automatic)
- **03:45 PM:** Daily summary sent to Telegram

#### **Manual Scan (If Needed)**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate

# Standard scan (15 stocks)
python manage.py scan --live

# Bulk scan (1000 stocks)
python manage.py scan --bulk --live

# Dry run (test without real orders)
python manage.py scan --dry-run
```

#### **Monitor Positions**

```bash
# View current positions
python manage.py positions

# Check via dashboard
# Open: https://YOUR_SERVER_IP
# Navigate to "📊 Overview" page
```

### **Evening Routine (After Market Close)**

#### **1. Review Day's Activity**

```bash
# Check daily summary
cat logs/scheduler.log | grep "DAILY SUMMARY" -A 20

# View trade log
tail -20 logs/trades.csv

# Check P&L
python manage.py summary
```

#### **2. Check Logs**

```bash
# View today's trading engine logs
sudo journalctl -u algo-trader --since today

# View dashboard logs
sudo journalctl -u algo-dashboard --since today -n 50

# Check error logs
tail -50 logs/app.log | grep ERROR
```

#### **3. Monitor via Dashboard**

Access: `https://YOUR_SERVER_IP`

Check:

- ✅ Open positions
- ✅ Today's signals
- ✅ P&L Analytics
- ✅ Paper trading comparison (if enabled)

---

## 🖥️ Dashboard Access

### **Local Access (On Server)**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate
streamlit run dashboard/app.py
```

Access: `http://localhost:8501`

### **Remote Access (From Anywhere)**

**URL:** `https://YOUR_SERVER_IP`

**From Browser:**

1. Open `https://YOUR_SERVER_IP`
2. Accept security warning (self-signed certificate)
3. Click "Advanced" → "Proceed"
4. Login with dashboard password

**From Mobile:**

1. Open browser on phone
2. Visit `https://YOUR_SERVER_IP`
3. Accept certificate warning
4. Login and use dashboard

**Tip:** Bookmark or add to home screen for quick access

### **Dashboard Pages**

- **📊 Overview:** Real-time portfolio, open positions, KPIs
- **📝 Paper Trading:** Paper vs Live comparison, performance metrics
- **📈 P&L Analytics:** Cumulative P&L, win rate, profit factor
- **🔬 Backtesting:** Test strategies on historical data
- **⚙️ Capital & Risk:** View/update capital, risk parameters
- **📋 Watchlist:** Manage stock watchlists
- **📜 Logs:** Audit trail, system logs

### **Set Dashboard Password**

```bash
cd ~/zerodha-algo-trader
nano .env
```

Add:

```bash
# Generate password hash
# Run: python3 -c "import hashlib; print(hashlib.sha256(b'YourPassword').hexdigest())"
DASHBOARD_PASSWORD_HASH=<paste_hash_here>
```

Restart dashboard:

```bash
sudo systemctl restart algo-dashboard
```

---

## ⚙️ Trading Engine Management

### **Service Control**

```bash
# Start trading engine
sudo systemctl start algo-trader

# Stop trading engine
sudo systemctl stop algo-trader

# Restart trading engine
sudo systemctl restart algo-trader

# Check status
sudo systemctl status algo-trader

# View live logs
sudo journalctl -u algo-trader -f

# View recent logs
sudo journalctl -u algo-trader -n 100 --no-pager
```

### **Manual Trading Operations**

#### **Run Manual Scan**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate

# Standard scan with real orders
python manage.py scan --live

# Bulk scan (1000 stocks)
python manage.py scan --bulk --live

# Test scan (no real orders)
python manage.py scan --dry-run
```

#### **View Positions**

```bash
# View all positions
python manage.py positions

# Check specific symbol
grep "RELIANCE" logs/trades.csv
```

#### **Update Capital**

```bash
# Update trading capital
python manage.py capital 75000

# View current capital
python manage.py status | grep Capital
```

#### **Send Summary**

```bash
# Send daily summary to Telegram
python manage.py summary
```

### **Configuration Changes**

#### **Change Trading Mode**

```bash
cd ~/zerodha-algo-trader
nano .env
```

**For Live Trading:**

```bash
PAPER_TRADING_MODE=false
DRY_RUN=false
```

**For Paper Trading:**

```bash
PAPER_TRADING_MODE=true
```

**For Testing (No Orders):**

```bash
DRY_RUN=true
```

**Restart services after changes:**

```bash
sudo systemctl restart algo-trader
sudo systemctl restart algo-dashboard
```

#### **Update Risk Parameters**

```bash
nano .env
```

Common parameters:

```bash
MAX_RISK_PER_TRADE=0.02        # 2% risk per trade
MAX_OPEN_POSITIONS=5            # Max concurrent positions
MIN_CONFIDENCE=7.0              # Minimum strategy confidence
MIN_RISK_REWARD=2.0             # Minimum risk:reward ratio
```

Restart:

```bash
sudo systemctl restart algo-trader
```

### **Update Code**

```bash
cd ~/zerodha-algo-trader
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart algo-trader
sudo systemctl restart algo-dashboard
```

---

## 📝 Paper Trading Mode

Paper trading simulates all order execution without risking real capital. However, it still requires Zerodha authentication to fetch real market data (prices, charts, quotes) for accurate simulation.

### **Enable Paper Trading**

```bash
cd ~/zerodha-algo-trader
nano .env
```

Set:

```bash
PAPER_TRADING_MODE=true
PAPER_TRADING_CAPITAL=50000
```

Restart:

```bash
sudo systemctl restart algo-trader
sudo systemctl restart algo-dashboard
```

### **Monitor Paper Trading**

**Via Dashboard:**

- Navigate to "📝 Paper Trading" page
- View paper vs live comparison
- Check performance metrics

**Via Logs:**

```bash
# View paper trading activity
sudo journalctl -u algo-trader | grep PAPER

# Check paper state
cat data/paper_state.json | jq
```

**Via Telegram:**

- All paper trade notifications show `🟡 [PAPER]` prefix

### **Paper Trading Operations**

```bash
# View paper state
cat data/paper_state.json | jq

# View paper positions
cat data/paper_state.json | jq '.open_positions'

# View paper P&L
cat data/paper_state.json | jq '.total_pnl'

# Reset paper trading data (from dashboard settings page)
# Or manually:
rm data/paper_state.json
```

### **Switch Back to Live Trading**

```bash
nano .env
```

Set:

```bash
PAPER_TRADING_MODE=false
```

Restart:

```bash
sudo systemctl restart algo-trader
sudo systemctl restart algo-dashboard
```

---

## 🔧 Monitoring & Maintenance

### **Daily Monitoring**

```bash
# Quick health check
sudo systemctl status algo-trader algo-dashboard nginx

# Check today's activity
sudo journalctl -u algo-trader --since today | tail -100

# View recent trades
tail -20 logs/trades.csv

# Check Telegram notifications
# (check your Telegram app)
```

### **Weekly Maintenance**

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Check disk usage
df -h

# Check memory usage
free -h

# Clear old logs (keep last 30 days)
find logs/ -name "*.log" -mtime +30 -delete

# Check service status
sudo systemctl status algo-trader algo-dashboard nginx
```

### **Monthly Tasks**

```bash
# Review and update capital
python manage.py capital 60000

# Check strategy performance via dashboard
# Navigate to "📈 P&L Analytics"

# Backup important data
cp data/state.json backups/state_$(date +%Y%m%d).json
cp data/paper_state.json backups/paper_state_$(date +%Y%m%d).json
cp logs/trades.csv backups/trades_$(date +%Y%m%d).csv

# Update code if needed
cd ~/zerodha-algo-trader
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart algo-trader algo-dashboard
```

### **Monitor Resource Usage**

```bash
# CPU and memory
top
# Press 'q' to quit

# Or use htop (install: sudo apt install htop)
htop

# Disk I/O
iostat -x 2

# Network connections
sudo netstat -tulpn
```

### **Check Service Logs**

```bash
# Trading engine logs (live tail)
sudo journalctl -u algo-trader -f

# Trading engine logs (recent)
sudo journalctl -u algo-trader -n 200 --no-pager

# Dashboard logs
sudo journalctl -u algo-dashboard -n 100

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Application logs
tail -f logs/app.log
tail -f logs/scheduler.log
```

---

## 🚨 Troubleshooting

### **Trading Engine Won't Start**

```bash
# Check detailed error
sudo journalctl -u algo-trader -n 100 --no-pager

# Test manually
cd ~/zerodha-algo-trader
source venv/bin/activate
python scheduler.py
# Press Ctrl+C to stop

# Common fixes:
# 1. Check .env file exists and is valid
ls -la .env
cat .env | grep -v "^#" | grep -v "^$"

# 2. Check Python dependencies
pip install -r requirements.txt

# 3. Check permissions
chmod 600 .env

# 4. Fix logs/data directory permissions (MOST COMMON ISSUE)
cd ~/zerodha-algo-trader
sudo chown -R $USER:$USER logs/ data/
chmod -R 755 logs/ data/
chmod 644 logs/*.log logs/*.csv 2>/dev/null || true
chmod 644 data/*.json data/*.enc 2>/dev/null || true

# 5. Fix entire project ownership
sudo chown -R $USER:$USER ~/zerodha-algo-trader
```

### **Dashboard Not Accessible**

```bash
# Check dashboard service
sudo systemctl status algo-dashboard

# Check if Streamlit is running
sudo lsof -i :8501

# Check Nginx
sudo systemctl status nginx
sudo nginx -t

# Test locally
curl -k https://localhost

# Check firewall
sudo ufw status verbose

# Restart services
sudo systemctl restart algo-dashboard
sudo systemctl restart nginx
```

### **SSL Certificate Issues**

```bash
# Check certificate exists
ls -lh /etc/ssl/certs/algo-dashboard.crt
ls -lh /etc/ssl/private/algo-dashboard.key

# Regenerate certificate
SERVER_IP=$(curl -s ifconfig.me)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/algo-dashboard.key \
  -out /etc/ssl/certs/algo-dashboard.crt \
  -subj "/C=IN/ST=State/L=City/O=AlgoTrader/CN=$SERVER_IP"

sudo systemctl reload nginx
```

### **Kite Authentication Failed**

```bash
# Login again
cd ~/zerodha-algo-trader
source venv/bin/activate
python login.py

# Check IP is whitelisted
# Visit: https://developers.kite.trade
# Go to your app → Settings → IP Addresses
# Add your server IP: curl ifconfig.me
```

**Network Unreachable Error:**

If you get `OSError: [Errno 101] Network is unreachable`, check:

1. **Internet connectivity:**

   ```bash
   ping -c 3 api.kite.trade
   curl https://api.kite.trade
   ```

2. **DNS resolution:**

   ```bash
   nslookup api.kite.trade
   ```

3. **Firewall/network rules:**

   ```bash
   sudo iptables -L -n
   # Check if outbound HTTPS (port 443) is allowed
   ```

4. **Cloud provider firewall** (Oracle Cloud, AWS, etc.):
   - Check egress rules allow HTTPS to external IPs

### **Orders Not Placing**

**Check:**

1. ✅ Kite authenticated: `python login.py`
2. ✅ IP whitelisted on Kite developer console
3. ✅ Not in DRY_RUN mode: `grep DRY_RUN .env`
4. ✅ Not in PAPER mode (unless intended): `grep PAPER_TRADING_MODE .env`
5. ✅ Sufficient capital: `python manage.py status`
6. ✅ No circuit breakers triggered: Check logs

```bash
# View order placement logs
sudo journalctl -u algo-trader | grep "Order placed"

# Check for errors
sudo journalctl -u algo-trader | grep ERROR
```

### **High Memory/CPU Usage**

```bash
# Check resource usage
top

# Restart services
sudo systemctl restart algo-trader
sudo systemctl restart algo-dashboard

# Reduce bulk scan size (edit .env)
nano .env
# Set: BULK_SCAN_SIZE=500
```

### **Paper Trading Not Syncing**

```bash
# Check paper sync is running
sudo journalctl -u algo-trader | grep "PAPER TRADING SYNC"

# Check paper state file
cat data/paper_state.json | jq

# Manually trigger sync
cd ~/zerodha-algo-trader
source venv/bin/activate
python -c "from core.paper_sync_engine import sync_paper_positions; sync_paper_positions()"
```

---

## ⚡ Quick Reference Commands

### **Daily Essentials**

```bash
# Morning login
cd ~/zerodha-algo-trader && source venv/bin/activate && python login.py

# Check status
python manage.py status

# View positions
python manage.py positions

# Manual scan
python manage.py scan --live

# Check logs
sudo journalctl -u algo-trader --since today -n 50
```

### **Service Management**

```bash
# Restart everything
sudo systemctl restart algo-trader algo-dashboard nginx

# Check all services
sudo systemctl status algo-trader algo-dashboard nginx

# View logs
sudo journalctl -u algo-trader -f
sudo journalctl -u algo-dashboard -f
```

### **Configuration**

```bash
# Edit config
nano ~/zerodha-algo-trader/.env

# Update capital
cd ~/zerodha-algo-trader && source venv/bin/activate && python manage.py capital 60000

# Switch modes
# Edit .env: PAPER_TRADING_MODE=true/false
# Then: sudo systemctl restart algo-trader algo-dashboard
```

### **Monitoring**

```bash
# Dashboard access
echo "https://$(curl -s ifconfig.me)"

# Check trades
tail -20 ~/zerodha-algo-trader/logs/trades.csv

# System health
df -h && free -h && uptime
```

### **Troubleshooting**

```bash
# View errors
sudo journalctl -u algo-trader -n 200 --no-pager | grep ERROR

# Test manually
cd ~/zerodha-algo-trader && source venv/bin/activate && python manage.py scan --dry-run

# Restart with logs
sudo systemctl restart algo-trader && sudo journalctl -u algo-trader -f
```

---

## 📱 Mobile Quick Access

**Add to Phone Home Screen:**

1. Open `https://YOUR_SERVER_IP` in mobile browser
2. Accept certificate warning
3. Login
4. Chrome: Menu → "Add to Home Screen"
5. Safari: Share → "Add to Home Screen"

**Quick Check via SSH:**

Use Termux (Android) or Blink (iOS):

```bash
ssh YOUR_USERNAME@YOUR_SERVER_IP
cd zerodha-algo-trader
python manage.py status
sudo systemctl status algo-trader
```

---

## 📞 Support & Resources

### **Documentation**

- Main README: `README.md`
- Production Setup: `PRODUCTION_SETUP.md`
- Oracle Deployment: `ORACLE_CLOUD_DEPLOYMENT.md`
- Dashboard Deployment: `DASHBOARD_DEPLOYMENT.md`
- Paper Trading: `PAPER_TRADING_IMPLEMENTATION.md`

### **Important Files**

- Configuration: `.env`
- Live State: `data/state.json`
- Paper State: `data/paper_state.json`
- Trade Log: `logs/trades.csv`
- Application Log: `logs/app.log`
- Scheduler Log: `logs/scheduler.log`

### **External Resources**

- Kite API Docs: https://kite.trade/docs/connect/v3/
- KiteConnect Python: https://github.com/zerodhatech/pykiteconnect
- Zerodha Developer Console: https://developers.kite.trade

### **Getting Help**

1. Check logs: `sudo journalctl -u algo-trader -n 100`
2. Review error messages
3. Check configuration: `cat .env | grep -v "^#"`
4. Test manually: `python manage.py scan --dry-run`
5. Check Telegram for notifications

---

## ✅ Pre-Flight Checklist

**Before Going Live:**

- [ ] ✅ Server setup complete
- [ ] ✅ `.env` configured with real credentials
- [ ] ✅ Kite API key and secret added
- [ ] ✅ Server IP whitelisted on Kite console
- [ ] ✅ Daily login successful (`python login.py`)
- [ ] ✅ Trading capital set
- [ ] ✅ Risk parameters reviewed
- [ ] ✅ Telegram notifications working
- [ ] ✅ Trading engine service running
- [ ] ✅ Dashboard accessible remotely
- [ ] ✅ Test scan completed successfully
- [ ] ✅ `PAPER_TRADING_MODE=false` for live
- [ ] ✅ `DRY_RUN=false` for real orders
- [ ] ✅ Backup plan in place
- [ ] ✅ Monitoring setup (Telegram + Dashboard)

**Daily Checklist:**

- [ ] ✅ 08:30 AM: Run `python login.py` (required even in paper mode)
- [ ] ✅ 08:45 AM: Check system status
- [ ] ✅ 09:15 AM: Verify services running
- [ ] ✅ 09:30 AM: Monitor Telegram for signals
- [ ] ✅ 03:45 PM: Review daily summary
- [ ] ✅ 04:00 PM: Check positions and P&L
- [ ] ✅ Evening: Review logs for errors

---

**Last Updated:** 29 April 2026  
**Version:** 1.0

---

**🚀 You're all set! Trade smart, trade safe!**
