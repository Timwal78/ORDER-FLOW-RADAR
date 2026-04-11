"""
Alpaca API — REST for asset universe + websocket for real-time trades/quotes.
Free tier: unlimited websocket for IEX data. No fake data.
"""
import asyncio
import json
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger("alpaca")

REST_BASE = "https://paper-api.alpaca.markets"
DATA_REST = "https://data.alpaca.markets"
WS_URL = "wss://stream.data.alpaca.markets/v2/iex"


class AlpacaAPI:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._session: aiohttp.ClientSession | None = None
        self._ws = None
        self._subscribers: dict[str, list] = {}  # symbol -> [callbacks]

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_active_assets(self) -> list[dict]:
        """All active US equities tradable on Alpaca. This IS the universe."""
        session = await self._get_session()
        url = f"{REST_BASE}/v2/assets"
        params = {"status": "active", "asset_class": "us_equity"}
        async with session.get(url, headers=self._headers(), params=params) as resp:
            if resp.status != 200:
                logger.warning(f"Alpaca assets → {resp.status}")
                return []
            return await resp.json()

    async def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 30) -> list[dict]:
        """Historical bars for a symbol."""
        session = await self._get_session()
        url = f"{DATA_REST}/v2/stocks/{symbol}/bars"
        params = {"timeframe": timeframe, "limit": limit, "adjustment": "split"}
        async with session.get(url, headers=self._headers(), params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("bars", [])

    async def get_latest_trades(self, symbols: list[str]) -> dict:
        """Latest trade for multiple symbols."""
        session = await self._get_session()
        url = f"{DATA_REST}/v2/stocks/trades/latest"
        params = {"symbols": ",".join(symbols)}
        async with session.get(url, headers=self._headers(), params=params) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            return data.get("trades", {})

    async def start_stream(self, symbols: list[str], on_trade=None, on_quote=None):
        """Connect to Alpaca IEX websocket for real-time trades/quotes."""
        session = await self._get_session()
        self._ws = await session.ws_connect(WS_URL)

        # Auth
        await self._ws.send_json({
            "action": "auth",
            "key": self.api_key,
            "secret": self.api_secret,
        })
        auth_resp = await self._ws.receive_json()
        logger.info(f"Alpaca WS auth: {auth_resp}")

        # Subscribe
        sub_msg = {"action": "subscribe"}
        if on_trade:
            sub_msg["trades"] = symbols
        if on_quote:
            sub_msg["quotes"] = symbols
        await self._ws.send_json(sub_msg)
        sub_resp = await self._ws.receive_json()
        logger.info(f"Alpaca WS subscribed: {len(symbols)} symbols")

        # Listen loop
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                events = json.loads(msg.data)
                for event in events:
                    t = event.get("T")
                    sym = event.get("S", "")
                    if t == "t" and on_trade:
                        await on_trade(sym, event)
                    elif t == "q" and on_quote:
                        await on_quote(sym, event)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                logger.warning("Alpaca WS closed/error, reconnecting in 5s...")
                await asyncio.sleep(5)
                await self.start_stream(symbols, on_trade, on_quote)
                return

    async def update_subscription(self, symbols: list[str], trades: bool = True, quotes: bool = True):
        """Update websocket subscription without reconnecting."""
        if self._ws and not self._ws.closed:
            sub_msg = {"action": "subscribe"}
            if trades:
                sub_msg["trades"] = symbols
            if quotes:
                sub_msg["quotes"] = symbols
            await self._ws.send_json(sub_msg)
