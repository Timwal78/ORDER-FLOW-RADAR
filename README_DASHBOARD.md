# Order Flow Radar - Web Dashboard & Scanner API

Complete web interface and REST API for the Order Flow Radar trading signal system.

## Quick Start

Start the system with one command:

```bash
python main.py
```

Then open your browser to: **http://localhost:8080**

That's it! The dashboard is ready to use.

## Documentation

### For Users
- **[QUICKSTART.md](QUICKSTART.md)** - 30-second setup and basic usage
- **[DASHBOARD.md](DASHBOARD.md)** - Complete feature documentation and API reference

### For Developers
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Technical overview of what was built
- **[server.py](server.py)** - FastAPI application (well-commented)
- **[scan_universe.py](scan_universe.py)** - Ticker universe definitions

### Dashboard UI
- **[dashboard/index.html](dashboard/index.html)** - Single-page web UI (HTML/CSS/JavaScript)

## What's New

### 1. Search Bar
Type any symbol and search on-demand:
- Stocks: AAPL, MSFT, NVDA
- Crypto: BTC/USD, ETH/USD, SOL/USD
- ETFs: SPY, QQQ, IWM

Autocomplete provides suggestions for popular tickers.

### 2. Symbol Analysis
Instant analysis shows:
- Current price and ATR
- Confluence score (0-20 scale)
- All signal breakdowns with bias indicators
- Trade card with entry, stops, targets, R:R
- Alert level (WARNING, GO, FIRE)

### 3. Scanner
"Top Setups" panel auto-refreshes every 60 seconds:
- Scans ~130 equity symbols and 15 crypto pairs
- Shows symbols meeting confluence threshold
- Cached results (5 min) prevent API rate limiting
- Click any row to analyze

### 4. Watchlist
Add symbols for continuous monitoring:
- Real-time score updates via WebSocket
- Display current direction and price
- One-click remove

### 5. Web UI
Production-ready dark trading theme:
- Black/charcoal background
- Green for longs, red for shorts
- Monospace fonts for prices
- Mobile-responsive design
- Works on phone, tablet, desktop

## Architecture

```
Browser Dashboard (HTML/CSS/JS)
         ↓ HTTP + WebSocket
    FastAPI Server (port 8080)
         ↓ Imports
    Signal Modules (orderflow, momentum, volume, trend, levels, confluence)
         ↓
    Config + Data Providers (Alpaca, Polygon, Schwab)
```

The FastAPI server runs in a background thread while the main async engine continues operating.

## API Endpoints

**Dashboard:**
- `GET /` - Serve dashboard HTML

**Analysis:**
- `GET /api/analyze/{symbol}` - Analyze any symbol
- `GET /api/scan` - Scan equity universe
- `GET /api/scan/crypto` - Scan crypto universe

**Watchlist:**
- `GET /api/watchlist` - Get current watchlist
- `POST /api/watchlist/add` - Add symbol
- `POST /api/watchlist/remove` - Remove symbol

**Data:**
- `GET /api/signals/recent` - Last 50 signals
- `GET /api/status` - System health

**Real-time:**
- `WS /ws` - WebSocket for live updates

Full API docs in [DASHBOARD.md](DASHBOARD.md#api-endpoints).

## Features

✅ **Search bar** with autocomplete  
✅ **On-demand analysis** for any symbol  
✅ **Automated scanner** finding best setups  
✅ **Live watchlist** with WebSocket updates  
✅ **Trade cards** with entry/stops/targets  
✅ **Confluence scoring** (0-20 scale)  
✅ **Signal breakdown** showing contributing factors  
✅ **Mobile responsive** dark UI  
✅ **Rate limiting** via caching  
✅ **Professional design** ready for trading  

## Configuration

Key settings in `config.py`:

```python
CONFLUENCE_MIN = 5.0              # Min score for trade signals
SIGNAL_COOLDOWN_SECONDS = 600     # Prevent rapid re-entry
VOLUME_SPIKE_MULT = 2.5           # Volume threshold
RSI_OVERSOLD = 30                 # RSI extreme threshold
RSI_OVERBOUGHT = 70
```

## Deployment

### Local Development
```bash
python main.py
# http://localhost:8080
```

### Docker
```bash
docker build -t order-flow-radar .
docker run -p 8080:8080 \
  -e ALPACA_API_KEY=... \
  -e POLYGON_API_KEY=... \
  order-flow-radar
```

### Cloud
Works on AWS, GCP, Azure, or any host with Python 3.11+.

## Data & Signals

### Confluence Scoring

Combines 13 signal types:

| Signal | Points |
|--------|--------|
| Order Flow Imbalance | +2.0 |
| Orderflow Wall | +1.5 |
| Volume Absorption | +2.0 |
| RSI Extreme | +1.5 |
| RSI Divergence | +2.0 |
| MACD Crossover | +1.0 |
| VWAP Deviation | +1.5 |
| Volume Spike | +1.0 |
| CVD Divergence | +1.5 |
| EMA Crossover | +1.0 |
| Multi-TF Alignment | +2.0 |
| Support/Resistance | +1.5 |

**Max Score: 20.0 points**

### Alert Levels
- **Score 5-7**: WARNING
- **Score 7-9**: GO
- **Score 9+**: FIRE

### Trade Card
When score >= CONFLUENCE_MIN (default 5.0):
- Entry: Current price
- Stop Loss: 1.0x ATR
- TP1: 2.0x ATR (~1.5:1 R:R)
- TP2: 3.5x ATR (~2.5:1 R:R)

## Files

### New Files
- `server.py` - FastAPI server (650+ lines)
- `scan_universe.py` - Ticker universes (130+ lines)
- `dashboard/index.html` - Web UI (1000+ lines)
- `DASHBOARD.md` - Full documentation
- `QUICKSTART.md` - Quick start guide
- `IMPLEMENTATION_SUMMARY.md` - Technical overview

### Modified Files
- `main.py` - Now starts FastAPI in background thread
- `requirements.txt` - Added fastapi, uvicorn
- `Dockerfile` - Exposed port 8080

## Troubleshooting

**Dashboard won't load:**
- Check terminal for "Starting FastAPI web server"
- Verify http://localhost:8080 is accessible
- Try: `pip install fastapi uvicorn`

**Symbols show no score:**
- That's normal with mock data
- Add API keys to .env for real analysis:
  ```
  ALPACA_API_KEY=your_key
  POLYGON_API_KEY=your_key
  ```

**WebSocket says "Disconnected":**
- Temporary, auto-reconnects in 3 seconds
- Check network connection
- Refresh browser if stuck

See [DASHBOARD.md](DASHBOARD.md) for complete troubleshooting.

## Next Steps

1. **Start the system**: `python main.py`
2. **Open dashboard**: http://localhost:8080
3. **Try searching**: Type "AAPL" and hit Enter
4. **Add to watchlist**: Click "+ Add Symbol"
5. **Add API keys**: Set credentials in .env for real data
6. **Deploy**: Use Docker for production

## Support

- **Questions?** Check [QUICKSTART.md](QUICKSTART.md)
- **Need details?** Read [DASHBOARD.md](DASHBOARD.md)
- **Technical?** See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
- **Code issues?** Check [server.py](server.py) comments

---

Built with FastAPI, Chart.js, and your existing signal modules.  
Ready for production. Just add API credentials and deploy.
