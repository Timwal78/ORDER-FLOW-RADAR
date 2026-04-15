"""
Order Flow Radar™ — Options Engine
ScriptMasterLabs™

Recommends specific trade structures based on real-time Schwab option chains.
Zero mock data. No hardcoded strikes. No expiry fallbacks.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional

import config
from modules.schwab_api import SchwabAPI

logger = logging.getLogger("options_engine")


class OptionsEngine:
    def __init__(self, schwab: SchwabAPI):
        self._schwab = schwab

    async def get_recommendations(self, symbol: str, direction: str) -> List[Dict[str, Any]]:
        """
        Fetch real option chain from Schwab and recommend the best 3 contracts.
        Filtering via config.py weights (Law 2 compliance).
        """
        if not self._schwab._is_configured():
            logger.warning(f"Schwab not configured. Skipping options rec for {symbol}")
            return []

        chain = await self._schwab.get_option_chain(symbol)
        if not chain:
            return []

        # Extract candidates based on institutional DTE and Delta ranges
        recs = self._schwab.extract_best_options(
            chain, 
            direction=direction, 
            n=config.MAX_OPTIONS_RESULTS
        )

        return recs
