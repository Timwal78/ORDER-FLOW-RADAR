"""
Alpha Vantage Technical Indicators Handler
Polls technical indicators and market sentiment with aggressive caching.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

import aiohttp

import config

logger = logging.getLogger(__name__)


class AlphaVantageHandler:
    """
    Async HTTP handler for Alpha Vantage technical indicators.
    Aggressive caching to respect free tier (25 calls/day).
    """

    def __init__(self):
        self.api_key = config.ALPHA_VANTAGE_KEY
        self.base_url = config.ALPHA_VANTAGE_BASE
        self.symbols = config.EQUITY_SYMBOLS
        self.poll_seconds = config.ALPHA_POLL_SECONDS

        # Cache management: {symbol: {metric: (value, timestamp)}}
        self.rsi_cache: Dict[str, Tuple[Optional[float], float]] = {
            symbol: (None, 0) for symbol in self.symbols
        }
        self.macd_cache: Dict[str, Tuple[Optional[Dict], float]] = {
            symbol: (None, 0) for symbol in self.symbols
        }
        self.sma_cache: Dict[str, Dict[int, Tuple[Optional[float], float]]] = {
            symbol: {50: (None, 0), 200: (None, 0)} for symbol in self.symbols
        }
        self.sentiment_cache: Dict[str, Tuple[Optional[Dict], float]] = {
            symbol: (None, 0) for symbol in self.symbols
        }

        # Call tracking to respect free tier limits
        self.calls_made = 0
        self.last_reset_time = time.time()
        self.daily_call_limit = 25

        # Symbol rotation for spreading calls
        self.current_symbol_idx = 0

    async def start(self) -> None:
        """Start polling loop for Alpha Vantage data."""
        while True:
            try:
                await self._poll_one_symbol()
            except Exception as e:
                logger.error(f"Error in Alpha Vantage polling loop: {e}")
            finally:
                # Spread out calls: 25/day = ~1 call per 3456 seconds
                # Use poll_seconds to allow faster development iteration
                await asyncio.sleep(self.poll_seconds)

    async def _poll_one_symbol(self) -> None:
        """Poll one symbol, rotating through the list."""
        if not self.symbols:
            return

        # Track daily call limit
        current_time = time.time()
        if current_time - self.last_reset_time > 86400:  # 24 hours
            self.calls_made = 0
            self.last_reset_time = current_time

        if self.calls_made >= self.daily_call_limit:
            logger.warning("Alpha Vantage daily call limit reached, skipping poll")
            return

        # Rotate through symbols
        symbol = self.symbols[self.current_symbol_idx % len(self.symbols)]
        self.current_symbol_idx += 1

        async with aiohttp.ClientSession() as session:
            try:
                # Check cache freshness (cache for 5 minutes = 300 seconds)
                cache_ttl = 300

                if self._is_stale(self.rsi_cache[symbol], cache_ttl):
                    await self._fetch_rsi(session, symbol)
                    self.calls_made += 1

                # Space out calls within a symbol poll
                if self.calls_made < self.daily_call_limit:
                    await asyncio.sleep(1)

                if self._is_stale(self.macd_cache[symbol], cache_ttl):
                    await self._fetch_macd(session, symbol)
                    self.calls_made += 1

                await asyncio.sleep(1)

                if self.calls_made < self.daily_call_limit:
                    if self._is_stale(self.sma_cache[symbol][50], cache_ttl):
                        await self._fetch_sma(session, symbol, 50)
                        self.calls_made += 1

                await asyncio.sleep(1)

                if self.calls_made < self.daily_call_limit:
                    if self._is_stale(self.sma_cache[symbol][200], cache_ttl):
                        await self._fetch_sma(session, symbol, 200)
                        self.calls_made += 1

            except Exception as e:
                logger.error(f"Error polling Alpha Vantage for {symbol}: {e}")

    @staticmethod
    def _is_stale(cached: Tuple, ttl: int) -> bool:
        """Check if cache entry is stale (older than ttl seconds)."""
        value, timestamp = cached
        return value is None or (time.time() - timestamp) > ttl

    async def _fetch_rsi(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch RSI(14) for symbol."""
        try:
            params = {
                "function": "RSI",
                "symbol": symbol,
                "interval": "daily",
                "time_period": 14,
                "apikey": self.api_key,
            }

            async with session.get(
                self.base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "Technical Analysis: RSI" in data:
                        rsi_data = data["Technical Analysis: RSI"]
                        # Get most recent value
                        latest_key = next(iter(rsi_data.keys()))
                        latest_rsi = float(rsi_data[latest_key]["RSI"])
                        self.rsi_cache[symbol] = (latest_rsi, time.time())
                        logger.debug(f"Fetched RSI for {symbol}: {latest_rsi}")
                    else:
                        logger.warning(f"No RSI data in response for {symbol}")
                else:
                    logger.warning(f"Failed to fetch RSI for {symbol}: {resp.status}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching RSI for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching RSI for {symbol}: {e}")

    async def _fetch_macd(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch MACD(12,26,9) for symbol."""
        try:
            params = {
                "function": "MACD",
                "symbol": symbol,
                "interval": "daily",
                "fastperiod": 12,
                "slowperiod": 26,
                "signalperiod": 9,
                "apikey": self.api_key,
            }

            async with session.get(
                self.base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "Technical Analysis: MACD" in data:
                        macd_data = data["Technical Analysis: MACD"]
                        latest_key = next(iter(macd_data.keys()))
                        latest = macd_data[latest_key]

                        macd_dict = {
                            "macd": float(latest.get("MACD", 0)),
                            "signal": float(latest.get("MACD_Signal", 0)),
                            "histogram": float(latest.get("MACD_Hist", 0)),
                        }
                        self.macd_cache[symbol] = (macd_dict, time.time())
                        logger.debug(f"Fetched MACD for {symbol}")
                    else:
                        logger.warning(f"No MACD data in response for {symbol}")
                else:
                    logger.warning(f"Failed to fetch MACD for {symbol}: {resp.status}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching MACD for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching MACD for {symbol}: {e}")

    async def _fetch_sma(
        self, session: aiohttp.ClientSession, symbol: str, period: int
    ) -> None:
        """Fetch SMA for symbol and period."""
        try:
            params = {
                "function": "SMA",
                "symbol": symbol,
                "interval": "daily",
                "time_period": period,
                "apikey": self.api_key,
            }

            async with session.get(
                self.base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "Technical Analysis: SMA" in data:
                        sma_data = data["Technical Analysis: SMA"]
                        latest_key = next(iter(sma_data.keys()))
                        latest_sma = float(sma_data[latest_key]["SMA"])
                        self.sma_cache[symbol][period] = (latest_sma, time.time())
                        logger.debug(f"Fetched SMA({period}) for {symbol}: {latest_sma}")
                    else:
                        logger.warning(f"No SMA data in response for {symbol}")
                else:
                    logger.warning(
                        f"Failed to fetch SMA({period}) for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching SMA({period}) for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching SMA({period}) for {symbol}: {e}")

    async def _fetch_sentiment(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch market sentiment for symbol."""
        try:
            params = {
                "function": "NEWS_SENTIMENT",
                "tickers": symbol,
                "apikey": self.api_key,
            }

            async with session.get(
                self.base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "feed" in data:
                        feed = data["feed"]
                        # Aggregate sentiment from top articles
                        positive = sum(
                            1 for item in feed[:10]
                            if float(item.get("overall_sentiment_score", 0)) > 0.1
                        )
                        negative = sum(
                            1 for item in feed[:10]
                            if float(item.get("overall_sentiment_score", 0)) < -0.1
                        )

                        sentiment_dict = {
                            "positive_count": positive,
                            "negative_count": negative,
                            "article_count": min(len(feed), 10),
                        }
                        self.sentiment_cache[symbol] = (sentiment_dict, time.time())
                        logger.debug(f"Fetched sentiment for {symbol}")
                    else:
                        logger.warning(f"No sentiment data in response for {symbol}")
                else:
                    logger.warning(
                        f"Failed to fetch sentiment for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching sentiment for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching sentiment for {symbol}: {e}")

    def get_rsi(self, symbol: str) -> Optional[float]:
        """Return RSI(14) for symbol."""
        value, _ = self.rsi_cache.get(symbol, (None, 0))
        return value

    def get_macd(self, symbol: str) -> Optional[Dict]:
        """Return MACD values for symbol."""
        value, _ = self.macd_cache.get(symbol, (None, 0))
        return value

    def get_sma(self, symbol: str, period: int) -> Optional[float]:
        """Return SMA for symbol and period."""
        if symbol not in self.sma_cache:
            return None
        value, _ = self.sma_cache[symbol].get(period, (None, 0))
        return value

    def get_sentiment(self, symbol: str) -> Optional[Dict]:
        """Return sentiment data for symbol."""
        value, _ = self.sentiment_cache.get(symbol, (None, 0))
        return value
