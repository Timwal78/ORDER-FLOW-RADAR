"""
Order Flow Radar™ — Alpaca API Client
ScriptMasterLabs™

Handles:
  - WebSocket stream: real-time trades & quotes (tick-rule CVD source)
  - REST snapshots: price initialization for discovered symbols
  - No mock data. No fallbacks. If Alpaca fails → log error, continue.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Callable, Optional, List

import aiohttp

import config

logger = logging.getLogger("alpaca_api")

_WS_URL_STOCKS = "wss://stream.data.alpaca.markets/v2/iex"
_REST_BASE      = "https://data.alpaca.markets"
_BROKER_BASE    = "https://api.alpaca.markets"

# Global health status for the dashboard
api_health = {
    "alpaca_ws": "OFFLINE",
    "alpaca_rest": "READY",
    "polygon": "READY",
    "schwab": "READY"
}


class AlpacaAPI:
    """
    Alpaca WebSocket + REST client.
    Real data only — trade/quote events directly feed FlowEngine.
    """

    def __init__(self, api_key: str, api_secret: str):
        self._key    = api_key
        self._secret = api_secret
        self._headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws               = None
        self._subscribed: set  = set()
        self._on_trade: Optional[Callable] = None
        self._on_quote: Optional[Callable] = None
        self._running  = False

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ──────────────────────────────────────────────────────────────────────────
    # WebSocket Stream
    # ──────────────────────────────────────────────────────────────────────────

    async def start_stream(
        self,
        symbols: List[str],
        on_trade: Callable,
        on_quote: Callable,
    ):
        """
        Connect to Alpaca IEX WebSocket and stream real trades/quotes.
        Reconnects automatically on disconnect.
        """
        self._on_trade = on_trade
        self._on_quote = on_quote
        self._running  = True

        while self._running:
            try:
                await self._connect_and_stream(symbols)
            except Exception as e:
                logger.error(f"Stream error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _connect_and_stream(self, symbols: List[str]):
        import websockets
        async with websockets.connect(
            _WS_URL_STOCKS,
            additional_headers={
                "APCA-API-KEY-ID":     self._key,
                "APCA-API-SECRET-KEY": self._secret,
            },
            ping_interval=20,
            ping_timeout=30,
        ) as ws:
            self._ws = ws
            api_health["alpaca_ws"] = "CONNECTED"
            logger.info("Alpaca WebSocket connected")

            # Auth
            await ws.send(json.dumps({"action": "auth", "key": self._key, "secret": self._secret}))

            # Subscribe to initial symbols
            if symbols:
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "trades": symbols,
                    "quotes": symbols,
                }))
                self._subscribed = set(symbols)
                logger.info(f"Subscribed to {len(symbols)} symbols")

            async for raw in ws:
                msgs = json.loads(raw)
                for msg in (msgs if isinstance(msgs, list) else [msgs]):
                    await self._dispatch(msg)

    async def _dispatch(self, msg: dict):
        t = msg.get("T")
        if t == "t":   # Trade
            sym   = msg.get("S", "")
            price = float(msg.get("p", 0) or 0)
            size  = int(msg.get("s", 0) or 0)
            conds = msg.get("c", [])
            # Alpaca does not provide explicit side in IEX feed — Tick Rule applied by FlowEngine
            if self._on_trade and sym and price > 0:
                self._on_trade(sym, price, size, conds)

        elif t == "q":  # Quote
            sym = msg.get("S", "")
            bid = float(msg.get("bp", 0) or 0)
            ask = float(msg.get("ap", 0) or 0)
            if self._on_quote and sym and bid > 0 and ask > 0:
                self._on_quote(sym, bid, ask)

        elif t == "error":
            logger.error(f"Alpaca WS error: {msg}")

    async def update_subscription(self, symbols: List[str]):
        """Update WebSocket subscription when universe changes."""
        if not self._ws:
            return
        try:
            new_syms = [s for s in symbols if s not in self._subscribed]
            if new_syms:
                await self._ws.send(json.dumps({
                    "action": "subscribe",
                    "trades": new_syms,
                    "quotes": new_syms,
                }))
                self._subscribed.update(new_syms)
                logger.info(f"Subscribed to {len(new_syms)} new symbols (total: {len(self._subscribed)})")
        except Exception as e:
            logger.warning(f"Subscription update failed: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # REST — Snapshots (price initialization only — NO volume classification)
    # ──────────────────────────────────────────────────────────────────────────

    async def get_snapshots(self, symbols: List[str]) -> dict:
        """
        Fetch REST snapshots for price initialization.
        Returns raw snapshot dicts keyed by symbol.
        Volume from snapshots is NOT used for CVD (no tick rule possible on aggregated data).
        """
        if not symbols:
            return {}

        session = self._get_session()
        result  = {}

        # Batch to avoid URL length limit
        batch_size = 100
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            try:
                async with session.get(
                    f"{_REST_BASE}/v2/stocks/snapshots",
                    headers=self._headers,
                    params={"symbols": ",".join(batch)},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result.update(data or {})
                    else:
                        body = await resp.text()
                        logger.error(f"Snapshot {resp.status}: {body[:120]}")
            except Exception as e:
                logger.error(f"Snapshot fetch error (batch {i}): {e}")

            await asyncio.sleep(0.05)

        return result

    async def get_most_actives(self, top: int = 1000) -> List[str]:
        """
        Fetch most-active US stocks from Alpaca screener.
        Returns symbol list — no slice limits applied here (caller decides).
        """
        session = self._get_session()
        try:
            # Shift to stable Data-V2 most-actives (Requires Market Data+ on some accounts)
            async with session.get(
                f"{_REST_BASE}/v2/stocks/most-actives",
                headers=self._headers,
                params={"top": top, "by": "volume"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    stocks = data.get("most_actives", [])
                    api_health["alpaca_rest"] = "READY"
                    return [s["symbol"] for s in stocks if s.get("symbol")]
                else:
                    body = await resp.text()
                    logger.error(f"Most-actives {resp.status}: {body[:120]}")
                    api_health["alpaca_rest"] = f"ERROR {resp.status}"
                    return []
        except Exception as e:
            logger.error(f"Most-actives fetch error: {e}")
            api_health["alpaca_rest"] = "OFFLINE"
            return []

    async def close(self):
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
