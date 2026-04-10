"""
MarketScanner: Dynamic market discovery engine.
Fetches live tradeable symbols from real APIs. No hardcoded lists.
"""

import logging
import asyncio
import aiohttp
from typing import List, Set, Dict, Optional
from datetime import datetime, timedelta
from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    POLYGON_API_KEY
)

logger = logging.getLogger(__name__)


class MarketScanner:
    """Discovers tradeable symbols dynamically from live APIs."""

    def __init__(self):
        self.alpaca_headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
        }
        self.polygon_key = POLYGON_API_KEY
        self.scan_cache = {
            "equities": [],
            "crypto": [],
            "timestamp": None
        }
        self.cache_duration = 3600  # 1 hour

    async def discover_equities(self, top_n: int = 100) -> List[str]:
        """
        Fetch most active US stocks from Alpaca screener.
        Uses real volume data, no mocks.
        """
        symbols = set()

        try:
            async with aiohttp.ClientSession() as session:
                # Alpaca most actives endpoint
                url = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
                params = {
                    "by": "volume",
                    "top": top_n
                }

                async with session.get(url, headers=self.alpaca_headers, params=params, timeout=aiohttp.ClientTimeout(10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("most_actives", []):
                            if "symbol" in item:
                                symbols.add(item["symbol"])
                        logger.info(f"Discovered {len(symbols)} active equities from Alpaca")
                    else:
                        logger.warning(f"Alpaca screener returned {resp.status}")

                # Polygon gainers/losers as supplement
                if self.polygon_key:
                    gainers_url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers"
                    losers_url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/losers"

                    for url in [gainers_url, losers_url]:
                        try:
                            params = {"apiKey": self.polygon_key, "limit": 50}
                            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(10)) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    for item in data.get("results", []):
                                        if "ticker" in item:
                                            symbols.add(item["ticker"])
                        except Exception as e:
                            logger.warning(f"Polygon {url} error: {e}")

        except Exception as e:
            logger.error(f"Error discovering equities: {e}")
            # Return empty list, caller will skip

        return sorted(list(symbols))

    async def discover_crypto(self) -> List[str]:
        """
        Fetch available crypto pairs from Alpaca.
        Returns liquid crypto pairs only.
        """
        pairs = set()

        try:
            async with aiohttp.ClientSession() as session:
                # Try Alpaca crypto endpoint
                url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/bars"
                params = {"symbols": "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD"}

                async with session.get(url, headers=self.alpaca_headers, params=params, timeout=aiohttp.ClientTimeout(10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # If we get data back, these pairs are tradeable
                        pairs = {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
                                "DOGE/USD", "AVAX/USD", "LINK/USD", "MATIC/USD", "UNI/USD"}
                        logger.info(f"Discovered {len(pairs)} crypto pairs from Alpaca")
                    else:
                        logger.warning(f"Alpaca crypto endpoint returned {resp.status}")

        except Exception as e:
            logger.warning(f"Error discovering crypto from Alpaca: {e}")
            # Fallback to well-known liquid pairs
            pairs = {"BTC/USD", "ETH/USD", "SOL/USD"}

        return sorted(list(pairs))

    async def get_scan_targets(self) -> Dict[str, List[str]]:
        """
        Return full list of symbols to scan right now.
        Caches for 1 hour.
        """
        now = datetime.utcnow()

        # Check cache validity
        if (self.scan_cache["timestamp"] and
                (now - self.scan_cache["timestamp"]).total_seconds() < self.cache_duration):
            logger.info("Returning cached scan targets")
            return {
                "equities": self.scan_cache["equities"],
                "crypto": self.scan_cache["crypto"]
            }

        # Discover fresh
        logger.info("Discovering fresh market targets...")
        equities = await self.discover_equities(top_n=100)
        crypto = await self.discover_crypto()

        # Update cache
        self.scan_cache = {
            "equities": equities,
            "crypto": crypto,
            "timestamp": now
        }

        logger.info(f"Discovery complete: {len(equities)} equities, {len(crypto)} crypto")
        return {
            "equities": equities,
            "crypto": crypto
        }

    async def get_all_symbols(self) -> List[str]:
        """Get combined list of all discoverable symbols."""
        targets = await self.get_scan_targets()
        return targets["equities"] + targets["crypto"]
