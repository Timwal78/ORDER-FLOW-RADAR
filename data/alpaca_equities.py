"""
Alpaca Equities REST API Handler
Polls latest bars, quotes, snapshots, and VWAP data for equity symbols.
"""

import asyncio
import logging
from typing import Dict, List, Optional

import aiohttp
import pandas as pd

import config

logger = logging.getLogger(__name__)


class AlpacaEquitiesHandler:
    """
    Async HTTP handler for Alpaca equity data via REST API polling.
    Maintains DataFrames for bars at multiple timeframes and quotes.
    """

    def __init__(self):
        self.api_key = config.ALPACA_API_KEY
        self.secret_key = config.ALPACA_SECRET_KEY
        self.base_url = config.ALPACA_STOCK_DATA
        self.symbols = config.EQUITY_SYMBOLS
        self.poll_seconds = config.EQUITY_POLL_SECONDS

        # Headers for Alpaca API
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

        # Data storage: {symbol: {timeframe: DataFrame}}
        self.bars: Dict[str, Dict[str, pd.DataFrame]] = {
            symbol: {tf: pd.DataFrame() for tf in ["1min", "5min", "1h", "1d"]}
            for symbol in self.symbols
        }

        # Quotes storage: {symbol: {"bid": float, "ask": float, "mid": float, ...}}
        self.quotes: Dict[str, Dict] = {symbol: {} for symbol in self.symbols}

        # Snapshots storage: {symbol: {snapshot data}}
        self.snapshots: Dict[str, Dict] = {symbol: {} for symbol in self.symbols}

        # VWAP cache
        self.vwap_cache: Dict[str, float] = {}
        self.daily_volume_cache: Dict[str, float] = {}

    async def start(self) -> None:
        """Start polling loop for equity data."""
        while True:
            try:
                await self._poll_all()
            except Exception as e:
                logger.error(f"Error in equities polling loop: {e}")
            finally:
                await asyncio.sleep(self.poll_seconds)

    async def _poll_all(self) -> None:
        """Poll all symbols for bars, quotes, and snapshots."""
        async with aiohttp.ClientSession() as session:
            # Create concurrent tasks for all symbols
            tasks = [
                self._fetch_symbol_data(session, symbol)
                for symbol in self.symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Error fetching data for {self.symbols[i]}: {result}"
                    )

    async def _fetch_symbol_data(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch bars, quotes, and snapshot for a single symbol."""
        try:
            # Fetch bars for all timeframes concurrently
            bar_tasks = [
                self._fetch_bars(session, symbol, tf)
                for tf in ["1min", "5min", "1h", "1d"]
            ]
            await asyncio.gather(*bar_tasks, return_exceptions=True)

            # Fetch quote and snapshot
            await self._fetch_quote(session, symbol)
            await self._fetch_snapshot(session, symbol)

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")

    async def _fetch_bars(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        timeframe: str,
    ) -> None:
        """Fetch latest bars for a symbol and timeframe."""
        try:
            # Map timeframe to Alpaca format
            tf_map = {"1min": "1Min", "5min": "5Min", "1h": "1Hour", "1d": "1Day"}
            alpaca_tf = tf_map.get(timeframe, "1Min")

            url = f"{self.base_url}/bars"
            params = {
                "symbols": symbol,
                "timeframe": alpaca_tf,
                "limit": 500,  # Get last 500 bars
            }

            async with session.get(
                url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    bars_list = data.get("bars", {}).get(symbol, [])

                    if bars_list:
                        df = pd.DataFrame(bars_list)
                        # Ensure proper dtypes
                        for col in ["o", "h", "l", "c", "v"]:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col], errors="coerce")
                        self.bars[symbol][timeframe] = df
                        logger.debug(f"Fetched {len(df)} bars for {symbol} {timeframe}")
                else:
                    logger.warning(
                        f"Failed to fetch bars for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching bars for {symbol} {timeframe}")
        except Exception as e:
            logger.error(f"Error fetching bars for {symbol} {timeframe}: {e}")

    async def _fetch_quote(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch latest quote (bid/ask) for symbol."""
        try:
            url = f"{self.base_url}/quotes/latest"
            params = {"symbols": symbol}

            async with session.get(
                url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    quote = data.get("quotes", {}).get(symbol, {})

                    if quote:
                        bid = float(quote.get("bid_price", 0))
                        ask = float(quote.get("ask_price", 0))
                        mid = (bid + ask) / 2 if bid and ask else 0

                        self.quotes[symbol] = {
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "bid_size": float(quote.get("bid_size", 0)),
                            "ask_size": float(quote.get("ask_size", 0)),
                            "timestamp": quote.get("timestamp"),
                        }
                else:
                    logger.warning(f"Failed to fetch quote for {symbol}: {resp.status}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching quote for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")

    async def _fetch_snapshot(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch daily snapshot (VWAP, volume, etc.) for symbol."""
        try:
            url = f"{self.base_url}/snapshots"
            params = {"symbols": symbol}

            async with session.get(
                url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    snapshot = data.get("snapshots", {}).get(symbol, {})

                    if snapshot:
                        # Extract VWAP and daily volume
                        daily_data = snapshot.get("dailyBar", {})
                        vwap = float(daily_data.get("vw", 0))
                        volume = float(daily_data.get("v", 0))

                        self.snapshots[symbol] = {
                            "vwap": vwap,
                            "daily_open": float(daily_data.get("o", 0)),
                            "daily_high": float(daily_data.get("h", 0)),
                            "daily_low": float(daily_data.get("l", 0)),
                            "daily_close": float(daily_data.get("c", 0)),
                            "daily_volume": volume,
                        }

                        self.vwap_cache[symbol] = vwap
                        self.daily_volume_cache[symbol] = volume
                else:
                    logger.warning(
                        f"Failed to fetch snapshot for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching snapshot for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching snapshot for {symbol}: {e}")

    def get_bars(
        self, symbol: str, timeframe: str, n: int = 100
    ) -> Optional[pd.DataFrame]:
        """Return last n bars for symbol and timeframe."""
        if symbol not in self.bars or timeframe not in self.bars[symbol]:
            return None

        df = self.bars[symbol][timeframe]
        if df.empty:
            return None

        return df.tail(n).copy()

    def get_vwap(self, symbol: str) -> Optional[float]:
        """Return current daily VWAP for symbol."""
        return self.vwap_cache.get(symbol)

    def get_daily_volume(self, symbol: str) -> Optional[float]:
        """Return current daily volume for symbol."""
        return self.daily_volume_cache.get(symbol)

    def get_quote(self, symbol: str) -> Dict:
        """Return current bid/ask quote for symbol."""
        return self.quotes.get(symbol, {})

    def get_snapshot(self, symbol: str) -> Dict:
        """Return daily snapshot data for symbol."""
        return self.snapshots.get(symbol, {})
