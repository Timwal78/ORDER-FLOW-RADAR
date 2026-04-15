"""
Order Flow Radar™ — Sentiment Engine
ScriptMasterLabs™

Fetches and caches News Sentiment from Alpha Vantage.
Designed for Free Tier (25 calls/day) with aggressive caching.
"""
import asyncio
import logging
import time
from typing import Dict, Optional

import aiohttp
import config

logger = logging.getLogger("sentiment_engine")

_BASE_URL = "https://www.alphavantage.co/query"

class SentimentEngine:
    def __init__(self):
        self._key = config.ALPHA_VANTAGE_KEY
        self._cache: Dict[str, Dict] = {} # ticker: {score: float, expiry: float}
        self._session: Optional[aiohttp.ClientSession] = None
        self._calls_today = 0
        self._last_reset = time.time()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _reset_limits(self):
        if time.time() - self._last_reset > 86400:
            self._calls_today = 0
            self._last_reset = time.time()

    async def get_sentiment(self, symbol: str) -> float:
        """
        Get sentiment score for a symbol (-1.0 to 1.0).
        Aggressively cached for 4 hours to respect 25 calls/day limit.
        """
        self._reset_limits()
        
        # 1. Check Cache
        cached = self._cache.get(symbol)
        if cached and time.time() < cached["expiry"]:
            return cached["score"]

        # 2. Check Daily Limit
        if self._calls_today >= 25:
            logger.warning("Alpha Vantage free tier limit reached for today (25/day).")
            return 0.0

        if not self._key:
            return 0.0

        try:
            logger.info(f"Sentiment lookup: {symbol} (Calls today: {self._calls_today})")
            async with self._get_session().get(
                _BASE_URL,
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers":  symbol.upper(),
                    "apikey":   self._key
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Alpha Vantage returns sentiment in "sentiment_score" field of feed items
                    feed = data.get("feed", [])
                    if not feed:
                        # Fallback if no specific news found - search global
                        return 0.0

                    # Average the first 5 news items most relevant to this ticker
                    scores = []
                    for item in feed[:5]:
                        ticker_sentiment = next(
                            (s for s in item.get("ticker_sentiment", []) if s["ticker"] == symbol.upper()), 
                            None
                        )
                        if ticker_sentiment:
                            scores.append(float(ticker_sentiment.get("ticker_sentiment_score", 0)))
                    
                    avg_score = sum(scores) / len(scores) if scores else 0.0
                    
                    # Cache for 4 hours
                    self._cache[symbol] = {
                        "score": avg_score,
                        "expiry": time.time() + 14400 
                    }
                    self._calls_today += 1
                    return avg_score
                else:
                    logger.error(f"Alpha Vantage sentiment failed: {resp.status}")
                    return 0.0
        except Exception as e:
            logger.error(f"Sentiment engine error for {symbol}: {e}")
            return 0.0

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
