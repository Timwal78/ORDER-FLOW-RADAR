"""
Schwab API — Real OAuth, real options chains, real greeks.
No mock data. No fallbacks. If auth fails, it says so.
"""
import time
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("schwab")

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
BASE_URL = "https://api.schwabapi.com/marketdata/v1"


class SchwabAPI:
    def __init__(self, app_key: str, app_secret: str, refresh_token: str, redirect_uri: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.refresh_token = refresh_token
        self.redirect_uri = redirect_uri
        self.access_token = ""
        self.token_expiry = 0.0
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _refresh_access_token(self):
        async with self._lock:
            if time.time() < self.token_expiry - 60:
                return
            session = await self._get_session()
            auth = aiohttp.BasicAuth(self.app_key, self.app_secret)
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }
            async with session.post(TOKEN_URL, auth=auth, data=data) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Token refresh failed ({resp.status}): {body}")
                    raise RuntimeError(f"Schwab token refresh failed: {resp.status}")
                result = await resp.json()
                self.access_token = result["access_token"]
                self.token_expiry = time.time() + result.get("expires_in", 1800)
                if "refresh_token" in result:
                    self.refresh_token = result["refresh_token"]
                logger.info("Schwab token refreshed OK")

    async def _get(self, path: str, params: dict = None) -> dict:
        await self._refresh_access_token()
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{BASE_URL}{path}"
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning(f"Schwab GET {path} → {resp.status}: {body[:200]}")
                return {}
            return await resp.json()

    async def get_quote(self, symbol: str) -> dict:
        """Single equity quote — last price, volume, etc."""
        data = await self._get(f"/quotes", params={"symbols": symbol, "fields": "quote"})
        return data.get(symbol, {}).get("quote", {})

    async def get_quotes_batch(self, symbols: list[str]) -> dict:
        """Batch quotes — up to 500 symbols per call."""
        results = {}
        for i in range(0, len(symbols), 500):
            batch = symbols[i:i+500]
            sym_str = ",".join(batch)
            data = await self._get("/quotes", params={"symbols": sym_str, "fields": "quote"})
            for sym, val in data.items():
                results[sym] = val.get("quote", {})
        return results

    async def get_options_chain(self, symbol: str, dte_min: int = 7, dte_max: int = 30) -> dict:
        """Full options chain with greeks. Real data only."""
        from_date = (datetime.now() + timedelta(days=dte_min)).strftime("%Y-%m-%d")
        to_date = (datetime.now() + timedelta(days=dte_max)).strftime("%Y-%m-%d")
        params = {
            "symbol": symbol,
            "contractType": "ALL",
            "includeUnderlyingQuote": "TRUE",
            "range": "ALL",
            "fromDate": from_date,
            "toDate": to_date,
        }
        return await self._get("/chains", params=params)

    async def get_movers(self, index: str = "$SPX", direction: str = "up", change_type: str = "percent") -> list:
        """Market movers — top gainers/losers."""
        data = await self._get(f"/movers/{index}", params={
            "direction": direction,
            "change": change_type,
        })
        return data.get("screeners", [])
