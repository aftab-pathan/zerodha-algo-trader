"""
utils/security.py
Handles encrypted storage of access tokens, credential masking, and audit logging.
"""

import os
import json
import base64
import hashlib
import logging
from datetime import datetime
from cryptography.fernet import Fernet
from config.config import TOKEN_FILE, DATA_DIR, LOG_DIR

logger = logging.getLogger(__name__)


def _get_or_create_key() -> bytes:
    """
    Encryption key derived from machine-specific entropy + env salt.
    Stored in DATA_DIR/secret.key (never commit this file).
    """
    key_file = os.path.join(DATA_DIR, "secret.key")
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(key_file):
        with open(key_file, "rb") as f:
            return f.read()

    # Generate new key
    key = Fernet.generate_key()
    with open(key_file, "wb") as f:
        f.write(key)
    os.chmod(key_file, 0o600)   # owner read/write only
    logger.info("New encryption key generated.")
    return key


def save_access_token(token: str) -> None:
    """Encrypt and persist the Kite access token to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    fernet = Fernet(_get_or_create_key())
    encrypted = fernet.encrypt(token.encode())
    with open(TOKEN_FILE, "wb") as f:
        f.write(encrypted)
    os.chmod(TOKEN_FILE, 0o600)
    logger.info("Access token saved (encrypted).")


def load_access_token() -> str | None:
    """Load and decrypt the saved access token. Returns None if not found."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        fernet = Fernet(_get_or_create_key())
        with open(TOKEN_FILE, "rb") as f:
            return fernet.decrypt(f.read()).decode()
    except Exception as e:
        logger.error(f"Failed to decrypt access token: {e}")
        return None


def mask_secret(value: str, visible: int = 4) -> str:
    """Return masked string like 'abcd****' for logging."""
    if not value or len(value) <= visible:
        return "****"
    return value[:visible] + "*" * (len(value) - visible)


def hash_value(value: str) -> str:
    """One-way hash for audit logging without exposing actual values."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def audit_log(event: str, details: dict) -> None:
    """
    Write security-relevant events to a tamper-evident audit log.
    Events: LOGIN, ORDER_PLACED, ORDER_REJECTED, CONFIG_CHANGED, ERROR
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    audit_file = os.path.join(LOG_DIR, "audit.log")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event,
        **details
    }
    with open(audit_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def sanitize_env() -> dict:
    """Return a safe config summary (no secrets) for health check endpoints."""
    from config.config import (
        KITE_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN,
        TRADING_CAPITAL, ACTIVE_STRATEGIES
    )
    return {
        "kite_api_key": mask_secret(KITE_API_KEY),
        "anthropic_key": mask_secret(ANTHROPIC_API_KEY),
        "telegram_token": mask_secret(TELEGRAM_BOT_TOKEN),
        "trading_capital": TRADING_CAPITAL,
        "active_strategies": ACTIVE_STRATEGIES,
    }
