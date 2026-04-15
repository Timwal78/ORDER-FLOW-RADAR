"""
Order Flow Radar™ — Polygon API Client
ScriptMasterLabs™

Handles:
  - OHLCV bars (for technical indicators)
  - Gainers/Losers (universe discovery — no slice limits)
  - Ticker details (market cap filtering)
  - No mock data. If Polygon fails → log error, return empty, continue.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

import aiohttp

import config

logger = logging.getLogger("polygon_api")

_BASE = "https://api.polygon.io"

_TF_MAP = {
    "1m":  (1, "minute"),
    "5m":  (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h":  (1, "hour"),
    "4h":  (4, "hour"),
    "1d":  (1, "day"),
    "1w":  (1, "week"),
}


class PolygonAPI:
    def __init__(self, api_key: str):
        self._key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get(self, url: str, params: dict = None) -> Optional[dict]:
        p = {"apiKey": self._key}
        if params:
            p.update(params)
        try:
            async with self._get_session().get(
                url, params=p, timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                body = await resp.text()
                logger.error(f"Polygon {resp.status} {url}: {body[:120]}")
                return None
        except Exception as e:
            logger.error(f"Polygon request error {url}: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # OHLCV Bars
    # ──────────────────────────────────────────────────────────────────────────

    async def get_bars(
        self, symbol: str, timeframe: str = "1d", limit: int = 200
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars for a symbol via Polygon Aggregates.
        Returns list of bar dicts: {o, h, l, c, v, t}
        """
        mult, span = _TF_MAP.get(timeframe, (1, "day"))
        end   = date.today().isoformat()
        start = (date.today() - timedelta(days=365)).isoformat()

        data = await self._get(
            f"{_BASE}/v2/aggs/ticker/{symbol.upper()}/range/{mult}/{span}/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": limit},
        )
        if not data or not data.get("results"):
            return []
        return data["results"]

    # ──────────────────────────────────────────────────────────────────────────
    # Universe Discovery — Manifesto Rule 2: NO top-N limits applied here
    # ──────────────────────────────────────────────────────────────────────────

    async def get_gainers(self) -> List[str]:
        """Fetch today's top gainers. Returns full list — no slice."""
        data = await self._get(
            f"{_BASE}/v2/snapshot/locale/us/markets/stocks/gainers",
            {"include_otc": "false"},
        )
        if not data:
            return []
        tickers = data.get("tickers", [])
        return [t["ticker"] for t in tickers if t.get("ticker")]

    async def get_losers(self) -> List[str]:
        """Fetch today's top losers. Returns full list — no slice."""
        data = await self._get(
            f"{_BASE}/v2/snapshot/locale/us/markets/stocks/losers",
            {"include_otc": "false"},
        )
        if not data:
            return []
        tickers = data.get("tickers", [])
        return [t["ticker"] for t in tickers if t.get("ticker")]

    async def get_ticker_details(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch ticker fundamentals (market cap, name, etc.)."""
        data = await self._get(f"{_BASE}/v3/reference/tickers/{symbol.upper()}")
        if not data:
            return None
        return data.get("results")

    async def get_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get single-symbol real-time snapshot."""
        data = await self._get(
            f"{_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}"
        )
        if not data:
            return None
        return data.get("ticker")

    async def get_last_trade(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get most recent trade for a symbol."""
        data = await self._get(f"{_BASE}/v2/last/trade/{symbol.upper()}")
        if not data:
            return None
        return data.get("results")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
