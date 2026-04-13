# Order Flow Radar - Real-Time Trading Signal System

## Overview

A production-ready trading signal system with **ZERO mock data**. Real API data only. Discovers symbols dynamically, scans continuously, learns outcomes, and adjusts signal weights.

## Key Principles

- **Real Data Only**: No mock data, demo mode, or fake fallbacks. This is governed by the [AGENT_LAW.md](file:///C:/Users/timot/.gemini/antigravity/scratch/order-flow-radar/AGENT_LAW.md) which serves as the repository constitution.
- **Institutional Cadence**: Evaluation and alerts are performed on a 5-minute institutional window to ensure signal stability.
- **Dynamic Discovery**: Scan the entire market by fetching most-active symbols from APIs every hour.
- **Quality Filtering**: Only qualified signals (confluence score ≥ threshold) reach the dashboard and Discord.
- **Learning AI**: Tracks signal outcomes (TP1, TP2, SL) and adjusts confluence weights to improve future signals.

## Architecture

### 1. Market Scanner (`market_scanner.py`)

**Purpose**: Discovers tradeable symbols dynamically from live APIs.

**Methods**:
- `discover_equities()`: Fetch top 100 most-active US stocks from Alpaca screener + Polygon gainers/losers
- `discover_crypto()`: Get liquid crypto pairs from Alpaca (BTC/USD, ETH/USD, SOL/USD, etc.)
- `get_scan_targets()`: Combined list, cached for 1 hour
- `get_all_symbols()`: Returns all discoverable symbols

**No Hardcoded Lists**: Replaces old `scan_universe.py` completely. The system discovers what's tradeable, not a static watchlist.

### 2. Signal Learning (`signals/learner.py`)

**Purpose**: Tracks signal outcomes and learns which confluence factors work best.

**Key Features**:
- Persistent CSV journal: `signal_outcomes.csv` tracks every signal
- Dynamic weights: `learned_weights.json` stores weights per confluence factor
- Outcome tracking: Marks signals as TP1_HIT, TP2_HIT, LOSS, EXPIRED
- Auto-retraining: Adjusts weights based on win rates (every 24 hours or 50 closed signals)

**How It Works**:
1. When signal fires, record it: entry price, stops, confluences list
2. Every 5 minutes, check if current price hit TP1/TP2/SL
3. Update outcome status in CSV
4. Periodically (daily), retrain:
   - For each confluence factor, calculate win rate
   - If win rate > 60%, increase weight by 5%
   - If win rate < 40%, decrease weight by 10%
   - Clamp weights between 0.1 and 4.0

### 3. Confluence Engine (Updated)

**Dynamic Weights**: Now accepts weights from the learner instead of hardcoded values.

```python
confluence_engine.set_weights(learner.get_weights())
```

All scoring now uses learned weights. Over time, the system will naturally emphasize the factors that actually generate winning trades.

### 4. Orchestrator (`main.py`)

**Runs 5 concurrent async tasks**:

1. **Market Discovery** (every 1 hour):
   - Fetch fresh symbol list from APIs
   - Cache for 1 hour

2. **Continuous Scanning** (every 30-60 seconds):
   - For each discovered symbol, fetch real bars/quotes
   - Run all signal modules
   - Score with confluence engine (using learned weights)
   - If score ≥ threshold → send Discord + log to journal + record for learner

3. **Outcome Checker** (every 5 minutes):
   - Check all open signals against current prices
   - Update CSV: did signal hit TP1, TP2, or SL?
   - Learner uses this to calculate performance

4. **Learner Retraining** (every 24 hours):
   - Analyze all closed signals
   - Recalculate win rates per factor
   - Adjust weights
   - Update confluence engine

5. **FastAPI Server** (port 8080):
   - Dashboard UI
   - REST API endpoints
   - WebSocket for real-time updates

### 5. Server (`server.py`)

**Real Data Only**: All endpoints return error if data fetch fails (no fallback to fake data).

**Key Endpoints**:

- `GET /` - Dashboard HTML
- `GET /api/scan` - Equity scan (real data, current prices)
- `GET /api/scan/crypto` - Crypto scan
- `GET /api/analyze/{symbol}` - On-demand analysis (real data)
- `GET /api/signals/recent` - Historical signals from journal
- `GET /api/status` - System health + API status
- `GET /api/learner/weights` - Current learned weights
- `GET /api/learner/performance` - Win rates, outcomes breakdown
- `WS /ws` - Real-time signal stream (qualified signals only)

**No Watchlist**: Removed `/api/watchlist/*` endpoints. The scanner IS the system—it finds setups automatically.

### 6. Dashboard (`dashboard/index.html`)

**Layout**:

- **Top Bar**: Logo, search, system status, time
- **Left Panel**: Live Scanner Results
  - Shows all symbols currently meeting confluence threshold
  - Columns: Symbol, Price, Direction (LONG/SHORT), Score, Confluences, Time
  - Auto-refreshes every 30 seconds
  - Click row to expand (TODO: full trade card)

- **Right Sidebar**:
  - **Performance**: Total signals, closed signals, win rate, TP1/TP2/Loss breakdown
  - **Top Factors**: Most-weighted confluence factors by current learned weights
  - **System**: Mode (LIVE), threshold, last update time

**No Watchlist Panel**: Removed. Dashboard focuses entirely on scan results.

## Data Flow

```
Market Discovery (hourly)
    ↓
    Get symbols from Alpaca/Polygon APIs
    ↓
Continuous Scan Loop (every 30-60s)
    ↓
    For each symbol: fetch real bars/quotes
    ↓
    Run signals (orderflow, momentum, volume, trend, levels)
    ↓
    Score with confluence engine (using learned weights)
    ↓
    If score ≥ threshold:
        → Send Discord alert
        → Log to journal
        → Record for learner tracking
        → Push to WebSocket clients
    ↓
Outcome Checker (every 5 min)
    ↓
    For each open signal:
        Check if price hit TP1/TP2/SL
        Update signal status in CSV
    ↓
Learner Retraining (every 24h)
    ↓
    For each confluence factor:
        Calculate win rate from closed signals
        Adjust weight (increase if >60%, decrease if <40%)
    ↓
    Update confluence engine with new weights
```

## Configuration

All settings in `config.py` (loaded from environment variables):

- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` - Alpaca credentials
- `POLYGON_API_KEY` - Polygon API key
- `CONFLUENCE_MIN` - Minimum score threshold (default: 5.0)
- `SIGNAL_COOLDOWN_SECONDS` - Cooldown between signals (default: 600)
- Technical indicator periods (RSI, EMA, etc.)
- Risk management: ATR multipliers, R:R ratios

## Error Handling

**Core Rule**: If an API call fails, skip that symbol. Never fake data.

Example:
```python
try:
    bars = await fetch_real_bars(symbol)
    if not bars:
        continue  # Skip if no data
    # Process real data
except Exception:
    logger.error(f"Skipping {symbol}: API error")
    continue  # Skip on error
```

## Learning Example

Suppose over a week, you generate 100 signals:

1. System tracks all 100 signals until they close
2. Of the 50 that hit TP1/TP2, count which factors were present:
   - RSI Divergence: present in 35/50 winners → 70% win rate
   - Order Flow Imbalance: present in 40/50 winners → 80% win rate
   - MACD Crossover: present in 20/50 winners → 40% win rate

3. Retraining adjusts weights:
   - Order Flow Imbalance: 2.0 → 2.0 × 1.05 = 2.1 (boost, high win rate)
   - RSI Divergence: 2.0 → 2.0 × 1.05 = 2.1 (boost)
   - MACD Crossover: 1.0 → 1.0 × 0.90 = 0.9 (penalize, low win rate)

4. Next signals are evaluated with these new weights
5. Over time, the system converges to optimal weights for YOUR market conditions

## Running the System

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ALPACA_API_KEY=your_key
export ALPACA_SECRET_KEY=your_secret
export POLYGON_API_KEY=your_key
export DISCORD_WEBHOOK_URL=your_webhook
export CONFLUENCE_MIN=5.0

# Run
python main.py
```

Dashboard available at: `http://localhost:8080`

## Docker

```bash
docker build -t order-flow-radar .
docker run -e ALPACA_API_KEY=... -e ALPACA_SECRET_KEY=... -p 8080:8080 order-flow-radar
```

## Files

- `main.py` - Orchestrator, task scheduler
- `market_scanner.py` - Symbol discovery from live APIs
- `server.py` - FastAPI server, REST endpoints, WebSocket
- `signals/confluence.py` - Scoring engine (now with dynamic weights)
- `signals/learner.py` - Outcome tracking, weight learning, retraining
- `dashboard/index.html` - Real-time UI (scanner-focused)
- `config.py` - Configuration loader
- `requirements.txt` - Python dependencies
- `Dockerfile` - Container build

## Future Enhancements

1. Real API data integration (Alpaca bars, Polygon tickers, Alpha Vantage)
2. Options flow tracking (Schwab API)
3. Backtesting framework (test weights against historical data)
4. Multi-strategy support (enable/disable signal types per market)
5. Slack/Telegram alerts in addition to Discord
6. A/B testing framework (split signals, track A vs B performance)
