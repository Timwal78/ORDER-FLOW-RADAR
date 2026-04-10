# Options Recommender - Quick Start

## 1-Minute Overview

Your trading system now recommends **specific options contracts** instead of just direction/price targets.

When a LONG signal fires for NVDA at $145.67, instead of just saying "go long," it says:
- **BUY NVDA 04/18 $140 CALL at $3.55**
- Max risk: $355/contract
- Estimated return at TP1: $680 (1.9:1)
- Alternative 1: NVDA 04/25 $142 CALL at $2.80
- Alternative 2: NVDA 04/18 $138 CALL at $4.90

## Getting Started

### Step 1: Verify Schwab Credentials

Check your `.env`:
```env
SCHWAB_APP_KEY=xxx
SCHWAB_APP_SECRET=xxx
SCHWAB_REFRESH_TOKEN=xxx
```

If missing, the system will still work but won't fetch options.

### Step 2: Start the Server

Options polling starts automatically:
```bash
python server.py
# Logs will show: "Schwab options polling started"
```

### Step 3: Use in Your Code

**Option A: Async (recommended)**
```python
from signals.confluence import ConfluenceEngine
from signals.options_recommender import OptionsRecommender
from data.schwab_options import SchwabOptionsHandler

schwab = SchwabOptionsHandler()
recommender = OptionsRecommender(schwab)
confluence = ConfluenceEngine(config, recommender)

# Later...
trade_card = await confluence.evaluate_async(
    symbol="NVDA",
    all_signals=all_signals,
    current_price=145.67,
    timeframe="swing"
)

if trade_card and trade_card.get("options_recommendation"):
    options = trade_card["options_recommendation"]
    primary = options["primary_pick"]
    print(f"Buy {primary['contract']}")
    print(f"Risk: ${primary['max_risk_per_contract']}")
```

**Option B: REST API**
```bash
# Get recommendations
curl "http://localhost:8080/api/options/NVDA/recommend?direction=long&entry=145.67"

# Get full analysis
curl http://localhost:8080/api/options/NVDA
```

**Option C: Discord Alert (automatic)**

When a trade signal fires, Discord embed now includes options section automatically.

## Discord Alert Example

```
🔼 LONG NVDA

Entry: $145.67
Stop Loss: $143.21 (-1.68%)
Target 1: $150.12 (+3.07R)
Target 2: $154.89 (+6.28R)

📊 Recommended Options:
  NVDA 04/18 $140 CALL
  Mid: $3.48 | Delta: 0.45
  Risk: $355 | Return@TP1: $680 (1.9:1)
  Break-even: $143.55
  Vol: 12,500 | OI: 8,200
  High vol/OI, tight spread, optimal delta, 9 DTE

Alternatives:
  Alt 1: NVDA 04/25 $142 CALL ($2.80)
  Alt 2: NVDA 04/18 $138 CALL ($4.90)

Options Flow:
  P/C Ratio: 0.72 | Sentiment: SLIGHTLY BULLISH
  Unusual Activity: 3 contracts detected
```

## Key Concepts

### DTE Ranges (Days to Expiration)

| Timeframe | DTE Range | Examples |
|-----------|-----------|----------|
| Scalp | 1-7 days | Fast decay theta, quick profit |
| Swing | 14-45 days | Balanced theta/gamma |
| Multi-day | 21-60 days | Slower decay, less theta |

### Strike Selection

| Trade Type | Strike Selection | Example (Stock @ $145) |
|-----------|------------------|----------------------|
| LONG (CALL) | ATM to 5% OTM | $145-$152 |
| SHORT (PUT) | ATM to 5% OTM | $138-$145 |

### Scoring Factors

Contracts are scored on these factors:

1. **Volume/OI Ratio** (+2.0) - Higher = more active
   - > 1.0: +2.0 | 0.5-1.0: +1.0 | < 0.1: -1.0

2. **Bid/Ask Spread** (+2.0) - Tighter = more liquid
   - < 5%: +2.0 | 5-10%: +1.0 | > 20%: -1.0

3. **Delta** (+2.0) - Sweet spot 0.35-0.55
   - 0.35-0.55: +2.0 | 0.30-0.60: +1.0 | < 0.20 or > 0.80: -1.0

4. **Premium** (+1.0) - Affordable
   - $0.50-$20.00: +1.0

5. **DTE Alignment** (+1.5) - Matches timeframe
   - Correct range for timeframe: +1.5

6. **Implied Volatility** (+0.5) - Moderate
   - 20%-80%: +0.5

Target score: 8+ is excellent, 6+ is good, <5 means weak recommendation.

## Common Workflows

### Workflow 1: Monitor a Signal

```python
# In your signal monitoring loop:
for symbol in watch_list:
    trade_card = await confluence.evaluate_async(
        symbol,
        all_signals[symbol],
        current_prices[symbol],
        timeframe="swing"
    )
    
    if trade_card:
        # Send to Discord automatically
        # (if you have webhook setup)
        await send_discord(format_discord_embed(trade_card))
        
        # Or use options manually:
        if trade_card.get("options_recommendation"):
            rec = trade_card["options_recommendation"]
            print(f"Contract: {rec['primary_pick']['contract']}")
```

### Workflow 2: Manual Option Lookup

```python
# Just want to check options for a symbol?
import aiohttp

async with aiohttp.ClientSession() as session:
    resp = await session.get(
        "http://localhost:8080/api/options/TSLA/recommend",
        params={"direction": "short", "entry": 245.50}
    )
    data = await resp.json()
    
    primary = data["recommendation"]["primary_pick"]
    print(f"Sell {primary['contract']} at ${primary['ask']:.2f}")
```

### Workflow 3: Analyze Options Flow

```python
# Check unusual activity and sentiment:
async with aiohttp.ClientSession() as session:
    resp = await session.get("http://localhost:8080/api/options/SPY")
    data = await resp.json()
    
    print(f"P/C Ratio: {data['put_call_ratio']}")
    print(f"Sentiment: {data['sentiment']}")
    print(f"Unusual Contracts: {data['unusual_count']}")
    
    for unusual in data["unusual_activity"][:3]:
        print(f"  {unusual['type']} {unusual['strike']} vol/oi: {unusual['volume_oi_ratio']:.1f}x")
```

## Troubleshooting

### "No options chain data available"

**Possible causes:**
1. Schwab credentials not set in `.env`
2. Market is closed (polling only runs 9:30-16:00 ET, M-F)
3. First request - wait 5 minutes for initial poll
4. Check logs: `grep "Schwab" logs/*.log`

### Recommendations don't match my stock price

This is normal! Options recommender uses strike selection logic (ATM to 5% OTM). If your stock price is outside that range or has few options at that price level, recommendations may look different.

### "Could not generate recommendation"

The stock likely has no liquid options or no contracts match the DTE/strike filters. Try:
- Adjusting entry price
- Checking if stock has options trading
- Looking at unusual activity count (0 = no action)

### Spread is too wide / Premium too cheap

Low-volume stocks will have wide spreads. Consider:
- Waiting for better volume
- Using LEAPS (further out) for better spreads
- Checking unusual activity - if 0, liquidity is poor

## API Response Examples

### GET /api/options/NVDA/recommend

```json
{
  "symbol": "NVDA",
  "direction": "long",
  "entry": 145.67,
  "recommendation": {
    "primary_pick": {
      "contract": "NVDA 04/18 $140 CALL",
      "strike": 140.0,
      "expiry": "2026-04-18",
      "dte": 9,
      "bid": 3.40,
      "ask": 3.55,
      "mid": 3.475,
      "delta": 0.45,
      "gamma": 0.03,
      "theta": -0.15,
      "vega": 0.08,
      "volume": 12500,
      "open_interest": 8200,
      "implied_volatility": 0.42,
      "score": 8.7,
      "max_risk_per_contract": 355.0,
      "estimated_return_tp1": 680.0,
      "risk_reward": "1.9:1",
      "breakeven": 143.55,
      "reasoning": "High vol/OI (1.23), tight spread (3.4%), optimal delta (0.45), 9 DTE"
    },
    "alternatives": [
      {
        "contract": "NVDA 04/25 $142 CALL",
        "strike": 142.0,
        ...similar fields...
        "score": 7.8
      },
      {
        "contract": "NVDA 04/18 $138 CALL",
        ...
        "score": 7.2
      }
    ],
    "options_flow_context": {
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
  },
  "timestamp": "2026-04-09T14:30:00.123456"
}
```

### GET /api/options/NVDA

```json
{
  "symbol": "NVDA",
  "timestamp": "2026-04-09T14:30:00.123456",
  "put_call_ratio": 0.72,
  "sentiment": "slightly_bullish",
  "options_flow": {
    "put_volume": 45000,
    "call_volume": 62000,
    "put_oi": 180000,
    "call_oi": 220000,
    "unusual_count": 3
  },
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
  "unusual_count": 3
}
```

## Key Files

| File | Purpose |
|------|---------|
| `signals/options_recommender.py` | Core recommendation engine |
| `signals/confluence.py` | Integrated with trade evaluation |
| `alerts/formatter.py` | Discord embed formatting |
| `server.py` | REST API endpoints |
| `INTEGRATION_GUIDE.md` | Detailed docs (70+ lines) |

## Real Data Only

- No mock contracts ever generated
- No fake API responses
- If Schwab is down, system gracefully returns None
- All parsing based on actual Schwab API format
- OAuth2 token management automatic

---

**Ready to use!** Your system will automatically recommend options when signals fire.

Questions? Check `INTEGRATION_GUIDE.md` for detailed docs or review code in `signals/options_recommender.py`.
