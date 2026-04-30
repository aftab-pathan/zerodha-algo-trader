# Dashboard Remote Access Setup Guide

Complete guide to access your Algo Trader dashboard securely from anywhere via HTTPS.

---

## 🎯 **Overview**

This guide enables secure remote access to your Streamlit dashboard using:

- **Nginx** as reverse proxy (port 443 HTTPS → 8501 internal)
- **Self-signed SSL certificate** for encryption
- **Firewall rules** for security
- **Systemd service** for auto-start

**Access Method:** `https://YOUR_VM_IP` from any device

---

## 📋 **Prerequisites**

- Algo trader deployed and running (see ORACLE_CLOUD_DEPLOYMENT.md)
- SSH access to your VM
- VM public IP address (run `curl ifconfig.me` on VM to get it)
- Dashboard tested locally: `streamlit run dashboard/app.py`

---

## 🚀 **Step-by-Step Setup**

### **Step 1: Install Required Packages**

```bash
# Connect to your VM
ssh -i ~/.ssh/your-key.pem ubuntu@YOUR_VM_IP

# Update package list
sudo apt update

# Install Nginx and OpenSSL
sudo apt install -y nginx openssl

# Verify Nginx installed
nginx -v
```

---

### **Step 2: Generate Self-Signed SSL Certificate**

```bash
# Create directory for certificates
sudo mkdir -p /etc/ssl/private
sudo mkdir -p /etc/ssl/certs

# Generate 2048-bit RSA self-signed certificate (valid for 1 year)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/algo-dashboard.key \
  -out /etc/ssl/certs/algo-dashboard.crt \
  -subj "/C=IN/ST=GUJRAT/L=SURAT/O=AlgoTrader/CN=161.118.177.247"

# Set secure permissions
sudo chmod 600 /etc/ssl/private/algo-dashboard.key
sudo chmod 644 /etc/ssl/certs/algo-dashboard.crt

# Verify certificate created
ls -lh /etc/ssl/private/algo-dashboard.key
ls -lh /etc/ssl/certs/algo-dashboard.crt
```

**Note:** Replace `YOUR_VM_IP` with your actual VM IP address in the command above.

---

### **Step 3: Configure Nginx Reverse Proxy**

```bash
# Create Nginx configuration file
sudo nano /etc/nginx/sites-available/algo-dashboard
```

**Paste this configuration:**

```nginx
# Rate limiting zones
limit_req_zone  $binary_remote_addr zone=dashboard_login:10m  rate=5r/m;
limit_req_zone  $binary_remote_addr zone=dashboard_api:10m    rate=30r/m;

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name 161.118.177.247;

    # Redirect all HTTP traffic to HTTPS
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name 161.118.177.247;

    # SSL Certificate paths
    ssl_certificate     /etc/ssl/certs/algo-dashboard.crt;
    ssl_certificate_key /etc/ssl/private/algo-dashboard.key;

    # SSL Configuration
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options           DENY                                   always;
    add_header X-Content-Type-Options    nosniff                                always;
    add_header X-XSS-Protection          "1; mode=block"                        always;
    add_header Referrer-Policy           "no-referrer"                          always;
    add_header Content-Security-Policy   "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: wss: https:;" always;

    # Hide server version
    server_tokens off;

    # Rate limiting
    limit_req zone=dashboard_api burst=20 nodelay;

    # Proxy to Streamlit
    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;

        # WebSocket support for Streamlit
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";

        # Headers
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout    60s;
        proxy_read_timeout    86400s; # 24 hours for long-running requests
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "OK";
    }

    # Block hidden files
    location ~ /\. {
        deny all;
    }
}
```

**Replace `YOUR_VM_IP` with your actual VM IP address (e.g., `132.145.xxx.xxx`).**

**Save:** `Ctrl+O`, Enter, `Ctrl+X`

---

### **Step 4: Enable Nginx Configuration**

```bash
# Create symbolic link to enable site
sudo ln -s /etc/nginx/sites-available/algo-dashboard /etc/nginx/sites-enabled/

# Remove default Nginx site (optional, but recommended)
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration for syntax errors
sudo nginx -t

# Expected output:
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test is successful

# Reload Nginx to apply changes
sudo systemctl reload nginx

# Check Nginx status
sudo systemctl status nginx
```

---

### **Step 5: Configure Firewall**

```bash
# Allow HTTPS traffic (port 443)
sudo ufw allow 443/tcp

# Allow HTTP traffic (port 80) - will redirect to HTTPS
sudo ufw allow 80/tcp

# Verify SSH is allowed (should already be allowed)
sudo ufw allow 22/tcp

# Enable firewall if not already enabled
sudo ufw enable

# Check firewall status
sudo ufw status verbose

# Expected output should show:
# 22/tcp     ALLOW IN    Anywhere
# 80/tcp     ALLOW IN    Anywhere
# 443/tcp    ALLOW IN    Anywhere
```

---

### **Step 6: Setup Dashboard as Systemd Service**

```bash
# Get your current username
echo $USER
# Output will be your username (e.g., ubuntu, aftab, etc.)

# Replace YOUR_USERNAME with your actual username and create service file
# Replace 'ubuntu' in the command below with your actual username from above
cd ~/zerodha-algo-trader
sed "s/YOUR_USERNAME/ubuntu/g" algo-dashboard.service | sudo tee /etc/systemd/system/algo-dashboard.service

# Alternative: If your username is different (e.g., 'aftab'), use:
# sed "s/YOUR_USERNAME/aftab/g" algo-dashboard.service | sudo tee /etc/systemd/system/algo-dashboard.service
```

**⚠️ Important:** Replace `ubuntu` in the command above with YOUR actual username (shown by `echo $USER`)

# Reload systemd

sudo systemctl daemon-reload

# Enable service to start on boot

sudo systemctl enable algo-dashboard

# Start dashboard service

sudo systemctl start algo-dashboard

# Check service status

sudo systemctl status algo-dashboard

# Expected output: Active: active (running)

````

---

### **Step 7: Update Oracle Cloud Security List (CRITICAL)**

**In Oracle Cloud Console:**

1. Go to **Networking** → **Virtual Cloud Networks**
2. Select your VCN → **Security Lists** → **Default Security List**
3. Click **Add Ingress Rules**

**Add these two rules:**

**Rule 1: HTTP (Port 80)**

- Source CIDR: `0.0.0.0/0`
- IP Protocol: `TCP`
- Destination Port Range: `80`
- Description: `HTTP redirect to HTTPS`

**Rule 2: HTTPS (Port 443)**

- Source CIDR: `0.0.0.0/0`
- IP Protocol: `TCP`
- Destination Port Range: `443`
- Description: `HTTPS dashboard access`

4. Click **Add Ingress Rules**

**Without this step, you won't be able to access the dashboard from outside!**

---

### **Step 8: Test Dashboard Access**

**From your local machine:**

```bash
# Test HTTP → HTTPS redirect
curl -I http://YOUR_VM_IP
# Should return: HTTP/1.1 301 Moved Permanently
# Location: https://YOUR_VM_IP/

# Test HTTPS connection
curl -k https://YOUR_VM_IP
# Should return Streamlit HTML content
````

**From your web browser:**

1. Open: `https://YOUR_VM_IP`
2. **Browser warning:** "Your connection is not private" or "NET::ERR_CERT_AUTHORITY_INVALID"
3. Click **"Advanced"** → **"Proceed to YOUR_VM_IP (unsafe)"**
   - This is normal for self-signed certificates
   - Your connection is still encrypted, just not verified by a Certificate Authority
4. You should see the **Algo Trader Login Page** 🔒
5. Enter your dashboard password
6. Access granted! 🎉

---

## 📊 **Managing the Dashboard Service**

### **Service Commands**

```bash
# Start dashboard
sudo systemctl start algo-dashboard

# Stop dashboard
sudo systemctl stop algo-dashboard

# Restart dashboard
sudo systemctl restart algo-dashboard

# Check status
sudo systemctl status algo-dashboard

# View logs (real-time)
sudo journalctl -u algo-dashboard -f

# View logs (last 100 lines)
sudo journalctl -u algo-dashboard -n 100
```

### **Troubleshooting Dashboard**

**If dashboard won't start:**

```bash
# Check detailed logs
sudo journalctl -u algo-dashboard -n 50 --no-pager

# Test Streamlit manually
cd ~/zerodha-algo-trader
source venv/bin/activate
streamlit run dashboard/app.py

# Check if port 8501 is in use
sudo lsof -i :8501

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

---

## 🔒 **Security Best Practices**

### **1. Set Strong Dashboard Password**

```bash
cd ~/zerodha-algo-trader
nano .env
```

Add/update:

```bash
# Generate strong password hash
# Method 1: Using Python
python3 -c "import hashlib; print(hashlib.sha256(b'YourStrongPassword123').hexdigest())"

# Method 2: Using OpenSSL
echo -n "YourStrongPassword123" | openssl dgst -sha256

# Add hash to .env:
DASHBOARD_PASSWORD_HASH=<your_sha256_hash>
```

**Restart dashboard:**

```bash
sudo systemctl restart algo-dashboard
```

### **2. Enable IP Whitelist (Recommended)**

Edit Nginx config to allow only your IP:

```bash
sudo nano /etc/nginx/sites-available/algo-dashboard
```

Add before `location /` block:

```nginx
    # Allow only your IP
    allow YOUR_HOME_IP;        # e.g., 203.0.113.10
    allow YOUR_OFFICE_IP;      # e.g., 198.51.100.5
    deny all;
```

Reload Nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### **3. Enable Fail2Ban (Block Brute Force)**

```bash
# Install fail2ban
sudo apt install -y fail2ban

# Create Nginx filter
sudo nano /etc/fail2ban/filter.d/nginx-dashboard.conf
```

Paste:

```ini
[Definition]
failregex = ^<HOST>.*"POST.*HTTP.*" (401|403)
ignoreregex =
```

Create jail:

```bash
sudo nano /etc/fail2ban/jail.local
```

Paste:

```ini
[nginx-dashboard]
enabled = true
port = http,https
filter = nginx-dashboard
logpath = /var/log/nginx/access.log
maxretry = 5
bantime = 3600
findtime = 600
```

Restart fail2ban:

```bash
sudo systemctl restart fail2ban
sudo fail2ban-client status nginx-dashboard
```

---

## 📱 **Mobile Access**

**Access from phone/tablet:**

1. Open browser (Chrome/Safari)
2. Go to: `https://YOUR_VM_IP`
3. Accept security warning (self-signed cert)
4. Login with your password
5. Dashboard works on mobile! 📱

**Tip:** Add to home screen for quick access (works like an app)

---

## 🌐 **Optional: Use Custom Domain**

If you have a domain (costs ~$10-15/year):

### **Step 1: Update DNS**

In your domain registrar:

- Add **A Record**: `dashboard.yourdomain.com` → `YOUR_VM_IP`

### **Step 2: Get Free SSL Certificate**

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Get certificate (replace with your domain)
sudo certbot --nginx -d dashboard.yourdomain.com

# Auto-renewal test
sudo certbot renew --dry-run
```

### **Step 3: Update Nginx Config**

```bash
sudo nano /etc/nginx/sites-available/algo-dashboard
```

Change `server_name YOUR_VM_IP;` to `server_name dashboard.yourdomain.com;`

Reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Now access at: `https://dashboard.yourdomain.com` (no browser warning!) ✅

---

## ✅ **Verification Checklist**

- [ ] Nginx installed and running
- [ ] Self-signed SSL certificate created
- [ ] Nginx configuration correct (nginx -t passes)
- [ ] Firewall allows ports 80, 443
- [ ] Oracle Cloud Security List allows ports 80, 443
- [ ] Dashboard service running (systemctl status)
- [ ] HTTPS accessible from external browser
- [ ] Login page appears
- [ ] Dashboard password works
- [ ] All pages load correctly (Overview, P&L, etc.)
- [ ] No JavaScript errors in browser console

---

## 🎯 **Summary**

You can now access your algo trader dashboard from **anywhere**:

📊 **URL:** `https://YOUR_VM_IP`  
🔒 **Encrypted:** Yes (HTTPS with self-signed cert)  
🛡️ **Secure:** Password protected + Nginx security headers  
📱 **Mobile:** Works on all devices  
⚡ **Auto-start:** Runs automatically on VM reboot

**Next Steps:**

1. Bookmark the URL on all your devices
2. Monitor via Telegram for trade alerts
3. Check dashboard daily for P&L and positions
4. Consider setting up domain + Let's Encrypt for no browser warnings

---

## 📞 **Support**

If you encounter issues:

1. Check logs: `sudo journalctl -u algo-dashboard -n 100`
2. Check Nginx logs: `sudo tail -f /var/log/nginx/error.log`
3. Test manually: `streamlit run dashboard/app.py`
4. Verify firewall: `sudo ufw status verbose`
5. Verify ports: `sudo netstat -tulpn | grep -E ':(80|443|8501)'`

**Your dashboard is now accessible 24/7 from anywhere! 🚀**
