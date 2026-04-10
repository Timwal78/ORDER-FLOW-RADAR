# Options Recommendation Engine - Integration Guide

## Overview

The Options Recommender Engine takes trade signals from the Confluence Engine and recommends **specific options contracts** to execute those trades. Instead of just saying "BUY NVDA," it says "BUY NVDA 04/18 $140 CALL at $3.55, max risk $355, estimated return $680 at TP1."

## Architecture

### Components

1. **`signals/options_recommender.py`** - Main recommendation engine
   - `OptionsRecommender` class handles contract scoring and enrichment
   - Fetches real Schwab options chains
   - Scores contracts based on volume, spread, delta, DTE
   - Returns top 3 recommendations with detailed metrics

2. **`signals/confluence.py`** - Updated to call recommender
   - New async method: `evaluate_async()` with options integration
   - Old sync method: `evaluate()` still works (no options)
   - Pass `options_recommender` instance to constructor

3. **`alerts/formatter.py`** - Updated Discord formatting
   - Shows primary recommendation with all metrics
   - Lists 2 alternatives
   - Displays options flow context (PCR, sentiment, unusual activity)

4. **`server.py`** - New API endpoints
   - `GET /api/options/{symbol}` - Full chain analysis
   - `GET /api/options/{symbol}/recommend` - Contract recommendations

## Usage

### 1. Basic Integration (Async)

```python
from signals.confluence import ConfluenceEngine
from signals.options_recommender import OptionsRecommender
from data.schwab_options import SchwabOptionsHandler

# Initialize
schwab = SchwabOptionsHandler()
recommender = OptionsRecommender(schwab)
confluence = ConfluenceEngine(config, recommender)

# Later in your trade evaluation:
trade_card = await confluence.evaluate_async(
    symbol="NVDA",
    all_signals=signal_dict,
    current_price=145.67,
    atr=2.5,
    timeframe="swing"
)

if trade_card:
    # trade_card now includes "options_recommendation" key
    options = trade_card.get("options_recommendation")
    if options:
        primary = options["primary_pick"]
        print(f"BUY {primary['contract']}")
        print(f"Risk: ${primary['max_risk_per_contract']}")
        print(f"Est Return: ${primary['estimated_return_tp1']}")
```

### 2. Direct Recommendation (No Trade Card Required)

```python
# Get recommendations for any symbol/direction without a full trade card
trade_card_minimal = {
    "symbol": "TSLA",
    "direction": "long",
    "entry": 250.00,
    "stop_loss": 245.00,
    "tp1": 255.00,
    "tp2": 260.00,
    "timeframe": "intraday"
}

recommendation = await recommender.recommend(trade_card_minimal)
if recommendation:
    primary = recommendation["primary_pick"]
    print(f"Contract: {primary['contract']}")
    print(f"Score: {primary['score']}/10")
    print(f"Reasoning: {primary['reasoning']}")
```

### 3. Via REST API

```bash
# Get full options analysis for a symbol
curl http://localhost:8080/api/options/NVDA

# Get specific contract recommendations
curl "http://localhost:8080/api/options/NVDA/recommend?direction=long&entry=145.67"
```

## How It Works

### Scoring Logic

Each option contract is scored (0-10+) based on:

| Factor | Weight | Criteria |
|--------|--------|----------|
| Volume/OI Ratio | +2.0 | > 1.0 = high activity |
| Bid/Ask Spread | +2.0 | < 5% = very tight |
| Delta Sweet Spot | +2.0 | 0.35-0.55 = optimal direction |
| Premium Affordability | +1.0 | $0.50-$20.00 = tradeable |
| DTE Alignment | +1.5 | Matches timeframe |
| Implied Volatility | +0.5 | 20%-80% = moderate |

### DTE Filtering

- **Scalp/Intraday**: 1-7 DTE (0DTE avoided unless explicit)
- **Swing**: 14-45 DTE
- **Multi-day**: 21-60 DTE

### Strike Selection

- **LONG (CALL)**: ATM to 5% OTM above current price
- **SHORT (PUT)**: ATM to 5% OTM below current price

Prefer strikes near round numbers ($140, $145, etc).

## Response Format

### Primary Recommendation

```json
{
  "contract": "NVDA 04/18 $140 CALL",
  "strike": 140.0,
  "expiry": "2026-04-18",
  "type": "CALL",
  "dte": 9,
  "bid": 3.40,
  "ask": 3.55,
  "mid": 3.475,
  "last": 3.50,
  "volume": 12500,
  "open_interest": 8200,
  "implied_volatility": 0.42,
  "delta": 0.45,
  "gamma": 0.03,
  "theta": -0.15,
  "vega": 0.08,
  "score": 8.7,
  "max_risk_per_contract": 355.0,
  "estimated_return_tp1": 680.0,
  "risk_reward": "1.9:1",
  "breakeven": 143.55,
  "reasoning": "High vol/OI (1.23), tight spread (3.4%), optimal delta (0.45), 9 DTE"
}
```

### Alternatives

Same format, listed in score order (2nd and 3rd picks).

### Options Flow Context

```json
{
  "put_call_ratio": 0.72,
  "unusual_activity_count": 3,
  "unusual_activity": [
    {
      "strike": "145.0",
      "expiry": "2026-04-18:9",
      "type": "CALL",
      "volume": 45000,
      "open_interest": 8200,
      "volume_oi_ratio": 5.49
    }
  ],
  "smart_money_bias": "slightly_bullish"
}
```

## Error Handling

The recommender gracefully handles API failures:

```python
# If Schwab is down, this still returns trade_card, just without options:
trade_card = await confluence.evaluate_async(...)

# trade_card will have "options_recommendation": None
# Discord alert still fires, just without the options section
```

## Discord Alert Format

When options recommendations are available, Discord embeds include:

```
📊 Recommended Options:
  NVDA 04/18 $140 CALL
  Mid: $3.48 | Delta: 0.45
  Risk: $355 | Return@TP1: $680 (1.9:1)
  Break-even: $143.55
  Vol: 12,500 | OI: 8,200
  High vol/OI (1.23), tight spread (3.4%), optimal delta (0.45), 9 DTE

Alternatives:
  Alt 1: NVDA 04/25 $142 CALL ($2.80)
  Alt 2: NVDA 04/18 $138 CALL ($4.90)

Options Flow:
  P/C Ratio: 0.72 | Sentiment: SLIGHTLY BULLISH
  Unusual Activity: 3 contracts detected
```

## Configuration

All settings in `config.py` and `.env`:

```env
# Required for options recommender
SCHWAB_APP_KEY=your_app_key
SCHWAB_APP_SECRET=your_app_secret
SCHWAB_REFRESH_TOKEN=your_refresh_token

# Polling interval (seconds)
SCHWAB_POLL_SECONDS=300  # 5 minutes during market hours
```

## Real Data Only

- **NO mock contracts** - All data from Schwab API
- **NO fake optionality** - If API fails, recommender returns None
- **API failures are graceful** - Trade cards still fire, options section empty
- **Live updates** - Polls during market hours (9:30-16:00 ET)

## Performance Notes

- Options chain fetch: ~500ms per symbol (async, parallelized)
- Contract scoring: ~5ms
- Trade card with options: ~600ms total
- Polling loop: Runs every 5 minutes (configurable)

## Troubleshooting

### "No options chain data available"

- Schwab API credentials invalid? Check `.env`
- Outside market hours? (9:30-16:00 ET, M-F)
- First request? Wait ~5 minutes for initial poll
- Check server logs: `tail -f logs/*.log | grep "Schwab"`

### Empty/None recommendations

- Stock has no actively traded options (low vol)
- No contracts meet strike/DTE filters
- All available contracts score below threshold
- This is expected behavior - recommendation attempts gracefully

### Spread too wide / No suitable contracts

- Low-volume tickers: wait for better liquidity
- Very far OTM strikes: adjust your entry/targets
- Non-standard DTE: consider different timeframe

## Integration Checklist

- [x] Created `signals/options_recommender.py`
- [x] Updated `signals/confluence.py` with `evaluate_async()`
- [x] Updated `alerts/formatter.py` for Discord output
- [x] Added API endpoints in `server.py`
- [x] Integrated Schwab handler startup
- [x] Real data only (no mocks)
- [x] Graceful error handling
- [x] Comprehensive logging

## Next Steps

1. **Enable in market scanner**: Update `market_scanner.py` to pass options recommender
2. **Database logging**: Store options recommendations in journal alongside trade cards
3. **Backtesting**: Track which recommendations hit targets vs stop
4. **ML optimization**: Feed recommendation accuracy back to learner
5. **SMS alerts**: Send options contract details to phone (not just Discord)
