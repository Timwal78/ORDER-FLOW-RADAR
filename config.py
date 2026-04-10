"""
Configuration module for Order Flow Radar trading signal system.
Loads all settings from environment variables with sensible production defaults.
"""

import os
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Alpaca Credentials
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_CRYPTO_WS = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"
ALPACA_STOCK_DATA = "https://data.alpaca.markets/v2"

# Polygon Credentials
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_BASE = "https://api.polygon.io"

# Alpha Vantage Credentials
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"

# Schwab Credentials and OAuth
SCHWAB_APP_KEY = os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_REFRESH_TOKEN = os.getenv("SCHWAB_REFRESH_TOKEN", "")
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
SCHWAB_BASE = "https://api.schwabapi.com/marketdata/v1"

# Discord Webhooks (tiered channels)
DISCORD_WEBHOOK_FREE = os.getenv("DISCORD_WEBHOOK_FREE", "")
DISCORD_WEBHOOK_PRO = os.getenv("DISCORD_WEBHOOK_PRO", "")
DISCORD_WEBHOOK_PREMIUM = os.getenv("DISCORD_WEBHOOK_PREMIUM", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", DISCORD_WEBHOOK_PRO)  # legacy fallback

# Symbol Lists
_default_equities = ["AAPL", "TSLA", "NVDA", "SPY", "QQQ", "AMD", "AMZN", "META", "MSFT", "GOOGL"]
_default_crypto = ["BTC/USD", "ETH/USD"]

EQUITY_SYMBOLS: List[str] = os.getenv("EQUITY_SYMBOLS", ",".join(_default_equities)).split(",")
EQUITY_SYMBOLS = [s.strip() for s in EQUITY_SYMBOLS if s.strip()]

CRYPTO_SYMBOLS: List[str] = os.getenv("CRYPTO_SYMBOLS", ",".join(_default_crypto)).split(",")
CRYPTO_SYMBOLS = [s.strip() for s in CRYPTO_SYMBOLS if s.strip()]

# Polling Intervals (seconds)
EQUITY_POLL_SECONDS = int(os.getenv("EQUITY_POLL_SECONDS", "60"))
ALPHA_POLL_SECONDS = int(os.getenv("ALPHA_POLL_SECONDS", "300"))
SCHWAB_POLL_SECONDS = int(os.getenv("SCHWAB_POLL_SECONDS", "300"))

# Order Flow Parameters
WALL_SIZE_BTC = float(os.getenv("WALL_SIZE_BTC", "5.0"))  # BTC for crypto walls
WALL_SIZE_EQUITY = int(os.getenv("WALL_SIZE_EQUITY", "10000"))  # shares for equity walls
WALL_TIMEOUT_SECONDS = int(os.getenv("WALL_TIMEOUT_SECONDS", "30"))
SPOOF_TIMEOUT_SECONDS = int(os.getenv("SPOOF_TIMEOUT_SECONDS", "10"))

# Signal Thresholds
IMBALANCE_THRESHOLD = float(os.getenv("IMBALANCE_THRESHOLD", "0.15"))  # 15% imbalance
VOLUME_SPIKE_MULT = float(os.getenv("VOLUME_SPIKE_MULT", "2.5"))  # 2.5x volume spike
VOLUME_SMA_PERIOD = int(os.getenv("VOLUME_SMA_PERIOD", "20"))
VWAP_DEV_THRESHOLD = float(os.getenv("VWAP_DEV_THRESHOLD", "0.02"))  # 2% deviation from VWAP

# Technical Indicators
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERSOLD = int(os.getenv("RSI_OVERSOLD", "25"))
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", "75"))
EMA_FAST = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW = int(os.getenv("EMA_SLOW", "21"))
EMA_50 = int(os.getenv("EMA_50", "50"))
LEVEL_CLUSTER_THRESHOLD = float(os.getenv("LEVEL_CLUSTER_THRESHOLD", "0.003"))  # 0.3%

# Risk Management
DEFAULT_STOP_ATR_MULT = float(os.getenv("DEFAULT_STOP_ATR_MULT", "1.5"))  # 1.5x ATR
TP1_RR_RATIO = float(os.getenv("TP1_RR_RATIO", "1.5"))  # 1.5:1 risk/reward
TP2_RR_RATIO = float(os.getenv("TP2_RR_RATIO", "2.5"))  # 2.5:1 risk/reward

# Confluence and Signal Management
CONFLUENCE_MIN = float(os.getenv("CONFLUENCE_MIN", "5.0"))  # minimum signal weight for entry
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "600"))  # 10 min cooldown
SIGNAL_EXPIRY_MINUTES = int(os.getenv("SIGNAL_EXPIRY_MINUTES", "120"))  # signal valid for 2 hours

# Discord Alert Settings
DISCORD_MAX_RETRIES = int(os.getenv("DISCORD_MAX_RETRIES", "3"))
DISCORD_RATE_LIMIT = int(os.getenv("DISCORD_RATE_LIMIT", "5"))  # max 5 per minute

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def load_config() -> Dict:
    """Load configuration as a dictionary for signal modules."""
    return {
        # Order Flow Settings
        "WALL_SIZE": WALL_SIZE_EQUITY,
        "WALL_SIZE_BTC": WALL_SIZE_BTC,
        "WALL_TIMEOUT_SECONDS": WALL_TIMEOUT_SECONDS,
        "SPOOF_TIMEOUT_SECONDS": SPOOF_TIMEOUT_SECONDS,
        "IMBALANCE_THRESHOLD": IMBALANCE_THRESHOLD,

        # Momentum Settings
        "RSI_PERIOD": RSI_PERIOD,
        "RSI_OVERSOLD": RSI_OVERSOLD,
        "RSI_OVERBOUGHT": RSI_OVERBOUGHT,
        "VWAP_DEV_THRESHOLD": VWAP_DEV_THRESHOLD,

        # Volume Settings
        "VOLUME_SPIKE_MULT": VOLUME_SPIKE_MULT,
        "VOLUME_SMA_PERIOD": VOLUME_SMA_PERIOD,

        # Trend Settings
        "EMA_FAST": EMA_FAST,
        "EMA_SLOW": EMA_SLOW,
        "EMA_50": EMA_50,

        # Level Settings
        "LEVEL_CLUSTER_THRESHOLD": LEVEL_CLUSTER_THRESHOLD,

        # Confluence Settings
        "CONFLUENCE_MIN": CONFLUENCE_MIN,
        "SIGNAL_COOLDOWN_SECONDS": SIGNAL_COOLDOWN_SECONDS,

        # Discord Settings
        "DISCORD_WEBHOOK_URL": DISCORD_WEBHOOK_URL,
        "DISCORD_MAX_RETRIES": DISCORD_MAX_RETRIES,

        # Risk Management
        "DEFAULT_STOP_ATR_MULT": DEFAULT_STOP_ATR_MULT,
        "TP1_RR_RATIO": TP1_RR_RATIO,
        "TP2_RR_RATIO": TP2_RR_RATIO,

        # Signal Expiry
        "SIGNAL_EXPIRY_MINUTES": SIGNAL_EXPIRY_MINUTES,

        # API Keys (for data handlers)
        "ALPACA_API_KEY": ALPACA_API_KEY,
        "ALPACA_SECRET_KEY": ALPACA_SECRET_KEY,
        "POLYGON_API_KEY": POLYGON_API_KEY,
        "ALPHA_VANTAGE_KEY": ALPHA_VANTAGE_KEY,
        "SCHWAB_APP_KEY": SCHWAB_APP_KEY,
        "SCHWAB_APP_SECRET": SCHWAB_APP_SECRET,
        "SCHWAB_REFRESH_TOKEN": SCHWAB_REFRESH_TOKEN,

        # Discord Webhooks (tiered)
        "DISCORD_WEBHOOK_FREE": DISCORD_WEBHOOK_FREE,
        "DISCORD_WEBHOOK_PRO": DISCORD_WEBHOOK_PRO,
        "DISCORD_WEBHOOK_PREMIUM": DISCORD_WEBHOOK_PREMIUM,

        # Symbols
        "EQUITY_SYMBOLS": EQUITY_SYMBOLS,
        "CRYPTO_SYMBOLS": CRYPTO_SYMBOLS,

        # Polling
        "EQUITY_POLL_SECONDS": EQUITY_POLL_SECONDS,
        "ALPHA_POLL_SECONDS": ALPHA_POLL_SECONDS,
        "SCHWAB_POLL_SECONDS": SCHWAB_POLL_SECONDS,

        # Logging
        "LOG_LEVEL": LOG_LEVEL,
    }
