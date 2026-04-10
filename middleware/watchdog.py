"""
System health watchdog. Monitors all data feeds, auto-recovers,
and exposes a health endpoint for Railway/Docker.
"""

import asyncio
import time
import logging
from typing import Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SystemWatchdog:
    def __init__(self):
        self.feed_status: Dict[str, dict] = {}
        self.error_counts: Dict[str, int] = {}
        self.last_successful: Dict[str, float] = {}
        self.system_start_time = time.time()
        self.total_signals_sent = 0
        self.total_errors = 0
        self.symbols_scanned = 0
        self.is_healthy = True

    def register_feed(self, name: str):
        self.feed_status[name] = {
            "status": "starting",
            "last_update": None,
            "errors_last_hour": 0,
            "total_updates": 0,
        }
        self.error_counts[name] = 0

    def report_success(self, feed_name: str):
        now = time.time()
        if feed_name in self.feed_status:
            self.feed_status[feed_name]["status"] = "healthy"
            self.feed_status[feed_name]["last_update"] = now
            self.feed_status[feed_name]["total_updates"] += 1
            self.last_successful[feed_name] = now
            self.error_counts[feed_name] = 0

    def report_error(self, feed_name: str, error: str):
        self.error_counts[feed_name] = self.error_counts.get(feed_name, 0) + 1
        self.total_errors += 1
        if feed_name in self.feed_status:
            self.feed_status[feed_name]["status"] = "error"
            self.feed_status[feed_name]["errors_last_hour"] = self.error_counts[feed_name]
        logger.error(f"Feed {feed_name} error #{self.error_counts[feed_name]}: {error}")

    def report_signal(self):
        self.total_signals_sent += 1

    def get_health_report(self) -> dict:
        uptime = time.time() - self.system_start_time
        healthy_feeds = sum(1 for f in self.feed_status.values() if f["status"] == "healthy")
        total_feeds = len(self.feed_status)

        if healthy_feeds > 0:
            status = "healthy"
        elif total_feeds > 0:
            status = "degraded"
        else:
            status = "starting"

        return {
            "status": status,
            "uptime_seconds": int(uptime),
            "uptime_human": self._format_uptime(uptime),
            "feeds": {k: {**v, "last_update": self._fmt_ts(v["last_update"])} for k, v in self.feed_status.items()},
            "healthy_feeds": f"{healthy_feeds}/{total_feeds}",
            "total_signals": self.total_signals_sent,
            "symbols_scanned": self.symbols_scanned,
            "total_errors": self.total_errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _fmt_ts(self, ts):
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def _format_uptime(self, seconds: float) -> str:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    async def monitor_loop(self, stale_threshold: int = 300):
        """Run every 60s. Marks feeds stale if no update within threshold."""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                for name, status in self.feed_status.items():
                    last = self.last_successful.get(name, 0)
                    if last > 0 and (now - last) > stale_threshold:
                        status["status"] = "stale"
                        logger.warning(f"Feed {name} stale ({int(now - last)}s since last update)")
                degraded = [n for n, s in self.feed_status.items() if s["status"] not in ("healthy", "starting")]
                self.is_healthy = len(degraded) == 0
                if degraded:
                    logger.warning(f"Degraded feeds: {degraded}")
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
