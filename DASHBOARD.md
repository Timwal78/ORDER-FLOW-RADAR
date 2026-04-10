# Order Flow Radar Web Dashboard & Scanner API

## Overview

The web dashboard and scanner API add a real-time, browser-based interface to the Order Flow Radar trading system. Users can search any stock/crypto symbol on-demand, scan for setups meeting confluence thresholds, and maintain a watchlist with live updates.

## Architecture

### Components

1. **server.py** - FastAPI web server with REST API and WebSocket endpoints
2. **dashboard/index.html** - Single-page dark-themed trading UI
3. **scan_universe.py** - Categorized stock/crypto ticker universes for scanning
4. **main.py** - Updated to run FastAPI server in background thread alongside async engine

### Ports

- **8080** - Web dashboard and REST API (http://localhost:8080)
- Signal engine continues running on the main async event loop

## Features

### 1. Search Bar (Primary Feature)

Type any symbol and hit Enter or click search:
- **Crypto**: BTC/USD, ETH/USD, SOL/USD (contains "/")
- **Equities**: AAPL, MSFT, NVDA, etc.
- **ETFs**: SPY, QQQ, IWM

Autocomplete suggestions for popular tickers.

When a symbol is analyzed:
1. Data is fetched from configured providers (Alpaca, Polygon, etc.)
2. All signal modules run: orderflow, momentum, volume, trend, levels
3. Confluence scoring combines signals
4. Trade card is generated if score meets threshold
5. Results displayed with full breakdown

### 2. Scanner

**Top Setups Panel** - Auto-refreshing every 60 seconds

Scans two universes:
- **Equity Universe**: S&P 500 top 50 + popular day-trade stocks + meme stocks + ETFs (~100 tickers)
- **Crypto Universe**: 15 popular crypto pairs

Features:
- **5-minute cache** to respect API rate limits
- **Rotating batch scanning** to avoid blasting all symbols at once
- **Background updates** - cache returns immediately, new results update in background
- Results sorted by confluence score descending
- Click any row to run full analysis

### 3. Watchlist

Add symbols for continuous monitoring:
- Maintains live scores via WebSocket
- Displays current score, direction, price
- Remove button for quick cleanup
- Symbols push real-time updates to dashboard

### 4. Recent Signals

Displays last 50 signals from the signal journal (CSV):
- Symbol, direction, entry/stops/targets
- Confluence count and alert level
- Timestamps for signal timing analysis

### 5. System Status

Top bar indicators show:
- Data feed connectivity (Alpaca, Polygon, Schwab)
- Current time
- System uptime
- Connected WebSocket clients

## API Endpoints

### REST API

```
GET  /                              # Serve dashboard HTML
GET  /api/analyze/{symbol}          # Analyze symbol on-demand
GET  /api/scan                      # Scan equity universe
GET  /api/scan/crypto               # Scan crypto universe
GET  /api/watchlist                 # Get current watchlist
POST /api/watchlist/add             # Add symbol to watchlist
POST /api/watchlist/remove          # Remove symbol from watchlist
GET  /api/signals/recent            # Get last 50 signals from journal
GET  /api/status                    # System health status
```

### WebSocket

```
WS   /ws                            # Real-time updates
```

Subscribe to symbol updates via WebSocket:
```javascript
ws.send('subscribe:AAPL');
```

Receive updates:
```javascript
{
  "type": "symbol_analyzed",
  "symbol": "AAPL",
  "score": 7.5,
  "direction": "long"
}
```

## Setup & Running

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the System

```bash
python main.py
```

This starts:
- FastAPI web server (port 8080)
- Async signal engine (background)
- WebSocket server for live updates

### 3. Access Dashboard

Open browser to: **http://localhost:8080**

Or on mobile: **http://<your-ip>:8080**

### 4. Docker

```bash
docker build -t order-flow-radar .
docker run -p 8080:8080 -e ALPACA_API_KEY=... order-flow-radar
```

## Configuration

Key settings in `config.py`:

```python
CONFLUENCE_MIN = 5.0              # Min score for trade cards
SIGNAL_COOLDOWN_SECONDS = 600     # Cooldown between signals per symbol
VOLUME_SPIKE_MULT = 2.5           # Volume spike multiplier
RSI_OVERSOLD = 30                 # RSI oversold threshold
RSI_OVERBOUGHT = 70               # RSI overbought threshold
```

Scanner caching:
- **5-minute cache** for scan results
- **Rotating batch of 10** symbols per scan request to avoid rate limits
- Click "Top Setups" to trigger immediate rescan

## UI Features

### Dark Trading Theme

- Black/charcoal background (#0a0e27)
- Green (#00d4aa) for longs / Red (#ff4757) for shorts
- Monospace fonts for prices and scores
- Professional trading card layouts

### Responsive Design

- Desktop: Full 3-column layout (search results, scanner, watchlist)
- Tablet: 2-column with sidebar below
- Mobile: Single column, accordion-style panels

### Real-time Updates

- WebSocket connection maintains live watchlist scores
- Scan results auto-refresh every 60 seconds
- Status indicators for feed connectivity
- Live clock in top bar

## Signal Breakdown

Each analysis shows:

### Individual Signals
- **Orderflow**: Imbalances, walls, absorption, spoofing
- **Momentum**: RSI, MACD, VWAP, divergences
- **Volume**: Spikes, climaxes, CVD divergences
- **Trend**: EMA crossovers, multi-timeframe alignment
- **Levels**: Support/resistance, price clustering

### Confluence Scoring

Score points by signal:
- Order Flow Imbalance: +2.0
- Wall (non-spoof): +1.5
- Absorption: +2.0
- RSI Oversold/Overbought: +1.5
- RSI Divergence: +2.0
- MACD Crossover: +1.0
- VWAP Mean Reversion: +1.5
- Volume Spike: +1.0
- CVD Divergence: +1.5
- EMA Crossover: +1.0
- Multi-TF Alignment: +2.0
- Support/Resistance: +1.5

**Maximum Score**: 20.0 points

### Trade Card (if score >= CONFLUENCE_MIN)

Generated when threshold is met:
- **Entry**: Current price
- **Stop Loss**: 1.0x ATR below entry (long) or above (short)
- **TP1**: 2.0x ATR above entry (long) - ~1.5:1 R:R
- **TP2**: 3.5x ATR above entry (long) - ~2.5:1 R:R
- **Alert Level**: FIRE (score >= 9), GO (>= 7), WARNING

## Scanner Universe

### scan_universe.py

Provides four functions:

```python
get_equity_universe()     # ~130 tickers (S&P 500 top 50 + popular + meme)
get_crypto_universe()     # 15 crypto pairs
get_full_universe()       # All symbols
is_crypto_symbol(symbol)  # Detect if "/"  in symbol
get_sector(symbol)        # Map to sector (tech, energy, etc.)
```

Categorized lists:
- **SP500_TOP_50**: Market cap leaders
- **POPULAR_DAYTRADE**: High volatility trades
- **CRYPTO_PAIRS**: Major pairs
- **MEME_STOCKS**: GME, AMC, BBIG, etc.
- **ETFS**: SPY, QQQ, IWM, etc.
- **SECTOR_LEADERS**: Tech, energy, finance, healthcare, consumer, industrial

## Data Integration

### Current Implementation

Server.py includes mock data structures. In production, connect to:

1. **Alpaca** (equities & crypto)
   - Historical bars via REST
   - Real-time WebSocket streams

2. **Polygon** (equities)
   - Bars, snapshots, trade ticks
   - Option chains

3. **Schwab** (options)
   - Option chain data
   - Greeks, implied volatility

4. **Alpha Vantage** (technical fallback)
   - Slow but free tier available

### Implementation Steps

1. Replace mock data in `/api/analyze/{symbol}` with real API calls
2. Cache bars data (1min, 5min, 1hr, 1day) for quick access
3. Subscribe to WebSocket streams for watchlist symbols
4. Update scan_cache with real confluence scores

## Monitoring & Logging

Dashboard logs to terminal:
- Symbol analyses
- Scan operations
- WebSocket connections/disconnections
- Confluence scores
- Trade card generation

Enable debug logging in main.py:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Known Limitations

1. **API Rate Limiting**: Scanner rotates through 10 symbols per request to avoid hitting Alpaca/Polygon rate limits
2. **Data Latency**: Demo uses mock data - production needs real feed integration
3. **Cooldown**: Signal cooldown (default 10 min) prevents rapid re-entry on same symbol
4. **Browser Support**: Modern browsers with ES6 support (Chrome, Firefox, Safari 11+)

## Future Enhancements

1. **Backtesting**: Run historical analysis on past signals
2. **P&L Tracking**: Link filled trades to signals, calculate P&L
3. **Alerts**: Email, SMS, Telegram notifications
4. **Multi-Account**: Support multiple Alpaca/Schwab accounts
5. **Advanced Charts**: TradingView Lightweight Charts integration
6. **Custom Universes**: User-defined watchlists and scan universes
7. **Machine Learning**: Predict confluence threshold adjustments
8. **Market Profile**: Volume profile & order book visualization

## Support & Debugging

### WebSocket Won't Connect

Check:
```bash
# Terminal should show "WebSocket connected"
# Check browser console for connection errors
# Verify http://localhost:8080 is accessible
```

### Symbols Not Analyzing

- Check API credentials in .env
- Verify ALPACA_API_KEY and POLYGON_API_KEY are set
- Check terminal for error messages

### Dashboard Slow

- Clear browser cache
- Reduce max_results in scanner
- Check scan_cache status via `/api/status`

### Building from Source

```bash
# Install dev dependencies
pip install -r requirements.txt
pip install pytest black flake8

# Format code
black server.py scan_universe.py

# Run tests
pytest tests/

# Start dev server with auto-reload
uvicorn server:app --reload --host 0.0.0.0 --port 8080
```
