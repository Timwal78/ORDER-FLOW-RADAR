import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# API KEYS — All from .env, no defaults, strictly real-time keys
# =============================================================================
SCHWAB_APP_KEY = os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_REFRESH_TOKEN = os.getenv("SCHWAB_REFRESH_TOKEN", "")
SCHWAB_REDIRECT_URI = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_RATE_LIMIT = float(os.getenv("POLYGON_RATE_LIMIT", "0"))  # Set to 0 if paid, or 12.5 if free tier

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_API_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# =============================================================================
# SCANNER SETTINGS
# =============================================================================
# Large-cap filter: skip tickers with market cap > this (avoids AAPL/MSFT/GOOG flood)
# Relying on alert throttle in sweep_scanner instead of hard exclusion.
LARGE_CAP_CEILING = float(os.getenv("LARGE_CAP_CEILING", "2e12"))  # 2T default (includes NVDA/AMZN/META)
# Min market cap to avoid penny stock noise
MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "100e6"))  # 100M min
# Always-scan tickers regardless of cap filters
ALWAYS_SCAN = [s.strip().upper() for s in os.getenv("ALWAYS_SCAN", "AMC,GME").split(",") if s.strip()]

# Scan intervals (seconds)
OPTIONS_SCAN_INTERVAL = int(os.getenv("OPTIONS_SCAN_INTERVAL", "120"))  # 2 min
EQUITY_POLL_INTERVAL = int(os.getenv("EQUITY_POLL_INTERVAL", "60"))
ALPHA_VANTAGE_INTERVAL = int(os.getenv("ALPHA_VANTAGE_INTERVAL", "300"))
SIGNAL_EVAL_INTERVAL = int(os.getenv("SIGNAL_EVAL_INTERVAL", "60"))

# Confluence scoring & Alpha Factors (Institutional Weights)
MIN_CONFLUENCE_SCORE = float(os.getenv("MIN_CONFLUENCE_SCORE", "60.0"))
CVD_BOOST_FACTOR = float(os.getenv("CVD_BOOST_FACTOR", "1.3")) # Standard confirmation weight
NEUTRAL_TAPE_BOOST = float(os.getenv("NEUTRAL_TAPE_BOOST", "1.1")) # SIDOT (Sideways Detection)
LARGE_TRADE_WEIGHT = float(os.getenv("LARGE_TRADE_WEIGHT", "0.4")) # Influence of blocks
SPREAD_PENALTY_MULT = float(os.getenv("SPREAD_PENALTY_MULT", "50.0")) # Liquidity penalty
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", "600")) # 10 min

# Options recommendation
PREFERRED_DTE_MIN = int(os.getenv("PREFERRED_DTE_MIN", "7"))
PREFERRED_DTE_MAX = int(os.getenv("PREFERRED_DTE_MAX", "30"))
PREFERRED_DELTA_MIN = float(os.getenv("PREFERRED_DELTA_MIN", "0.25"))
PREFERRED_DELTA_MAX = float(os.getenv("PREFERRED_DELTA_MAX", "0.70"))
MAX_OPTIONS_RESULTS = int(os.getenv("MAX_OPTIONS_RESULTS", "3"))

# Web dashboard
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
