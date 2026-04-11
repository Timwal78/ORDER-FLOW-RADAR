"""
SML Earnings Detector — Flags tickers with upcoming earnings.
Pre-earnings unusual options activity = front-running signal.
Integrates with sweep scanner to boost conviction on earnings plays.
"""
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger("earnings")


class EarningsDetector:
    """Detect tickers with earnings in the next N days using free APIs."""

    def __init__(self):
        self.earnings_cache = {}  # ticker -> earnings_date
        self.last_refresh = None
        self.refresh_interval = 3600  # 1 hour

    async def refresh_earnings_calendar(self, tickers: list):
        """Fetch earnings dates for a list of tickers via Alpha Vantage or Yahoo."""
        import os
        alpha_key = os.getenv("ALPHA_VANTAGE_KEY", "")

        now = datetime.now()
        if self.last_refresh and (now - self.last_refresh).seconds < self.refresh_interval:
            return  # Already fresh

        # Use Yahoo Finance earnings calendar (free, no key needed)
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "Mozilla/5.0"}

            # Yahoo earnings calendar for next 5 days
            for days_ahead in range(6):
                target = now + timedelta(days=days_ahead)
                date_str = target.strftime("%Y-%m-%d")
                url = f"https://finance.yahoo.com/calendar/earnings?day={date_str}"

                try:
                    # Use the screener API instead (more reliable)
                    api_url = "https://query1.finance.yahoo.com/v1/finance/trending/US"
                    # This won't give earnings directly, so let's use a different approach
                    pass
                except:
                    pass

            # Batch check via yfinance for specific tickers we care about
            # Only check tickers that showed up in sweep scans
            checked = 0
            for ticker in tickers[:50]:  # Cap to avoid rate limits
                if ticker in self.earnings_cache:
                    continue
                try:
                    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
                    params = {"modules": "calendarEvents"}
                    async with session.get(url, headers=headers, params=params,
                                          timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            events = (data.get("quoteSummary", {}).get("result", [{}])[0]
                                     .get("calendarEvents", {}).get("earnings", {}))
                            earnings_date_raw = events.get("earningsDate", [])
                            if earnings_date_raw:
                                # Yahoo returns epoch timestamp
                                ts = earnings_date_raw[0].get("raw", 0)
                                if ts:
                                    ed = datetime.fromtimestamp(ts).date()
                                    self.earnings_cache[ticker] = ed.isoformat()
                                    checked += 1
                    await asyncio.sleep(0.2)  # Rate limit
                except:
                    continue

            if checked:
                logger.info(f"Earnings: checked {checked} tickers, {len(self.earnings_cache)} with dates")

        self.last_refresh = now

    def has_upcoming_earnings(self, ticker, days=5):
        """Check if ticker has earnings within N days."""
        if ticker not in self.earnings_cache:
            return False, None

        try:
            ed = datetime.strptime(self.earnings_cache[ticker], "%Y-%m-%d").date()
            today = datetime.now().date()
            days_until = (ed - today).days
            if 0 <= days_until <= days:
                return True, days_until
        except:
            pass
        return False, None

    def get_earnings_tickers(self, days=5):
        """Get all tickers with earnings in next N days."""
        results = []
        today = datetime.now().date()
        for ticker, date_str in self.earnings_cache.items():
            try:
                ed = datetime.strptime(date_str, "%Y-%m-%d").date()
                days_until = (ed - today).days
                if 0 <= days_until <= days:
                    results.append({"ticker": ticker, "earnings_date": date_str, "days_until": days_until})
            except:
                continue
        return sorted(results, key=lambda x: x["days_until"])
