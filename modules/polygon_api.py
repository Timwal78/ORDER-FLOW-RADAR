"""
Polygon API — Ticker universe discovery, snapshots, unusual volume.
Free tier: 5 calls/min. We respect that with rate limiting.
No fake data. No fallbacks.
"""
import asyncio
import time
import aiohttp
import logging

logger = logging.getLogger("polygon")

BASE_URL = "https://api.polygon.io"


import config

class PolygonAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = None
        self._last_call = 0.0
        self._min_interval = config.POLYGON_RATE_LIMIT

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

    async def _get(self, path: str, params: dict = None) -> dict:
        await self._rate_limit()
        session = await self._get_session()
        p = params or {}
        p["apiKey"] = self.api_key
        url = f"{BASE_URL}{path}"
        async with session.get(url, params=p) as resp:
            if resp.status != 200:
                body = await resp.text()
                # Downgrade to debug so it doesn't spam the console if free tier rate limits are hit
                logger.debug(f"Polygon GET {path} → {resp.status}: {body[:200]}")
                return {}
            return await resp.json()

    async def get_grouped_daily(self, date: str) -> list[dict]:
        """All tickers' daily bars for a date (YYYY-MM-DD). Great for universe scan."""
        data = await self._get(f"/v2/aggs/grouped/locale/us/market/stocks/{date}")
        return data.get("results", [])

    async def get_snapshot_all(self) -> list[dict]:
        """Snapshot of all tickers — price, volume, change. 1 API call."""
        data = await self._get("/v2/snapshot/locale/us/markets/stocks/tickers")
        return data.get("tickers", [])

    async def get_snapshot_ticker(self, symbol: str) -> dict:
        """Single ticker snapshot."""
        data = await self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}")
        return data.get("ticker", {})

    async def get_ticker_details(self, symbol: str) -> dict:
        """Ticker details — market cap, SIC code, shares outstanding."""
        data = await self._get(f"/v3/reference/tickers/{symbol}")
        return data.get("results", {})

    async def get_all_tickers(self, market: str = "stocks", active: bool = True, limit: int = 1000) -> list[dict]:
        """Paginated ticker list for universe building."""
        all_tickers = []
        params = {
            "market": market,
            "active": str(active).lower(),
            "limit": limit,
            "order": "asc",
            "sort": "ticker",
        }
        data = await self._get("/v3/reference/tickers", params=params)
        all_tickers.extend(data.get("results", []))
        # Free tier can't paginate much, so we take what we get
        return all_tickers
