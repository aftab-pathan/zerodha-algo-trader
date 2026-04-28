# Upgrade Python from 3.8 to 3.10+ on Ubuntu 22.04

If you're experiencing Python 3.8 compatibility issues, follow these steps to upgrade to Python 3.10.

---

## ✅ **Quick Upgrade (Recommended)**

Ubuntu 22.04 comes with Python 3.10 by default. If you're using Python 3.8, you just need to recreate the virtual environment with Python 3.10:

```bash
cd ~/zerodha-algo-trader

# Stop the service
sudo systemctl stop algo-trader

# Check available Python versions
python3 --version          # Shows default version
python3.10 --version       # Should show Python 3.10.x
python3.11 --version       # May or may not be installed

# Remove old virtual environment
rm -rf venv

# Create new virtual environment with Python 3.10
python3.10 -m venv venv

# Activate it
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Test that it works
python --version           # Should show Python 3.10.x

# Test imports
python -c "from core.trading_engine import scan_and_trade; print('✅ Imports OK')"

# Restart the service
sudo systemctl restart algo-trader

# Check status
sudo systemctl status algo-trader
```

---

## 🔧 **If Python 3.10 is Not Installed**

If `python3.10 --version` fails, install it:

```bash
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev
```

Then follow the steps above to recreate the virtual environment.

---

## 📦 **Install Python 3.11 (Optional - Most Modern)**

For the latest features and best performance:

```bash
# Add deadsnakes PPA (provides newer Python versions)
sudo apt-get update
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update

# Install Python 3.11
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# Verify installation
python3.11 --version

# Recreate virtual environment with Python 3.11
cd ~/zerodha-algo-trader
sudo systemctl stop algo-trader
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Test
python --version
python -c "from core.trading_engine import scan_and_trade; print('✅ Imports OK')"

# Restart service
sudo systemctl restart algo-trader
sudo systemctl status algo-trader
```

---

## 🔍 **Verify the Upgrade**

After upgrading, verify everything works:

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate

# Check Python version
python --version

# Test imports (should have no warnings)
python login.py --help

# Test a dry run scan
python manage.py scan

# Check service logs
sudo journalctl -u algo-trader -f
```

---

## ⚠️ **Troubleshooting**

### **Issue: Still using Python 3.8**

```bash
# Make sure you're in the new venv
cd ~/zerodha-algo-trader
source venv/bin/activate
which python
# Should show: /home/ubuntu/zerodha-algo-trader/venv/bin/python

python --version
# Should show: Python 3.10.x or 3.11.x (NOT 3.8.x)
```

### **Issue: Cryptography deprecation warning**

If you still see the warning:

```
CryptographyDeprecationWarning: Python 3.8 is no longer supported
```

This means you're still using Python 3.8. Make sure you:

1. Deleted the old `venv` directory
2. Created a new one with `python3.10 -m venv venv`
3. Activated the new venv before running anything

### **Issue: Missing dependencies after upgrade**

```bash
cd ~/zerodha-algo-trader
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 📋 **Summary**

**Recommended approach for Ubuntu 22.04:**

- Use **Python 3.10** (comes pre-installed)
- Takes 2-3 minutes to switch
- No compatibility issues
- Fully supported until 2026

**For latest features:**

- Use **Python 3.11** (requires deadsnakes PPA)
- Takes 5-10 minutes to install
- Best performance
- Fully supported until 2027

**After upgrade:**

- No more type hint errors
- No cryptography warnings
- Better performance
- Native support for modern Python features
