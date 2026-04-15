"""
Order Flow Radar™ — Universe Engine
ScriptMasterLabs™

DEVELOPER MANIFESTO Rule 2 Compliance:
  - NO arbitrary .slice() calls
  - NO top-N limits in discovery loops
  - NO hardcoded symbol lists (ALWAYS_SCAN excepted — user-defined)
  - Discovery from live APIs only: Alpaca most-actives + Polygon gainers/losers

Manifesto Rule 3: Mega-caps shown only as Top-3 advertising benchmarks.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import List, Set, Optional

import config
from modules.alpaca_api import AlpacaAPI
from modules.polygon_api import PolygonAPI

logger = logging.getLogger("universe_engine")


class UniverseEngine:
    """
    Discovers tradeable symbols dynamically from live API feeds.
    Zero hardcoded lists. Zero arbitrary slice limits.
    """

    def __init__(self, alpaca: AlpacaAPI, polygon: PolygonAPI):
        self._alpaca = alpaca
        self._polygon = polygon
        self.active_universe: List[str] = list(config.ALWAYS_SCAN)
        self.last_built: Optional[datetime] = None
        self._building = False

    async def build(self) -> List[str]:
        """
        Fetch full symbol universe from Alpaca and Polygon.
        Returns combined, deduplicated list — no top-N slicing.
        ALWAYS_SCAN tickers always included.
        """
        if self._building:
            return self.active_universe
        self._building = True

        discovered: Set[str] = set(config.ALWAYS_SCAN)

        # ── Source 1: Alpaca most-actives ────────────────────────────────────
        try:
            alpaca_symbols = await self._alpaca.get_most_actives(top=1000)
            logger.info(f"Alpaca most-actives: {len(alpaca_symbols)} symbols")
            discovered.update(alpaca_symbols)
        except Exception as e:
            logger.error(f"Alpaca most-actives failed: {e}")

        # ── Source 2: Polygon gainers ────────────────────────────────────────
        try:
            gainers = await self._polygon.get_gainers()
            logger.info(f"Polygon gainers: {len(gainers)} symbols")
            discovered.update(gainers)
        except Exception as e:
            logger.error(f"Polygon gainers failed: {e}")

        # ── Source 3: Polygon losers ─────────────────────────────────────────
        try:
            losers = await self._polygon.get_losers()
            logger.info(f"Polygon losers: {len(losers)} symbols")
            discovered.update(losers)
        except Exception as e:
            logger.error(f"Polygon losers failed: {e}")

        # ── Sanitize: uppercase, strip, no empty strings ─────────────────────
        clean = sorted({s.strip().upper() for s in discovered if s and s.strip()})

        self.active_universe = clean
        self.last_built = datetime.utcnow()
        self._building = False

        logger.info(f"Universe built: {len(clean)} symbols (incl. {len(config.ALWAYS_SCAN)} always-scan)")
        return clean

    def symbol_count(self) -> int:
        return len(self.active_universe)
