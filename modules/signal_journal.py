"""
Order Flow Radar™ — Signal Journal
ScriptMasterLabs™

Persistent logging of all signals for performance analysis and learning.
Data stored in CSV for durability (institutional signal tape).
"""
from __future__ import annotations
import aiofiles
import logging
import os
from datetime import datetime
from typing import Dict, Any

import config

logger = logging.getLogger("signal_journal")


class SignalJournal:
    """
    Tracks every signal fired by the system.
    Persists to signal_data/signal_outcomes.csv
    """

    def __init__(self):
        self._path = config.JOURNAL_CSV_PATH
        self._init_csv()

    def _init_csv(self):
        """Ensure CSV exists with headers."""
        if not os.path.exists(self._path):
            with open(self._path, "w") as f:
                f.write("timestamp,symbol,action,price,score,cvd,cvd_ratio,confluences,outcome\n")
            logger.info(f"Initialized journal at {self._path}")

    async def log_signal(self, sig: dict):
        """Append a new signal to the journal."""
        line = (
            f"{sig['fired_at']},{sig['symbol']},{sig['action']},{sig['price']:.2f},"
            f"{sig['score']:.1f},{sig['cvd']:.2f},{sig['cvd_ratio']:.4f},"
            f"\"{';'.join(sig['confluences'])}\",OPEN\n"
        )
        try:
            async with aiofiles.open(self._path, mode="a") as f:
                await f.write(line)
        except Exception as e:
            logger.error(f"Failed to log signal to journal: {e}")

    async def get_recent_signals(self, limit: int = 50) -> list:
        """Fetch the most recent signals from the journal."""
        if not os.path.exists(self._path):
            return []
        
        signals = []
        try:
            async with aiofiles.open(self._path, mode="r") as f:
                lines = await f.readlines()
                # Skip header, take last N
                for line in lines[1:][-limit:]:
                    parts = line.strip().split(",")
                    if len(parts) >= 9:
                        signals.append({
                            "timestamp": parts[0],
                            "symbol":    parts[1],
                            "action":    parts[2],
                            "price":     float(parts[3]),
                            "score":     float(parts[4]),
                            "cvd":       float(parts[5]),
                            "cvd_ratio": float(parts[6]),
                            "outcome":   parts[8],
                        })
        except Exception as e:
            logger.error(f"Failed to read journal: {e}")
        
        return sorted(signals, key=lambda x: x["timestamp"], reverse=True)
