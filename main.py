"""
Order Flow Radar — Main Orchestrator
REAL DATA ONLY. Open fetch — no watchlist, no demo, no static symbols.
Every scan: discovers what Alpaca says is hot RIGHT NOW, fetches bars live, evaluates, alerts.
Fires: whale prints, sweeps, unusual vol, call/put sweeps, confluence signals.
"""

import asyncio
import logging
import signal as _signal
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp
import uvicorn

from signals.orderflow import OrderFlowSignals
from signals.momentum import MomentumSignals
from signals.volume import VolumeSignals
from signals.trend import TrendSignals
from signals.levels import LevelSignals
from signals.confluence import ConfluenceEngine
from signals.learner import SignalLearner

from alerts.formatter import format_discord_embed, format_free_tier_embed
from alerts.discord_webhook import DiscordAlerter
from alerts.journal import SignalJournal

from market_scanner import MarketScanner
from config import load_config, ALPACA_API_KEY, ALPACA_SECRET_KEY

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────
WHALE_VOL_MULT      = 5.0      # 5x avg volume
SWEEP_VOL_MULT      = 3.0      # 3x avg volume
UNUSUAL_VOL_MULT    = 2.5      # 2.5x avg volume
MIN_WHALE_DOLLARS   = 500_000  # $500k min
CONFLUENCE_MIN      = 5.0
COOLDOWN_SECONDS    = 300      # 5 min cooldown per symbol per alert type
ALPACA_HEADERS      = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
EQUITY_SCAN_SECS    = 60
CRYPTO_SCAN_SECS    = 30
DISCOVERY_SECS      = 900      # rediscover every 15 min for freshest symbols


# ── On-demand bar fetcher ──────────────────────────────────────────────────

async def fetch_bars(session: aiohttp.ClientSession, symbol: str,
                     timeframe: str = "1Hour", limit: int = 100) -> Optional[List[Dict]]:
    """Fetch OHLCV bars directly from Alpaca REST. Returns list of dicts or None."""
    try:
        url = "https://data.alpaca.markets/v2/stocks/bars"
        params = {"symbols": symbol, "timeframe": timeframe, "limit": limit, "feed": "iex"}
        async with session.get(url, headers=ALPACA_HEADERS, params=params,
                               timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw = data.get("bars", {}).get(symbol, [])
                return [{"open": b["o"], "high": b["h"], "low": b["l"],
                          "close": b["c"], "volume": b["v"],
                          "timestamp": b.get("t", "")} for b in raw] if raw else None
            return None
    except Exception:
        return None


async def fetch_latest_quote(session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
    """Fetch latest mid price from Alpaca."""
    try:
        url = "https://data.alpaca.markets/v2/stocks/quotes/latest"
        params = {"symbols": symbol, "feed": "iex"}
        async with session.get(url, headers=ALPACA_HEADERS, params=params,
                               timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                q = data.get("quotes", {}).get(symbol, {})
                bid = float(q.get("bp", 0))
                ask = float(q.get("ap", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return float(q.get("ap", 0)) or float(q.get("bp", 0)) or None
    except Exception:
        return None


async def fetch_snapshot(session: aiohttp.ClientSession, symbol: str) -> Optional[Dict]:
    """Fetch Alpaca snapshot (VWAP, daily vol, etc)."""
    try:
        url = f"https://data.alpaca.markets/v2/stocks/snapshots"
        params = {"symbols": symbol, "feed": "iex"}
        async with session.get(url, headers=ALPACA_HEADERS, params=params,
                               timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                snap = data.get("snapshots", {}).get(symbol, {})
                daily = snap.get("dailyBar", {})
                return {
                    "vwap":         float(daily.get("vw", 0)),
                    "daily_volume": float(daily.get("v", 0)),
                    "daily_open":   float(daily.get("o", 0)),
                    "daily_close":  float(daily.get("c", 0)),
                }
    except Exception:
        return None


# ── Orchestrator ──────────────────────────────────────────────────────────

class TradingSignalOrchestrator:

    def __init__(self, config: Dict):
        self.config  = config
        self.running = True

        # Signal modules
        self.orderflow = OrderFlowSignals(config)
        self.momentum  = MomentumSignals(config)
        self.volume    = VolumeSignals(config)
        self.trend     = TrendSignals(config)
        self.levels    = LevelSignals(config)
        self.confluence = ConfluenceEngine(config)

        # Alerts
        self.discord  = DiscordAlerter(config)
        self.journal  = SignalJournal(config)

        # Learning
        self.learner  = SignalLearner()
        self.confluence.set_weights(self.learner.get_weights())

        # Discovery
        self.scanner  = MarketScanner()
        self.equities: List[str] = []
        self.cryptos:  List[str] = []

        # Cooldown tracker: {f"{type}_{symbol}": datetime}
        self.last_alert: Dict[str, datetime] = {}

        # Stats
        self.signals = 0
        self.whales  = 0
        self.sweeps  = 0

        logger.info("Orchestrator ready — OPEN FETCH mode, no watchlist")

    def is_market_hours(self) -> bool:
        now  = datetime.now(ZoneInfo("America/New_York"))
        mins = now.hour * 60 + now.minute
        return now.weekday() < 5 and 9 * 60 + 30 <= mins <= 16 * 60 + 30

    def is_extended_hours(self) -> bool:
        now  = datetime.now(ZoneInfo("America/New_York"))
        mins = now.hour * 60 + now.minute
        return now.weekday() < 5 and 4 * 60 <= mins <= 20 * 60

    def _cooled(self, key: str) -> bool:
        last = self.last_alert.get(key)
        return bool(last and (datetime.utcnow() - last).total_seconds() < COOLDOWN_SECONDS)

    def _stamp(self, key: str):
        self.last_alert[key] = datetime.utcnow()

    # ── Discord helpers ───────────────────────────────────────────────────

    async def _send_pro(self, embed: Dict):
        await self.discord._post_webhook(self.discord.webhook_pro, embed)

    async def _send_premium(self, embed: Dict):
        await self.discord._post_webhook(self.discord.webhook_premium, embed)

    async def _send_free(self, embed: Dict):
        await self.discord._post_webhook(self.discord.webhook_free, embed)

    async def _send_all(self, embed: Dict):
        await asyncio.gather(
            self._send_pro(embed),
            self._send_premium(embed),
            self._send_free(embed),
            return_exceptions=True
        )

    # ── Alert builders ────────────────────────────────────────────────────

    async def alert_whale(self, symbol: str, price: float, vol: float,
                           avg_vol: float, dollar_val: float):
        key = f"whale_{symbol}"
        if self._cooled(key): return
        self._stamp(key)
        self.whales += 1
        ratio = vol / avg_vol if avg_vol > 0 else 0
        embed = {
            "title":       f"🐋 WHALE PRINT — {symbol}",
            "description": f"**{ratio:.1f}x** avg volume  |  **${dollar_val:,.0f}** printed",
            "color":       0xFFD700,
            "fields": [
                {"name": "Price",     "value": f"${price:.2f}",         "inline": True},
                {"name": "Volume",    "value": f"{vol:,.0f}",            "inline": True},
                {"name": "Ratio",     "value": f"{ratio:.1f}x avg",      "inline": True},
                {"name": "$ Value",   "value": f"${dollar_val:,.0f}",    "inline": True},
            ],
            "footer": {"text": f"Order Flow Radar  |  {datetime.utcnow().strftime('%H:%M:%S UTC')}"}
        }
        await self._send_pro(embed)
        await self._send_premium(embed)
        logger.info(f"🐋 WHALE {symbol} ${dollar_val:,.0f} ({ratio:.1f}x)")

    async def alert_sweep(self, symbol: str, price: float,
                           direction: str, ratio: float, bars_count: int):
        key = f"sweep_{symbol}_{direction}"
        if self._cooled(key): return
        self._stamp(key)
        self.sweeps += 1
        emoji = "🟢" if direction == "bull" else "🔴"
        label = "BULL SWEEP" if direction == "bull" else "BEAR SWEEP"
        embed = {
            "title":       f"{emoji} {label} — {symbol}",
            "description": f"**{ratio:.1f}x** volume over {bars_count} bars",
            "color":       0x00FF00 if direction == "bull" else 0xFF0000,
            "fields": [
                {"name": "Price",   "value": f"${price:.2f}", "inline": True},
                {"name": "Ratio",   "value": f"{ratio:.1f}x", "inline": True},
            ],
            "footer": {"text": f"Order Flow Radar  |  {datetime.utcnow().strftime('%H:%M:%S UTC')}"}
        }
        await self._send_pro(embed)
        logger.info(f"{emoji} SWEEP {symbol} {ratio:.1f}x ({direction})")

    async def alert_unusual_volume(self, symbol: str, price: float,
                                    ratio: float, direction: str):
        key = f"uvol_{symbol}"
        if self._cooled(key): return
        self._stamp(key)
        d = "🟢" if direction == "up" else "🔴"
        embed = {
            "title":       f"⚡ UNUSUAL VOLUME — {symbol}",
            "description": f"{d} **{ratio:.1f}x** average volume",
            "color":       0xFF8C00,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Ratio", "value": f"{ratio:.1f}x", "inline": True},
            ],
            "footer": {"text": f"Order Flow Radar  |  {datetime.utcnow().strftime('%H:%M:%S UTC')}"}
        }
        await self._send_free(embed)
        await self._send_pro(embed)
        logger.info(f"⚡ UVOL {symbol} {ratio:.1f}x ({direction})")

    async def alert_signal(self, trade_card: Dict):
        symbol = trade_card["symbol"]
        key = f"signal_{symbol}"
        if self._cooled(key): return
        self._stamp(key)
        self.signals += 1

        full = format_discord_embed(trade_card)
        free = format_free_tier_embed(trade_card)

        if full:
            await self._send_pro(full)
            await self._send_premium(full)
        if free:
            self.discord.free_delay_queue.append({
                "embed":   free,
                "send_at": datetime.utcnow() + timedelta(minutes=5)
            })

        await self.journal.log_signal(trade_card)
        await self.learner.record_signal(trade_card)
        logger.info(f"🚨 SIGNAL {symbol} {trade_card.get('direction','?').upper()} score={trade_card.get('score',0):.1f}")

    # ── Per-symbol evaluation ─────────────────────────────────────────────

    async def scan_equity(self, session: aiohttp.ClientSession, symbol: str):
        try:
            # Fetch bars + quote + snapshot live — no cache, no watchlist
            bars = await fetch_bars(session, symbol, "1Hour", 100)
            if not bars or len(bars) < 5:
                return

            price = await fetch_latest_quote(session, symbol)
            if not price:
                price = bars[-1]["close"]
            if price <= 0:
                return

            snap = await fetch_snapshot(session, symbol)
            vwap = snap["vwap"] if snap else None

            # Volume analysis
            vols    = [b["volume"] for b in bars if b["volume"] > 0]
            cur_vol = vols[-1] if vols else 0
            avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1) if len(vols) > 1 else 0

            if avg_vol > 0 and cur_vol > 0:
                ratio = cur_vol / avg_vol
                dollar_val = cur_vol * price
                direction  = "up" if bars[-1]["close"] >= bars[-1]["open"] else "down"

                if ratio >= WHALE_VOL_MULT and dollar_val >= MIN_WHALE_DOLLARS:
                    await self.alert_whale(symbol, price, cur_vol, avg_vol, dollar_val)

                elif ratio >= UNUSUAL_VOL_MULT:
                    await self.alert_unusual_volume(symbol, price, ratio, direction)

                # Sweep: 3x vol surge in last 3 bars
                if len(vols) >= 4:
                    recent_avg = sum(vols[-4:-1]) / 3
                    if recent_avg > 0 and cur_vol / recent_avg >= SWEEP_VOL_MULT:
                        sweep_dir = "bull" if direction == "up" else "bear"
                        await self.alert_sweep(symbol, price, sweep_dir,
                                               cur_vol / recent_avg, 3)

            # Full confluence signal evaluation
            all_signals = {
                "orderflow": self.orderflow.evaluate(symbol, {}, []),
                "momentum":  self.momentum.evaluate(symbol, bars, vwap),
                "volume":    self.volume.evaluate(symbol, bars, []),
                "trend":     self.trend.evaluate(symbol, {"1hr": bars}),
                "levels":    self.levels.evaluate(symbol, bars, price),
            }

            tc = self.confluence.evaluate(symbol, all_signals, price, None, "multi")
            if tc and tc.get("score", 0) >= CONFLUENCE_MIN:
                await self.alert_signal(tc)

        except Exception as e:
            logger.debug(f"scan_equity {symbol}: {e}")

    # ── Background tasks ──────────────────────────────────────────────────

    async def discovery_task(self):
        """Rediscover hottest symbols every 15 min. Completely open — no watchlist."""
        logger.info("Discovery task started — open fetch, no watchlist")
        while self.running:
            try:
                targets      = await self.scanner.get_scan_targets()
                self.equities = targets.get("equities", [])
                self.cryptos  = targets.get("crypto", [])
                logger.info(f"Discovered: {len(self.equities)} equities, {len(self.cryptos)} crypto")
            except Exception as e:
                logger.error(f"Discovery error: {e}")
            await asyncio.sleep(DISCOVERY_SECS)

    async def equity_scan_task(self):
        """Scan all discovered equities every 60s during market hours."""
        logger.info("Equity scan task started")
        await asyncio.sleep(20)  # wait for first discovery

        while self.running:
            try:
                if self.is_extended_hours() and self.equities:
                    logger.info(f"Scanning {len(self.equities)} equities (open fetch)...")

                    # Batch into groups of 20 to avoid hammering API
                    async with aiohttp.ClientSession() as session:
                        for i in range(0, len(self.equities), 20):
                            batch = self.equities[i:i+20]
                            await asyncio.gather(
                                *[self.scan_equity(session, sym) for sym in batch],
                                return_exceptions=True
                            )
                            await asyncio.sleep(1)  # brief pause between batches

                    logger.info(
                        f"Scan done — signals: {self.signals} | "
                        f"whales: {self.whales} | sweeps: {self.sweeps}"
                    )
                else:
                    logger.debug("Market closed — waiting")
            except Exception as e:
                logger.error(f"Equity scan error: {e}")
            await asyncio.sleep(EQUITY_SCAN_SECS)

    async def crypto_scan_task(self):
        """Scan crypto every 30s 24/7."""
        from data.alpaca_crypto import AlpacaCryptoHandler
        crypto_handler = AlpacaCryptoHandler()

        # Start WebSocket in background
        asyncio.create_task(crypto_handler.start())
        await asyncio.sleep(10)

        logger.info("Crypto scan task started")
        while self.running:
            try:
                for symbol in self.cryptos:
                    price = crypto_handler.get_mid(symbol)
                    if not price:
                        continue

                    book   = crypto_handler.get_book(symbol)
                    trades = crypto_handler.get_trades(symbol, 200)

                    key = f"signal_{symbol}"
                    if self._cooled(key):
                        continue

                    all_signals = {
                        "orderflow": self.orderflow.evaluate(symbol, book, trades),
                        "momentum":  self.momentum.evaluate(symbol, [], None),
                        "volume":    self.volume.evaluate(symbol, [], trades),
                        "trend":     self.trend.evaluate(symbol, {}),
                        "levels":    self.levels.evaluate(symbol, [], price),
                    }

                    tc = self.confluence.evaluate(symbol, all_signals, price, None, "24/7")
                    if tc and tc.get("score", 0) >= CONFLUENCE_MIN:
                        await self.alert_signal(tc)

            except Exception as e:
                logger.error(f"Crypto scan error: {e}")
            await asyncio.sleep(CRYPTO_SCAN_SECS)

    async def free_queue_task(self):
        while self.running:
            try:
                await self.discord.process_free_queue()
            except Exception as e:
                logger.error(f"Free queue: {e}")
            await asyncio.sleep(60)

    async def learner_task(self):
        while self.running:
            await asyncio.sleep(86400)
            try:
                await self.learner.retrain()
                self.confluence.set_weights(self.learner.get_weights())
                logger.info("Learner retrained")
            except Exception as e:
                logger.error(f"Learner: {e}")

    async def run(self):
        logger.info("All tasks starting")
        await asyncio.gather(
            self.discovery_task(),
            self.equity_scan_task(),
            self.crypto_scan_task(),
            self.free_queue_task(),
            self.learner_task(),
            return_exceptions=True
        )

    def shutdown(self):
        self.running = False


def run_api_server():
    try:
        from server import app
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
    except Exception as e:
        logger.error(f"API server: {e}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    logger.info("=" * 60)
    logger.info("  ORDER FLOW RADAR — LIVE")
    logger.info("  OPEN FETCH — no watchlist, no demo, no fake data")
    logger.info("  Whale prints | Sweeps | Unusual Vol | Confluence")
    logger.info("=" * 60)

    config = load_config()
    orch   = TradingSignalOrchestrator(config)

    threading.Thread(target=run_api_server, daemon=True).start()

    def _shutdown(signum, frame):
        orch.shutdown()

    _signal.signal(_signal.SIGINT,  _shutdown)
    _signal.signal(_signal.SIGTERM, _shutdown)

    try:
        await orch.run()
    except Exception as e:
        logger.error(f"Fatal: {e}")
        orch.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
