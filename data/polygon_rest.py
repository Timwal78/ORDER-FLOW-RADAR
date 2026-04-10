"""
Polygon.io REST API Handler
Supplemental equity data source, polled with rate limit awareness for free tier.
"""

import asyncio
import logging
from collections import deque
from typing import Dict, List, Optional

import aiohttp

import config

logger = logging.getLogger(__name__)


class PolygonRestHandler:
    """
    Async HTTP handler for Polygon.io equity data.
    Respects free tier rate limits (5 calls/min, rotate symbols).
    """

    def __init__(self):
        self.api_key = config.POLYGON_API_KEY
        self.base_url = config.POLYGON_BASE
        self.symbols = config.EQUITY_SYMBOLS
        self.poll_seconds = config.EQUITY_POLL_SECONDS

        # Rate limit management: free tier = 5 calls/min
        # Space out calls by rotating through symbols
        self.symbol_queue = deque(self.symbols)
        self.calls_made_this_minute = 0
        self.last_reset_time = None

        # Data caches
        self.prev_close: Dict[str, Dict] = {}
        self.aggregates: Dict[str, Dict[str, List[Dict]]] = {
            symbol: {"1min": [], "5min": [], "1day": []}
            for symbol in self.symbols
        }
        self.ticker_details: Dict[str, Dict] = {}

    async def start(self) -> None:
        """Start polling loop for Polygon data."""
        while True:
            try:
                await self._poll_one_symbol()
            except Exception as e:
                logger.error(f"Error in Polygon polling loop: {e}")
            finally:
                # Space out calls: 5 calls/min = 12 seconds per call
                await asyncio.sleep(max(12, self.poll_seconds))

    async def _poll_one_symbol(self) -> None:
        """Poll one symbol from queue to respect rate limits."""
        if not self.symbol_queue:
            self.symbol_queue.extend(self.symbols)

        symbol = self.symbol_queue.popleft()

        async with aiohttp.ClientSession() as session:
            try:
                await self._fetch_prev_close(session, symbol)
                await asyncio.sleep(1)
                await self._fetch_aggregates(session, symbol, "minute", 100)
                await asyncio.sleep(1)
                await self._fetch_aggregates(session, symbol, "day", 30)

            except Exception as e:
                logger.error(f"Error polling Polygon for {symbol}: {e}")

    async def _fetch_prev_close(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch previous day close data for symbol."""
        try:
            url = f"{self.base_url}/v1/open-close/{symbol}/previous"
            params = {"adjusted": "true", "apiKey": self.api_key}

            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "OK":
                        self.prev_close[symbol] = {
                            "open": data.get("o"),
                            "high": data.get("h"),
                            "low": data.get("l"),
                            "close": data.get("c"),
                            "volume": data.get("v"),
                            "vwap": data.get("vw"),
                            "from": data.get("from"),
                        }
                        logger.debug(f"Fetched prev close for {symbol}")
                else:
                    logger.warning(
                        f"Failed to fetch prev close for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching prev close for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching prev close for {symbol}: {e}")

    async def _fetch_aggregates(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        timespan: str,
        limit: int = 100,
    ) -> None:
        """Fetch aggregates (bars) for symbol at given timespan."""
        try:
            # Map to aggregate key
            agg_key = {"minute": "1min", "day": "1day"}.get(timespan, "1min")

            url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/{timespan}"
            params = {
                "limit": limit,
                "sort": "desc",
                "apiKey": self.api_key,
            }

            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "OK":
                        results = data.get("results", [])
                        self.aggregates[symbol][agg_key] = results
                        logger.debug(
                            f"Fetched {len(results)} {timespan} aggregates for {symbol}"
                        )
                else:
                    logger.warning(
                        f"Failed to fetch aggregates for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching aggregates for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching aggregates for {symbol}: {e}")

    async def _fetch_ticker_details(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch ticker details for symbol."""
        try:
            url = f"{self.base_url}/v3/reference/tickers/{symbol}"
            params = {"apiKey": self.api_key}

            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "OK":
                        result = data.get("results", {})
                        self.ticker_details[symbol] = result
                        logger.debug(f"Fetched ticker details for {symbol}")
                else:
                    logger.warning(
                        f"Failed to fetch ticker details for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching ticker details for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching ticker details for {symbol}: {e}")

    def get_prev_close(self, symbol: str) -> Optional[Dict]:
        """Return previous close data for symbol."""
        return self.prev_close.get(symbol)

    def get_aggregates(
        self, symbol: str, timeframe: str, n: int = 50
    ) -> List[Dict]:
        """Return last n aggregates for symbol and timeframe."""
        aggs = self.aggregates.get(symbol, {}).get(timeframe, [])
        return aggs[:n] if aggs else []

    def get_ticker_details(self, symbol: str) -> Optional[Dict]:
        """Return ticker details for symbol."""
        return self.ticker_details.get(symbol)
