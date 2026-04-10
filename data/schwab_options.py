"""
Charles Schwab Options Flow Handler
OAuth2 token management, options chain polling, unusual activity detection.
"""

import asyncio
import base64
import logging
import time
from typing import Dict, List, Optional, Tuple

import aiohttp

import config

logger = logging.getLogger(__name__)


class SchwabOptionsHandler:
    """
    Async HTTP handler for Schwab options data.
    Manages OAuth2 token refresh and polls options chains during market hours.
    """

    def __init__(self):
        self.app_key = config.SCHWAB_APP_KEY
        self.app_secret = config.SCHWAB_APP_SECRET
        self.refresh_token = config.SCHWAB_REFRESH_TOKEN
        self.token_url = config.SCHWAB_TOKEN_URL
        self.base_url = config.SCHWAB_BASE
        self.symbols = getattr(config, 'EQUITY_SYMBOLS', [])
        self.poll_seconds = config.SCHWAB_POLL_SECONDS

        # Token management
        self.access_token = None
        self.token_expiry_time = 0

        # Data caches (will be dynamically updated by orchestrator)
        self.options_chains: Dict[str, Dict] = {}
        self.unusual_activity: Dict[str, List[Dict]] = {}
        self.pcr_ratios: Dict[str, float] = {}
        self.options_flow: Dict[str, Dict] = {}

    async def start(self) -> None:
        """Start polling loop for options data (market hours only)."""
        while True:
            try:
                if self._is_market_hours():
                    await self._refresh_token_if_needed()
                    await self._poll_all_symbols()
                else:
                    logger.debug("Market closed, skipping options poll")
            except Exception as e:
                logger.error(f"Error in Schwab options polling loop: {e}")
            finally:
                await asyncio.sleep(self.poll_seconds)

    @staticmethod
    def _is_market_hours() -> bool:
        """Check if current time is during US market hours (9:30-16:00 ET, Mon-Fri)."""
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        # Convert to ET
        et = now.astimezone(
            datetime.timezone(datetime.timedelta(hours=-5))
        )  # Simplified, doesn't account for DST

        # Check if Monday-Friday (0=Mon, 4=Fri)
        if et.weekday() > 4:
            return False

        # Check if 9:30-16:00
        market_open = 9.5  # 9:30
        market_close = 16.0  # 16:00
        current_hour = et.hour + et.minute / 60

        return market_open <= current_hour < market_close

    async def _refresh_token_if_needed(self) -> None:
        """Refresh OAuth2 token if expired."""
        current_time = time.time()
        if self.access_token is None or current_time >= self.token_expiry_time:
            await self._get_access_token()

    async def _get_access_token(self) -> None:
        """Obtain new access token using refresh token."""
        try:
            # Encode credentials for basic auth
            credentials = f"{self.app_key}:{self.app_secret}"
            encoded_credentials = base64.b64encode(
                credentials.encode()
            ).decode()

            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            data = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.token_url,
                    headers=headers,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        self.access_token = result.get("access_token")
                        expires_in = result.get("expires_in", 1800)
                        self.token_expiry_time = time.time() + expires_in - 60

                        logger.info("Schwab access token refreshed")
                    else:
                        logger.error(
                            f"Failed to refresh Schwab token: {resp.status}"
                        )

        except Exception as e:
            logger.error(f"Error refreshing Schwab token: {e}")

    async def _poll_all_symbols(self) -> None:
        """Poll options chains for all symbols concurrently."""
        if not self.access_token:
            logger.warning("No Schwab access token available, skipping poll")
            return

        async with aiohttp.ClientSession() as session:
            tasks = [
                self._fetch_options_chain(session, symbol)
                for symbol in self.symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Error fetching options for {self.symbols[i]}: {result}"
                    )

    async def _fetch_options_chain(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> None:
        """Fetch options chain for symbol."""
        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}

            url = f"{self.base_url}/chains"
            params = {
                "symbol": symbol,
                "contractType": "ALL",
            }

            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.options_chains[symbol] = data

                    # Analyze chain for unusual activity
                    await self._analyze_chain(symbol, data)
                    logger.debug(f"Fetched options chain for {symbol}")
                else:
                    logger.warning(
                        f"Failed to fetch options chain for {symbol}: {resp.status}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching options chain for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")

    async def _analyze_chain(self, symbol: str, chain_data: Dict) -> None:
        """Analyze options chain for unusual activity."""
        try:
            unusual = []
            total_put_oi = 0
            total_call_oi = 0
            total_put_vol = 0
            total_call_vol = 0

            # Process call and put contracts
            for contract_list in [
                chain_data.get("callExpDateMap", {}),
                chain_data.get("putExpDateMap", {}),
            ]:
                is_put = contract_list == chain_data.get("putExpDateMap", {})

                for expiry, strike_map in contract_list.items():
                    for strike, contracts in strike_map.items():
                        for contract in contracts:
                            volume = float(contract.get("totalVolume", 0))
                            open_interest = float(contract.get("openInterest", 0))

                            # Track P/C ratio
                            if is_put:
                                total_put_vol += volume
                                total_put_oi += open_interest
                            else:
                                total_call_vol += volume
                                total_call_oi += open_interest

                            # Detect unusual volume (> 3x open interest)
                            if open_interest > 0 and volume > 3 * open_interest:
                                unusual.append(
                                    {
                                        "strike": strike,
                                        "expiry": expiry,
                                        "type": "PUT" if is_put else "CALL",
                                        "volume": volume,
                                        "open_interest": open_interest,
                                        "volume_oi_ratio": volume / open_interest,
                                    }
                                )

            self.unusual_activity[symbol] = unusual

            # Calculate put/call ratio
            total_vol = total_put_vol + total_call_vol
            if total_vol > 0:
                self.pcr_ratios[symbol] = total_put_vol / total_vol
                logger.debug(f"P/C ratio for {symbol}: {self.pcr_ratios[symbol]:.2f}")

            # Store flow data
            self.options_flow[symbol] = {
                "put_volume": total_put_vol,
                "call_volume": total_call_vol,
                "put_oi": total_put_oi,
                "call_oi": total_call_oi,
                "unusual_count": len(unusual),
            }

            if unusual:
                logger.info(
                    f"Found {len(unusual)} unusual options contracts for {symbol}"
                )

        except Exception as e:
            logger.error(f"Error analyzing options chain for {symbol}: {e}")

    def get_unusual_activity(self, symbol: str) -> List[Dict]:
        """Return list of unusual options activity for symbol."""
        return self.unusual_activity.get(symbol, [])

    def get_pcr(self, symbol: str) -> Optional[float]:
        """Return put/call ratio for symbol (0-1 range)."""
        pcr = self.pcr_ratios.get(symbol)
        return pcr if pcr and pcr > 0 else None

    def get_options_flow(self, symbol: str) -> Dict:
        """Return options flow summary for symbol."""
        return self.options_flow.get(symbol, {})
