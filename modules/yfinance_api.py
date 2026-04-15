"""
Order Flow Radar™ — Yahoo Finance Discovery Module
ScriptMasterLabs™

Institutional Scout (Source 4): 
Provides free, high-scale discovery of market movers.
Used to feed the 'Shadow Radar' when Alpaca/Polygon are hit by tier limits.
"""
import logging
import aiohttp
from typing import List

import random

logger = logging.getLogger("yfinance_api")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
]

# Yahoo's predefined screener IDs
GAINER_SCREENER = "day_gainers"
LOSER_SCREENER  = "day_losers"
MOST_ACTIVE     = "most_actives"

class YahooDiscovery:
    """
    Scouts Yahoo Finance for the absolute top market movers.
    Raw JSON access via direct query to ensure high reliability.
    """
    def __init__(self):
        self._url = "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved"
    
    async def get_top_movers(self, limit: int = 50) -> List[str]:
        """
        Combines Gainers, Losers, and Actives into a single scouting list.
        """
        discovered = set()
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com/gainers"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            # 1. Day Gainers
            discovered.update(await self._fetch_screener(session, GAINER_SCREENER, limit))
            # 2. Day Losers
            discovered.update(await self._fetch_screener(session, LOSER_SCREENER, limit))
            # 3. Most Actives
            discovered.update(await self._fetch_screener(session, MOST_ACTIVE, limit))
            
        return sorted(list(discovered))

    async def _fetch_screener(self, session: aiohttp.ClientSession, screener_id: str, limit: int) -> List[str]:
        params = {
            "formatted": "false",
            "scrIds": screener_id,
            "count": str(limit)
        }
        try:
            async with session.get(self._url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("finance", {}).get("result", [])
                    if results:
                        quotes = results[0].get("quotes", [])
                        return [q["symbol"] for q in quotes if "symbol" in q]
                else:
                    logger.warning(f"Yahoo {screener_id} failed: status {resp.status}")
        except Exception as e:
            logger.error(f"Yahoo {screener_id} error: {e}")
        return []
