# S3 Decision Engine

**Synthetic System Strain** — An institutional-grade options signal engine with autonomous scanning, AI-driven reasoning, and mathematical risk management.

## Architecture

```
main.py              → FastAPI server + background scanner
engine/
  ├── decision.py    → Signal evaluation (SL/TP, sizing, bias)
  ├── features.py    → Sharpe Momentum, Volatility, Anomaly Detection
  ├── scoring.py     → S3 Score + State Machine (IGNITION/EXHAUSTION/NEUTRAL)
  ├── options_math.py→ Strike/Expiry formulas (0DTE + 14DTE)
  ├── intelligence.py→ Anthropic Claude AI reasoning hook
  └── data_collector.py → Yahoo Finance rate-limited data fetcher
notifier.py          → Discord webhook alerts
```

## Lethal Suite Features

| Feature | Description |
|---|---|
| **Sharpe Momentum** | Volatility-adjusted momentum filters chaotic noise |
| **ATR Risk Management** | Mathematical SL (2x ATR) and TP (6x ATR = 3:1 R/R) |
| **Dynamic Position Sizing** | 0-10% allocation scaled by S3 Score conviction |
| **$50 Price Gate** | Filters out high-priced tickers for retail accessibility |
| **0DTE Routing** | IWM and sub-$5 tickers route to same-day expiry |
| **AI Reasoning** | Claude-3 executive summaries on actionable signals |
| **Live Scanner** | Background autonomous scanning with configurable watchlist |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Engine status + scanner state |
| `POST` | `/signal` | Manual signal evaluation |
| `POST` | `/scan` | Live scan with real market data |
| `POST` | `/scanner/start` | Start background scanner |
| `POST` | `/scanner/stop` | Stop background scanner |

## Deployment

### Render (Docker)
1. Connect this repo to Render
2. Set environment variables in the Render dashboard:
   - `DISCORD_WEBHOOK_URL`
   - `ANTHROPIC_API_KEY`
   - `AUTO_SCAN=true` (optional, for autonomous mode)
3. Deploy — `render.yaml` handles the rest

### Local
```bash
pip install -r requirements.txt
python main.py
```

## Configuration

All parameters are `.env`-driven. See `render.yaml` for the complete list.
No magic numbers in source code — **Developer Manifesto compliant**.
