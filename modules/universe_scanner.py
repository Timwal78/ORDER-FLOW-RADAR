"""
Universe Scanner — Open flow, wide as APIs allow.
Builds dynamic watchlist from:
  1. Alpaca active assets (full universe)
  2. Polygon snapshots (volume anomalies)
  3. Schwab movers (top gainers/losers)
Filters out mega-caps to prevent AAPL/MSFT/GOOG from flooding signals.
Always includes ALWAYS_SCAN tickers (AMC, GME, etc).
"""
import asyncio
import logging
from datetime import datetime

import config

logger = logging.getLogger("universe")


class UniverseScanner:
    def __init__(self, schwab_api, polygon_api, alpaca_api):
        self.schwab = schwab_api
        self.polygon = polygon_api
        self.alpaca = alpaca_api
        self.active_universe: list[str] = []  # Current scan targets
        self._cap_cache: dict[str, float] = {}  # symbol -> market_cap
        self._last_rebuild = 0.0

    async def build_universe(self) -> list[str]:
        """
        Merge all sources into one scan list.
        Runs every ~5 min to keep the list fresh.
        """
        candidates: set[str] = set()

        # 1. Always-scan tickers
        for sym in config.ALWAYS_SCAN:
            candidates.add(sym)

        # 1a. Broad Equity Universe (S&P 500, DayTrade, Memes, Sectors)
        try:
            import scan_universe
            for sym in scan_universe.get_equity_universe():
                candidates.add(sym)
            logger.info(f"Loaded {len(scan_universe.get_equity_universe())} tickers from scan_universe.py")
        except Exception as e:
            logger.warning(f"Failed to load equity universe: {e}")

        # 1b. Alpaca most-actives screener — works even when Schwab is down
        try:
            import aiohttp
            headers = {
                "APCA-API-KEY-ID": self.alpaca.api_key,
                "APCA-API-SECRET-KEY": self.alpaca.api_secret,
            }
            async with aiohttp.ClientSession() as session:
                for sort_by in ["volume", "trades"]:
                    try:
                        url = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
                        params = {"by": sort_by, "top": 50}
                        async with session.get(url, headers=headers, params=params,
                                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for item in data.get("most_actives", []):
                                    sym = item.get("symbol", "")
                                    if sym:
                                        candidates.add(sym)
                                logger.info(f"Alpaca screener ({sort_by}): {len(data.get('most_actives', []))} symbols")
                    except Exception as e:
                        logger.warning(f"Alpaca screener ({sort_by}) error: {e}")
        except Exception as e:
            logger.warning(f"Alpaca screener failed: {e}")

        # 2. Schwab movers — top gainers + losers
        try:
            up = await self.schwab.get_movers("$SPX", "up", "percent")
            down = await self.schwab.get_movers("$SPX", "down", "percent")
            for item in up + down:
                sym = item.get("symbol", "")
                if sym:
                    candidates.add(sym)
            logger.info(f"Schwab movers: {len(up)} up, {len(down)} down")
        except Exception as e:
            logger.warning(f"Schwab movers failed: {e}")

        # 3. Schwab movers — other indices
        for idx in ["$DJI", "$COMPX"]:
            try:
                up2 = await self.schwab.get_movers(idx, "up", "percent")
                down2 = await self.schwab.get_movers(idx, "down", "percent")
                for item in up2 + down2:
                    sym = item.get("symbol", "")
                    if sym:
                        candidates.add(sym)
            except Exception:
                pass

        # 4. Polygon snapshot — find unusual volume
        try:
            snaps = await self.polygon.get_snapshot_all()
            for snap in snaps:
                ticker = snap.get("ticker", "")
                day = snap.get("day", {})
                prev = snap.get("prevDay", {})
                vol = day.get("v", 0)
                prev_vol = prev.get("v", 1)
                change_pct = abs(snap.get("todaysChangePerc", 0))
                # Unusual volume: 3x avg OR big % move
                if prev_vol > 0 and (vol / prev_vol > 3.0 or change_pct > 5.0):
                    candidates.add(ticker)
            logger.info(f"Polygon unusual volume scan: {len(snaps)} tickers checked")
        except Exception as e:
            logger.warning(f"Polygon snapshot failed: {e}")
            
        # 4b. Polygon Grouped Daily (Squeeze OS style massive discovery)
        try:
            from datetime import timedelta
            now = datetime.now() - timedelta(days=1)
            while now.weekday() >= 5:  # Skip weekends
                now -= timedelta(days=1)
            date_str = now.strftime('%Y-%m-%d')
            
            grouped = await self.polygon.get_grouped_daily(date_str)
            poly_added = 0
            for bar in grouped:
                sym = bar.get("T", "")
                vol = bar.get("v", 0)
                price = bar.get("c", 0)
                open_p = bar.get("o", 0)
                chg_pct = abs(((price - open_p) / open_p * 100)) if open_p > 0 else 0
                
                # Minimum 50k volume, price filters, and > 0.1% move
                if sym and vol >= 50000 and 0.10 <= price <= 50000 and chg_pct >= 0.1:
                    candidates.add(sym)
                    poly_added += 1
            logger.info(f"Polygon grouped daily ({date_str}): Added {poly_added} tickers")
        except Exception as e:
            logger.warning(f"Polygon grouped daily failed: {e}")

        # 5. Filter by market cap — if we can't verify cap, INCLUDE the symbol
        #    rather than blocking it. Empty universe is worse than a noisy one.
        filtered = set()
        skip_cap_check = (config.POLYGON_RATE_LIMIT == 0) or (len(candidates) > 500)
        
        for sym in candidates:
            if skip_cap_check:
                filtered.add(sym)
                continue
                
            cap = await self._get_market_cap(sym)
            if cap == 0:
                # Unknown cap — include it (Polygon may be down)
                filtered.add(sym)
                continue
            if cap > config.LARGE_CAP_CEILING and sym not in config.ALWAYS_SCAN:
                continue  # Skip mega-caps
            if cap < config.MIN_MARKET_CAP and sym not in config.ALWAYS_SCAN:
                continue  # Skip micro-caps
            filtered.add(sym)

        # Always include forced tickers
        for sym in config.ALWAYS_SCAN:
            filtered.add(sym)

        self.active_universe = sorted(filtered)
        logger.info(f"Universe built: {len(self.active_universe)} tickers active")
        return self.active_universe

    async def _get_market_cap(self, symbol: str) -> float:
        """Get market cap, cached to avoid burning API calls."""
        if symbol in self._cap_cache:
            return self._cap_cache[symbol]
        try:
            details = await self.polygon.get_ticker_details(symbol)
            cap = details.get("market_cap", 0) or 0
            self._cap_cache[symbol] = cap
            return cap
        except Exception:
            return 0

    async def get_scan_batch(self, batch_size: int = 20) -> list[list[str]]:
        """Split universe into batches for parallel scanning."""
        batches = []
        for i in range(0, len(self.active_universe), batch_size):
            batches.append(self.active_universe[i:i+batch_size])
        return batches
