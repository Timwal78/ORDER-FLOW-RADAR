# Order Flow Radar — Discord Server Setup Guide

## Server Name
Order Flow Radar

## Roles (create in this order)
1. **Premium** — Color: Gold (#FFD700) — Display separately, hoist
2. **Pro** — Color: Green (#00FF88) — Display separately, hoist  
3. **Free** — Color: Gray (#888888) — Auto-assign on join

## Categories & Channels

### INFO (category)
- #welcome (read-only for everyone)
- #how-it-works (read-only)
- #subscribe (read-only — contains Stripe links + QR codes)

### SIGNALS (category)
- #free-signals (visible to @everyone, read-only)
- #pro-signals (visible to @Pro and @Premium only, read-only)
- #premium-signals (visible to @Premium only, read-only)

### COMMUNITY (category)
- #general (open chat)
- #results (read-only — weekly win/loss stats)
- #feedback (open)

## Channel Permissions
- All signal channels: only bot/webhook can post, members read-only
- #pro-signals: deny @everyone view, allow @Pro and @Premium view
- #premium-signals: deny @everyone view, allow @Premium view

## Webhooks to Create
1. **Free Signals Webhook** → #free-signals
2. **Pro Signals Webhook** → #pro-signals  
3. **Premium Signals Webhook** → #premium-signals

Save all 3 webhook URLs to .env:
```
DISCORD_WEBHOOK_FREE=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_PRO=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_PREMIUM=https://discord.com/api/webhooks/...
```

## Welcome Message (paste in #welcome)

---

**Welcome to Order Flow Radar**

The market never stops moving. Neither do we.

Order Flow Radar is an AI-powered signal engine that scans hundreds of stocks and crypto 24/7 using 15 confluence indicators across 5 live data sources. When enough signals stack up, you get a trade card delivered right here — entry, stop loss, targets, risk/reward, and the exact confluences that triggered it.

**What you get:**

**Free** — Delayed scanner results in #free-signals. See the system in action before you commit.

**Pro ($9.99/mo)** — Real-time trade cards in #pro-signals with full confluence breakdowns. Discord alerts the second a signal fires.
Subscribe: https://buy.stripe.com/14A14p4Rcbnp9hHafE6wE0J

**Premium ($19.99/mo)** — Everything in Pro PLUS options recommendations in #premium-signals. The system tells you the exact contract: strike, expiry, premium, Greeks, risk/reward.
Subscribe: https://buy.stripe.com/00wfZjdnIajl79zafE6wE0K

**The 15 Indicators:**
Order Book Imbalance | Wall Detection | Absorption | RSI Extremes (25/75) | RSI Divergence | MACD Crossover | MACD Acceleration | VWAP Deviation | Volume Spikes | Cumulative Volume Delta | EMA Crossover | Multi-TF Alignment | Support/Resistance Zones | Options Unusual Activity | Market Sentiment

**Rules:**
1. Signals are probabilistic, not financial advice
2. Always manage your own risk
3. Past performance does not guarantee future results
4. Be respectful in community channels

**Questions?** Drop them in #general.

---

## How-It-Works Message (paste in #how-it-works)

---

**How Order Flow Radar Works**

**Step 1: The System Scans**
Every 15-60 seconds, the engine pulls live data from Alpaca, Polygon, Alpha Vantage, and Schwab. It checks the most active stocks and all major crypto pairs.

**Step 2: Signals Stack**
For each symbol, the engine runs 15 independent indicators. Each one that fires adds points to a confluence score. A single indicator means nothing — 5+ stacked together means something.

**Step 3: Trade Card Fires**
When the score crosses the threshold, the system generates a complete trade card:
- Direction (LONG or SHORT)
- Entry price
- Stop loss (ATR-based)
- Target 1 (1.5:1 R:R)
- Target 2 (2.5:1 R:R)
- Confluence count and breakdown
- Alert level: WARNING (5-7) | GO (7-9) | FIRE (9+)

**Step 4: Options Rec (Premium)**
For Premium subscribers, the system also recommends the optimal options contract — strike, expiry, premium, delta, max risk, estimated return.

**Step 5: AI Learns**
Every signal is tracked. Did it hit TP1? TP2? Or stop loss? The system adjusts its scoring weights based on real outcomes. It literally gets smarter over time.

**Score Levels:**
- 5-7 points = Moderate setup (warning alert)
- 7-9 points = Strong setup (go signal)  
- 9+ points = A+ setup (fire signal)

---
