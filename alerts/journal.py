import logging
import os
import csv
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class SignalJournal:
    def __init__(self, config, journal_path: str = "signals_journal.csv"):
        self.config = config
        self.journal_path = journal_path
        self.file_lock = asyncio.Lock()

        # Ensure file exists with headers
        self._init_journal()

    def _init_journal(self):
        """Create journal file with headers if it doesn't exist."""
        try:
            if not os.path.exists(self.journal_path):
                with open(self.journal_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=self.get_fieldnames())
                    writer.writeheader()
                logger.info(f"Created signal journal at {self.journal_path}")
        except Exception as e:
            logger.error(f"Error initializing journal: {e}")

    @staticmethod
    def get_fieldnames():
        """Define CSV columns."""
        return [
            "timestamp",
            "symbol",
            "direction",
            "entry",
            "stop_loss",
            "tp1",
            "tp2",
            "risk_reward_1",
            "risk_reward_2",
            "score",
            "confluence_count",
            "confluences",
            "bias",
            "timeframe",
            "alert_level",
            "valid_for_minutes",
            "outcome"
        ]

    async def log_signal(self, trade_card: dict, outcome: str = None):
        """
        Append signal to journal.
        outcome: "won", "lost", "cancelled", or None (pending)
        """
        try:
            async with self.file_lock:
                confluences_str = "; ".join(
                    [c.get("factor", "") for c in trade_card.get("confluences", [])]
                )

                row = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "symbol": trade_card.get("symbol", ""),
                    "direction": trade_card.get("direction", ""),
                    "entry": trade_card.get("entry", ""),
                    "stop_loss": trade_card.get("stop_loss", ""),
                    "tp1": trade_card.get("tp1", ""),
                    "tp2": trade_card.get("tp2", ""),
                    "risk_reward_1": trade_card.get("risk_reward_1", ""),
                    "risk_reward_2": trade_card.get("risk_reward_2", ""),
                    "score": trade_card.get("score", ""),
                    "confluence_count": trade_card.get("confluence_count", ""),
                    "confluences": confluences_str,
                    "bias": trade_card.get("bias", ""),
                    "timeframe": trade_card.get("timeframe", ""),
                    "alert_level": trade_card.get("alert_level", ""),
                    "valid_for_minutes": trade_card.get("valid_for_minutes", ""),
                    "outcome": outcome or ""
                }

                with open(self.journal_path, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=self.get_fieldnames())
                    writer.writerow(row)

                logger.debug(f"Logged signal for {trade_card.get('symbol')} {trade_card.get('direction')}")

        except Exception as e:
            logger.error(f"Error logging signal to journal: {e}")

    async def update_outcome(self, symbol: str, direction: str, timestamp: str, outcome: str):
        """
        Update outcome for a specific signal.
        This is a simplified version - in production, you'd want better matching.
        """
        try:
            async with self.file_lock:
                rows = []

                with open(self.journal_path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)

                # Find and update matching row
                for row in rows:
                    if (row.get("symbol") == symbol and
                        row.get("direction") == direction and
                        row.get("timestamp") == timestamp):
                        row["outcome"] = outcome
                        logger.debug(f"Updated outcome for {symbol} {direction}")
                        break

                # Write back
                with open(self.journal_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=self.get_fieldnames())
                    writer.writeheader()
                    writer.writerows(rows)

        except Exception as e:
            logger.error(f"Error updating signal outcome: {e}")
