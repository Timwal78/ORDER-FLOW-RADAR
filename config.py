"""
Order Flow Radar™ — Configuration
ScriptMasterLabs™

LAW 2 COMPLIANCE: ALL weights, thresholds, and constants defined here
with explicit quantitative justification labels.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Build Identification (v1.2 Hardening)
SYSTEM_VERSION = "Inst-v1.2"

# =============================================================================
# API KEYS — All from .env. No defaults. No fakes.
# =============================================================================
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_API_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
POLYGON_API_KEY   = os.getenv("POLYGON_API_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

SCHWAB_APP_KEY       = os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET    = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_REFRESH_TOKEN = os.getenv("SCHWAB_REFRESH_TOKEN", "")
SCHWAB_REDIRECT_URI  = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

DISCORD_WEBHOOK_FREE    = os.getenv("DISCORD_WEBHOOK_FREE", "")
DISCORD_WEBHOOK_PRO     = os.getenv("DISCORD_WEBHOOK_PRO", "")
DISCORD_WEBHOOK_PREMIUM = os.getenv("DISCORD_WEBHOOK_PREMIUM", "")

TWITTER_API_KEY        = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET     = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN   = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET  = os.getenv("TWITTER_ACCESS_SECRET", "")

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

# =============================================================================
# SCANNER / UNIVERSE SETTINGS  (Law 2: labeled, config-driven)
# =============================================================================
# Always-scan: tickers monitored regardless of discovery results
# Institutional Safety Net: SPY, QQQ, IWM added to ensure radar is never empty.
ALWAYS_SCAN = [
    s.strip().upper()
    for s in os.getenv("ALWAYS_SCAN", "AMC,GME,SPY,QQQ,IWM").split(",")
    if s.strip()
]

# Market cap filters
MIN_MARKET_CAP  = float(os.getenv("MIN_MARKET_CAP", "100e6"))   # Exclude sub-100M penny noise
LARGE_CAP_CEILING = float(os.getenv("LARGE_CAP_CEILING", "2e12"))  # Cap at 2T; top 3 mega caps shown per Manifesto Rule 3

# Universe refresh cadence
# Polygon Free Tier: 5 calls/min limit. 
# Selection: 60s refresh = 3 calls/min (gainers, losers, screener), leaving headroom.
UNIVERSE_REFRESH_SECONDS = int(os.getenv("UNIVERSE_REFRESH_SECONDS", "60"))

# Memory & State Safety (15 min TTL, 2 min Stale)
TICKER_TTL_SECONDS      = int(os.getenv("TICKER_TTL_SECONDS", "900"))
STALE_THRESHOLD_SECONDS = int(os.getenv("STALE_THRESHOLD_SECONDS", "120"))

# =============================================================================
# CONFLUENCE SCORING WEIGHTS  (Law 2: labeled with justification)
# =============================================================================
# CVD_BOOST_FACTOR: Multiplier applied when cumulative volume delta confirms price direction
# Justification: Aligned institutional flow = higher probability of continuation
CVD_BOOST_FACTOR = float(os.getenv("CVD_BOOST_FACTOR", "1.3"))

# LARGE_TRADE_WEIGHT: Score weight for individual trades > LARGE_TRADE_THRESHOLD shares
# Justification: Block trades signal institutional accumulation/distribution
LARGE_TRADE_WEIGHT = float(os.getenv("LARGE_TRADE_WEIGHT", "0.4"))

# LARGE_TRADE_THRESHOLD: Minimum shares to classify a trade as a block trade
# Justification: 10k shares is the standard institutional print threshold
LARGE_TRADE_THRESHOLD = int(os.getenv("LARGE_TRADE_THRESHOLD", "10000"))

# SPREAD_PENALTY_MULT: Score deduction per percentage point of bid-ask spread
# Justification: Wide spreads reduce fill quality and signal reliability
SPREAD_PENALTY_MULT = float(os.getenv("SPREAD_PENALTY_MULT", "50.0"))

# RSI_OVERSOLD / RSI_OVERBOUGHT: Momentum signal thresholds
RSI_OVERSOLD  = float(os.getenv("RSI_OVERSOLD", "30.0"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "70.0"))

# MOMENTUM_EMA_FAST / SLOW: EMA periods for trend detection
MOMENTUM_EMA_FAST = int(os.getenv("MOMENTUM_EMA_FAST", "9"))
MOMENTUM_EMA_SLOW = int(os.getenv("MOMENTUM_EMA_SLOW", "21"))

# MIN_CONFLUENCE_SCORE: Signals below this score are discarded (not shown, not alerted)
# Justification: Quality gate — eliminates noise signals
MIN_CONFLUENCE_SCORE = float(os.getenv("MIN_CONFLUENCE_SCORE", "60.0"))

# =============================================================================
# SIGNAL TIMING  (Law 3: institutional cadence)
# =============================================================================
# SIGNAL_EVAL_INTERVAL: How often to evaluate all states for signals
# Institutional Fast Cadence: 60 seconds (1 minute resolution)
SIGNAL_EVAL_INTERVAL = int(os.getenv("SIGNAL_EVAL_INTERVAL", "60"))

# SIGNAL_COOLDOWN: Minimum seconds between repeated signals for same ticker
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", "300"))

# REST_SNAPSHOT_INTERVAL: How often to poll Alpaca REST snapshots
# Alpaca Free Tier: 200 requests/min. 10s is very safe.
REST_SNAPSHOT_INTERVAL = int(os.getenv("REST_SNAPSHOT_INTERVAL", "10"))

# SWEEP_SCAN_INTERVAL: Institutional sweep scan cadence
SWEEP_SCAN_INTERVAL = int(os.getenv("SWEEP_SCAN_INTERVAL", "600"))

# =============================================================================
# OPTIONS ENGINE SETTINGS
# =============================================================================
# ATR multipliers for stop-loss and take-profit calculations
ATR_STOP_MULT = float(os.getenv("ATR_STOP_MULT", "1.5"))  # 1.5x ATR below entry
ATR_TP1_MULT  = float(os.getenv("ATR_TP1_MULT", "2.0"))   # 2:1 R:R minimum
ATR_TP2_MULT  = float(os.getenv("ATR_TP2_MULT", "3.0"))   # 3:1 R:R extended

# Preferred options DTE range
PREFERRED_DTE_MIN = int(os.getenv("PREFERRED_DTE_MIN", "7"))
PREFERRED_DTE_MAX = int(os.getenv("PREFERRED_DTE_MAX", "30"))

# Preferred delta range for options selection
PREFERRED_DELTA_MIN = float(os.getenv("PREFERRED_DELTA_MIN", "0.25"))
PREFERRED_DELTA_MAX = float(os.getenv("PREFERRED_DELTA_MAX", "0.70"))

MAX_OPTIONS_RESULTS = int(os.getenv("MAX_OPTIONS_RESULTS", "3"))

# =============================================================================
# DISCORD DELIVERY DELAYS
# =============================================================================
DISCORD_PREMIUM_DELAY_SECONDS = int(os.getenv("DISCORD_PREMIUM_DELAY_SECONDS", "0"))   # Immediate
DISCORD_PRO_DELAY_SECONDS     = int(os.getenv("DISCORD_PRO_DELAY_SECONDS", "120"))     # 2 min
DISCORD_FREE_DELAY_SECONDS    = int(os.getenv("DISCORD_FREE_DELAY_SECONDS", "1800"))   # 30 min

# =============================================================================
# LEARNER / ADAPTIVE WEIGHTS
# =============================================================================
LEARNER_RETRAIN_INTERVAL_HOURS    = int(os.getenv("LEARNER_RETRAIN_INTERVAL_HOURS", "24"))
LEARNER_MIN_SIGNALS_FOR_RETRAIN   = int(os.getenv("LEARNER_MIN_SIGNALS_FOR_RETRAIN", "50"))
LEARNER_WIN_RATE_BOOST_THRESHOLD  = float(os.getenv("LEARNER_WIN_RATE_BOOST_THRESHOLD", "0.60"))
LEARNER_WIN_RATE_PENALTY_THRESHOLD = float(os.getenv("LEARNER_WIN_RATE_PENALTY_THRESHOLD", "0.40"))
LEARNER_BOOST_FACTOR              = float(os.getenv("LEARNER_BOOST_FACTOR", "1.05"))
LEARNER_PENALTY_FACTOR            = float(os.getenv("LEARNER_PENALTY_FACTOR", "0.90"))
LEARNER_WEIGHT_MIN                = float(os.getenv("LEARNER_WEIGHT_MIN", "0.10"))
LEARNER_WEIGHT_MAX                = float(os.getenv("LEARNER_WEIGHT_MAX", "4.00"))

# =============================================================================
# SWEEP SCANNER THRESHOLDS
# =============================================================================
# SWEEP_MIN_PREMIUM: Minimum options premium (in $) to flag as institutional sweep
SWEEP_MIN_PREMIUM    = float(os.getenv("SWEEP_MIN_PREMIUM", "50000.0"))   # $50k minimum institutional print
SWEEP_MIN_BLOCK_SIZE = int(os.getenv("SWEEP_MIN_BLOCK_SIZE", "10000"))    # Block trade threshold (shares)

# =============================================================================
# DASHBOARD
# =============================================================================
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
LOG_LEVEL      = os.getenv("LOG_LEVEL", "INFO")

# =============================================================================
# DATA PATHS (Runtime artifacts — not source code)
# =============================================================================
import os as _os
_BASE = _os.path.dirname(_os.path.abspath(__file__))
SIGNAL_DATA_DIR     = _os.path.join(_BASE, "signal_data")
JOURNAL_CSV_PATH    = _os.path.join(SIGNAL_DATA_DIR, "signal_outcomes.csv")
LEARNED_WEIGHTS_PATH = _os.path.join(SIGNAL_DATA_DIR, "learned_weights.json")
_os.makedirs(SIGNAL_DATA_DIR, exist_ok=True)
