"""
Order Flow Radar™ — Schwab API Client
ScriptMasterLabs™

Handles:
  - OAuth token refresh (using stored refresh token)
  - Options chains (real strikes, DTE, delta, theta, OI)
  - No hardcoded strikes or expiry limits (Manifesto Rule 2: fetch entire chain)
"""
from __future__ import annotations
import asyncio
import base64
import logging
import time
from typing import Optional, Dict, Any, List

import aiohttp

import config

logger = logging.getLogger("schwab_api")

_AUTH_URL = "https://api.schwabapi.com/v1/oauth/token"
_MARKET_BASE = "https://api.schwabapi.com/marketdata/v1"


class SchwabAPI:
    def __init__(self, app_key: str, app_secret: str, refresh_token: str, redirect_uri: str):
        self._app_key      = app_key
        self._app_secret   = app_secret
        self._refresh_token = refresh_token
        self._redirect_uri  = redirect_uri
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _is_configured(self) -> bool:
        return bool(self._app_key and self._app_secret and self._refresh_token)

    async def _ensure_token(self) -> bool:
        """Refresh access token if expired or missing. Returns True if token is valid."""
        if not self._is_configured():
            return False
        if self._access_token and time.time() < self._token_expires_at - 60:
            return True

        creds = base64.b64encode(
            f"{self._app_key}:{self._app_secret}".encode()
        ).decode()
        try:
            async with self._get_session().post(
                _AUTH_URL,
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": self._refresh_token,
                    "redirect_uri":  self._redirect_uri,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._access_token     = data["access_token"]
                    self._token_expires_at = time.time() + data.get("expires_in", 1800)
                    logger.info("Schwab token refreshed")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Schwab token refresh failed {resp.status}: {body[:120]}")
                    return False
        except Exception as e:
            logger.error(f"Schwab token refresh error: {e}")
            return False

    async def get_option_chain(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch complete option chain for a symbol.
        Manifesto Rule 2: NO hardcoded strike or expiry limits — fetch the entire chain.
        """
        if not await self._ensure_token():
            return None
        try:
            async with self._get_session().get(
                f"{_MARKET_BASE}/chains",
                headers={"Authorization": f"Bearer {self._access_token}"},
                params={
                    "symbol":         symbol.upper(),
                    "contractType":   "ALL",
                    "includeUnderlyingQuote": "true",
                    "strategy":       "SINGLE",
                    "range":          "ALL",   # Full chain, no strike limits
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                body = await resp.text()
                logger.error(f"Option chain {resp.status} for {symbol}: {body[:120]}")
                return None
        except Exception as e:
            logger.error(f"Option chain fetch error {symbol}: {e}")
            return None

    def extract_best_options(
        self, chain_data: dict, direction: str, n: int = None
    ) -> List[Dict]:
        """
        Extract top options recommendations from a chain based on signal direction.
        Filters by config DTE and delta ranges — no magic numbers.
        direction: 'LONG' → calls, 'SHORT' → puts
        """
        if n is None:
            n = config.MAX_OPTIONS_RESULTS

        option_type = "callExpDateMap" if direction == "LONG" else "putExpDateMap"
        chain_map = chain_data.get(option_type, {})

        candidates = []
        for expiry_key, strikes in chain_map.items():
            # expiry_key format: "2025-01-17:30" (date:DTE)
            parts = expiry_key.split(":")
            if len(parts) < 2:
                continue
            try:
                dte = int(parts[1])
            except ValueError:
                continue

            if not (config.PREFERRED_DTE_MIN <= dte <= config.PREFERRED_DTE_MAX):
                continue

            for strike_str, contracts in strikes.items():
                for contract in contracts:
                    delta = abs(float(contract.get("delta", 0) or 0))
                    if not (config.PREFERRED_DELTA_MIN <= delta <= config.PREFERRED_DELTA_MAX):
                        continue
                    candidates.append({
                        "symbol":       contract.get("symbol", ""),
                        "strike":       float(contract.get("strikePrice", 0)),
                        "expiration":   parts[0],
                        "dte":          dte,
                        "delta":        delta,
                        "theta":        float(contract.get("theta", 0) or 0),
                        "open_interest": int(contract.get("openInterest", 0) or 0),
                        "bid":          float(contract.get("bid", 0) or 0),
                        "ask":          float(contract.get("ask", 0) or 0),
                        "mid":          float(contract.get("mark", 0) or 0),
                        "volume":       int(contract.get("totalVolume", 0) or 0),
                        "direction":    direction,
                    })

        # Sort by delta proximity to center of preferred range, then by OI
        target_delta = (config.PREFERRED_DELTA_MIN + config.PREFERRED_DELTA_MAX) / 2
        candidates.sort(key=lambda x: (abs(x["delta"] - target_delta), -x["open_interest"]))
        return candidates[:n]

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
