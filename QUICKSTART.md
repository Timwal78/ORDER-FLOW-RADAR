# Quick Start Guide - Order Flow Radar Dashboard

## 30-Second Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set API keys in .env (optional for demo)
# ALPACA_API_KEY=...
# POLYGON_API_KEY=...

# 3. Start the system
python main.py

# 4. Open browser
# http://localhost:8080
```

That's it! You should see the dashboard immediately.

## First Steps

### 1. Search for a Symbol

In the search bar at the top:
- Type **BTC/USD** (crypto)
- Type **AAPL** (stock)
- Type **SPY** (ETF)

Press Enter or click the search icon.

### 2. View the Analysis

You'll see:
- **Current price** in the top left
- **Score gauge** showing confluence score (0-20)
- **Signal breakdown** - all factors contributing to the score
- **Trade card** (if score >= 5.0) with entry, stop, targets

### 3. Add to Watchlist

If you like a symbol, click the **+ Add Symbol** button in the right sidebar.

The symbol will appear in your watchlist and get live score updates via WebSocket.

### 4. Check Top Setups

The "🔍 Top Setups" panel shows the best equity signals right now.

Click any row to instantly analyze that symbol.

## What Each Section Shows

### Search Results (Left Panel)

**Score Gauge**
- 0-20 scale
- Green = strong long signal
- Red = strong short signal
- Orange = neutral/mixed

**Signal Breakdown**
- Each factor contributing points
- Green dot = bullish
- Red dot = bearish
- Orange dot = neutral

**Trade Card** (if applicable)
- Entry price (current)
- Stop loss (exit if wrong)
- TP1 & TP2 (profit targets)
- Risk/reward ratios

### Top Setups (Lower Left)

Automatically scans ~100 popular stocks and crypto every 60 seconds.

Shows symbols with best confluence scores.

Click any to analyze.

### Watchlist (Right Sidebar)

Your tracked symbols with live scores.

Click symbol to analyze. Click ✕ to remove.

### Status Bar (Top)

Green dots = connected data feeds.

Shows current time and system status.

## Commands & Features

### Search Bar Autocomplete

Start typing a symbol:
- Suggestions appear
- Press Enter or click suggestion
- Search executes

Popular suggestions:
- Crypto: BTC/USD, ETH/USD, SOL/USD
- Stocks: AAPL, MSFT, NVDA, TSLA, GOOGL
- ETFs: SPY, QQQ, IWM

### Watchlist Management

**Add Symbol**
- Type symbol in search bar
- Click "+ Add Symbol" button
- Symbol joins watchlist

**Remove Symbol**
- Click ✕ on watchlist item
- Symbol removed instantly

**View Updates**
- Live score changes via WebSocket
- Refreshes automatically
- No manual refresh needed

### Scanner Modes

**Equity Scan** (top left)
- S&P 500 components
- Popular day-trade stocks
- ETFs
- Updates every 60 seconds
- Cached to avoid rate limits

**Crypto Scan** (via `/api/scan/crypto`)
- 15 major crypto pairs
- BTC/USD, ETH/USD, SOL/USD, etc.
- Same refresh as equities

## Understanding Scores

### Score Meaning

**Score 0-5**: Weak signal, no trade card
**Score 5-7**: Moderate signal, "WARNING" alert
**Score 7-9**: Strong signal, "GO" alert
**Score 9+**: Very strong signal, "FIRE" alert

### Confluence Factors

Each adds points if detected:

| Factor | Points |
|--------|--------|
| Order Flow Imbalance | +2.0 |
| Orderflow Wall | +1.5 |
| Absorption | +2.0 |
| RSI Extreme | +1.5 |
| RSI Divergence | +2.0 |
| MACD Crossover | +1.0 |
| VWAP Deviation | +1.5 |
| Volume Spike | +1.0 |
| CVD Divergence | +1.5 |
| EMA Crossover | +1.0 |
| Multi-TF Alignment | +2.0 |
| S/R Zone | +1.5 |

**Max possible**: 20.0 points

### Trade Card Risk/Reward

Example:
- Entry: $100
- Stop: $95 (5pt risk)
- TP1: $107.50 (7.5pt gain, **1.5:1** risk/reward)
- TP2: $112.50 (12.5pt gain, **2.5:1** risk/reward)

Use these ratios to size your position:
- Never risk more than 1-2% per trade
- Scale out at TP1, let runner go to TP2

## Mobile View

The dashboard is mobile-responsive.

Access from phone:
```
http://<your-computer-ip>:8080
```

Example: `http://192.168.1.100:8080`

Works on iPhone, Android, iPad.

## Troubleshooting

### Dashboard Won't Load

```
Make sure you see this in terminal:
  - "Starting FastAPI web server on 0.0.0.0:8080"
  - "Uvicorn running on http://0.0.0.0:8080"
```

If not:
- Check Python installed: `python --version`
- Check FastAPI: `pip install fastapi uvicorn`
- Restart: `python main.py`

### Symbols Not Analyzing

API keys needed for real data. Without them, you see mock data (for demo).

Set in `.env`:
```
ALPACA_API_KEY=your_key_here
POLYGON_API_KEY=your_key_here
```

Then restart: `python main.py`

### WebSocket Says "Disconnected"

This is normal - just means live updates paused.

Reconnects automatically.

Check if:
- Browser tab is active
- Network connection is stable
- Firewall allows localhost:8080

### Symbols Keep Saying "No Score"

Your API credentials might be empty (using mock data).

For real analysis, add API keys to `.env`.

## Advanced Usage

### Custom Universe

Edit `scan_universe.py`:

```python
MY_SYMBOLS = ["AAPL", "TSLA", "NVDA"]

def get_custom_universe():
    return MY_SYMBOLS
```

Then in `server.py`, replace scanner to use your list.

### Adjust Confluence Threshold

In `config.py`:

```python
CONFLUENCE_MIN = 5.0  # Change to 6.0 for stricter
```

Higher = fewer but higher-quality signals.

### Monitor in Discord

Configure Discord webhook in `config.py`:

```python
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
```

Trade cards auto-post to Discord when generated.

## Real-World Workflow

1. **Morning**: Check dashboard, review overnight signals
2. **Pre-market**: Run scan for setups
3. **Market open**: Watch top setups panel (auto-refreshes)
4. **Throughout day**: Search symbols you're interested in
5. **Add to watchlist**: Symbols you want to monitor
6. **Trade**: Use entry/stop/target from trade cards
7. **Exit**: Close at TP1 or TP2, or stop if wrong

## Next Steps

- Read full docs: `DASHBOARD.md`
- Explore API: `GET http://localhost:8080/api/status`
- Configure alerts: Set `DISCORD_WEBHOOK_URL`
- Connect real data: Set Alpaca/Polygon API keys
- Deploy: Use Docker or cloud hosting

---

**Need help?** Check the logs in the terminal for error messages.

**Questions?** Review the full documentation in DASHBOARD.md or check the code comments in server.py.
