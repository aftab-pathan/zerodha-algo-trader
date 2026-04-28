#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# deploy_oracle.sh
# Enhanced deployment script for Oracle Cloud Free Tier (Ubuntu 22.04)
# Run: bash deploy_oracle.sh
# ═══════════════════════════════════════════════════════════════════

set -e
APP_DIR="/home/ubuntu/zerodha-algo-trader"
SERVICE_NAME="algo-trader"
PYTHON="/usr/bin/python3.10"

echo ""
echo "══════════════════════════════════════════"
echo "  Zerodha Algo Trader — Oracle Cloud Setup"
echo "  Version: 3.0 (Bulk Scan + Two-Tier Claude)"
echo "══════════════════════════════════════════"
echo ""

# ── 1. System packages ────────────────────────────────────────────
echo "[1/8] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3.10 python3.10-pip python3.10-venv python3.10-dev git ufw fail2ban htop curl
echo "  ✓ Python 3.10 installed"

# ── 2. Firewall (block everything except SSH) ─────────────────────
echo "[2/8] Configuring firewall..."
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw --force enable
echo "  ✓ Firewall: SSH only (no web ports exposed)"

# ── 3. Fail2ban (brute force protection) ─────────────────────────
echo "[3/8] Enabling fail2ban..."
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
echo "  ✓ Fail2ban active"

# ── 4. Add swap (for 1GB RAM Oracle VM) ───────────────────────────
echo "[4/8] Setting up swap space (2GB)..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "  ✓ Swap created: 2GB"
else
    echo "  ✓ Swap already exists"
fi

# ── 5. App setup ─────────────────────────────────────────────────
echo "[5/8] Setting up application..."
mkdir -p $APP_DIR
cd $APP_DIR

# Virtual environment
if [ ! -d "venv" ]; then
    python3.10 -m venv venv
    echo "  ✓ Virtual environment created (Python 3.10)"
fi

source venv/bin/activate

# Install dependencies
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✓ Dependencies installed"

# ── 6. Environment file ───────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[6/8] Creating .env from template..."
    cp .env.example .env
    chmod 600 .env
    echo ""
    echo "  ⚠️  IMPORTANT: Edit $APP_DIR/.env with your real credentials!"
    echo "      nano $APP_DIR/.env"
    echo ""
    echo "  Required settings:"
    echo "    - KITE_API_KEY"
    echo "    - KITE_API_SECRET"
    echo "    - TELEGRAM_BOT_TOKEN"
    echo "    - TELEGRAM_CHAT_ID"
    echo "    - TRADING_CAPITAL"
    echo "    - TRADE_DIRECTION=BUY  (BUY only, SELL only, or BOTH)"
    echo "    - DRY_RUN=true  (set false when ready for live)"
    echo ""
else
    echo "[6/8] .env already exists, skipping."
fi

# ── 7. Create directories ─────────────────────────────────────────
echo "[7/8] Creating directories..."
mkdir -p logs data
chmod 700 data   # restrict data dir to owner only
echo "  ✓ Directories created"

# ── 8. Systemd service ────────────────────────────────────────────
echo "[8/8] Installing systemd service..."
sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null <<EOF
[Unit]
Description=Zerodha Algo Trader with Bulk Scanning
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/python scheduler.py
Restart=always
RestartSec=30
StandardOutput=append:$APP_DIR/logs/scheduler.log
StandardError=append:$APP_DIR/logs/scheduler.log

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=$APP_DIR/logs $APP_DIR/data

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
echo "  ✓ Systemd service installed and enabled"

echo ""
echo "══════════════════════════════════════════"
echo "  ✅ SETUP COMPLETE!"
echo "══════════════════════════════════════════"
echo ""
echo "  📋 Next Steps:"
echo ""
echo "  1. Configure credentials:"
echo "     nano $APP_DIR/.env"
echo ""
echo "  2. IMPORTANT: Whitelist your VM IP in Kite Console:"
echo "     Your IP: \$(curl -s ifconfig.me)"
echo "     Add at: https://developers.kite.trade → Your App → IP Addresses"
echo ""
echo "  3. Create 'AlgoTrader Picks' watchlist in Kite app/web"
echo ""
echo "  4. Daily login (run at 8:30 AM IST daily):"
echo "     cd $APP_DIR && source venv/bin/activate"
echo "     python login.py"
echo ""
echo "  5. Test with dry run:"
echo "     python manage.py scan --bulk --dry-run"
echo ""
echo "  6. Start the scheduler:"
echo "     sudo systemctl start $SERVICE_NAME"
echo ""
echo "  7. Monitor logs:"
echo "     sudo journalctl -u $SERVICE_NAME -f"
echo "     # OR"
echo "     tail -f $APP_DIR/logs/scheduler.log"
echo ""
echo "  📊 Management Commands:"
echo "     python manage.py status"
echo "     python manage.py capital 50000"
echo "     python manage.py scan --bulk --dry-run"
echo "     python manage.py scan --bulk --live"
echo "     python manage.py positions"
echo ""
echo "  🔒 Security: Only SSH (port 22) is open. Use SSH tunneling for dashboard."
echo ""
echo "  💡 Features Enabled:"
echo "     ✓ Bulk scanning (1000 NSE stocks)"
echo "     ✓ Two-tier Claude optimization"
echo "     ✓ BUY-only trading filter"
echo "     ✓ Automated scheduling"
echo "     ✓ Telegram notifications"
echo ""
