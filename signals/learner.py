"""
SignalLearner: Tracks signal outcomes and learns which confluence combos win.
Adjusts weights dynamically based on accumulated trade data.
"""

import logging
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import asyncio

logger = logging.getLogger(__name__)


class SignalLearner:
    """Tracks signal outcomes and learns which confluence combos win."""

    def __init__(self, data_dir: str = "signal_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.weights_file = self.data_dir / "learned_weights.json"
        self.outcomes_file = self.data_dir / "signal_outcomes.csv"

        # Default weights (baseline from confluence engine)
        self.weights = {
            "orderflow_imbalance": 2.0,
            "wall_support": 1.5,
            "absorption": 2.0,
            "rsi_extreme": 1.5,
            "rsi_divergence": 2.0,
            "macd_crossover": 1.0,
            "macd_acceleration": 0.5,
            "vwap_deviation": 1.5,
            "volume_spike": 1.0,
            "cvd_divergence": 1.5,
            "ema_crossover": 1.0,
            "multi_tf_alignment": 2.0,
            "sr_level": 1.5,
            "options_unusual": 1.5,
            "sentiment": 0.5
        }

        self.load_weights()
        self._ensure_outcomes_file()

    def _ensure_outcomes_file(self):
        """Ensure the outcomes CSV file exists with headers."""
        if not self.outcomes_file.exists():
            with open(self.outcomes_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "signal_id", "symbol", "direction", "entry_price", "stop_loss",
                    "tp1", "tp2", "confluences", "created_at", "status", "outcome",
                    "hit_price", "closed_at"
                ])
                writer.writeheader()

    def load_weights(self):
        """Load learned weights from disk if they exist."""
        if self.weights_file.exists():
            try:
                with open(self.weights_file, "r") as f:
                    loaded = json.load(f)
                    self.weights.update(loaded)
                    logger.info(f"Loaded learned weights from {self.weights_file}")
            except Exception as e:
                logger.error(f"Error loading weights: {e}, using defaults")

    def save_weights(self):
        """Persist current weights to disk."""
        try:
            with open(self.weights_file, "w") as f:
                json.dump(self.weights, f, indent=2)
            logger.info(f"Saved learned weights to {self.weights_file}")
        except Exception as e:
            logger.error(f"Error saving weights: {e}")

    def get_weights(self) -> Dict[str, float]:
        """Return current weights for confluence engine to use."""
        return self.weights.copy()

    async def record_signal(self, trade_card: Dict):
        """
        Record a new signal. Start tracking for outcome.
        trade_card should have: id, symbol, direction, entry, stop_loss, tp1, tp2, confluences
        """
        try:
            with open(self.outcomes_file, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "signal_id", "symbol", "direction", "entry_price", "stop_loss",
                    "tp1", "tp2", "confluences", "created_at", "status", "outcome",
                    "hit_price", "closed_at"
                ])

                # Extract confluence names from trade_card
                confluence_names = [c.get("factor", "") for c in trade_card.get("confluences", [])]

                writer.writerow({
                    "signal_id": trade_card.get("id", ""),
                    "symbol": trade_card.get("symbol", ""),
                    "direction": trade_card.get("direction", ""),
                    "entry_price": trade_card.get("entry", 0),
                    "stop_loss": trade_card.get("stop_loss", 0),
                    "tp1": trade_card.get("tp1", 0),
                    "tp2": trade_card.get("tp2", 0),
                    "confluences": "|".join(confluence_names),
                    "created_at": datetime.utcnow().isoformat(),
                    "status": "OPEN",
                    "outcome": "",
                    "hit_price": "",
                    "closed_at": ""
                })

            logger.info(f"Recorded signal {trade_card.get('id')} for {trade_card.get('symbol')}")
        except Exception as e:
            logger.error(f"Error recording signal: {e}")

    async def check_outcomes(self, current_prices: Dict[str, float]):
        """
        Check all open signals against current prices.
        Updates outcome status: LOSS, TP1_HIT, TP2_HIT, EXPIRED, OPEN
        """
        try:
            rows = []
            with open(self.outcomes_file, "r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            updated = False
            for row in rows:
                if row.get("status") != "OPEN":
                    continue

                symbol = row.get("symbol", "")
                if symbol not in current_prices:
                    continue

                current_price = current_prices[symbol]
                entry_price = float(row.get("entry_price", 0))
                stop_loss = float(row.get("stop_loss", 0))
                tp1 = float(row.get("tp1", 0))
                tp2 = float(row.get("tp2", 0))
                direction = row.get("direction", "")
                created_at = datetime.fromisoformat(row.get("created_at", datetime.utcnow().isoformat()))

                # Check expiry (signal valid for 120 minutes default)
                if (datetime.utcnow() - created_at).total_seconds() > 7200:
                    row["status"] = "EXPIRED"
                    row["outcome"] = "EXPIRED"
                    row["closed_at"] = datetime.utcnow().isoformat()
                    updated = True
                    continue

                # Check outcomes
                outcome = None
                hit_price = None

                if direction == "long":
                    if current_price <= stop_loss:
                        outcome = "LOSS"
                        hit_price = current_price
                    elif current_price >= tp2:
                        outcome = "TP2_HIT"
                        hit_price = current_price
                    elif current_price >= tp1:
                        outcome = "TP1_HIT"
                        hit_price = current_price

                elif direction == "short":
                    if current_price >= stop_loss:
                        outcome = "LOSS"
                        hit_price = current_price
                    elif current_price <= tp2:
                        outcome = "TP2_HIT"
                        hit_price = current_price
                    elif current_price <= tp1:
                        outcome = "TP1_HIT"
                        hit_price = current_price

                if outcome:
                    row["status"] = "CLOSED"
                    row["outcome"] = outcome
                    row["hit_price"] = hit_price
                    row["closed_at"] = datetime.utcnow().isoformat()
                    updated = True
                    logger.info(f"Signal {row.get('signal_id')} outcome: {outcome}")

            # Write back if any changes
            if updated:
                with open(self.outcomes_file, "w", newline="") as f:
                    if rows:
                        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerows(rows)

        except Exception as e:
            logger.error(f"Error checking outcomes: {e}")

    async def retrain(self):
        """
        Adjust weights based on accumulated outcomes.
        Runs periodically (every 24 hours or every 50 completed signals).
        """
        try:
            rows = []
            with open(self.outcomes_file, "r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Filter to closed signals only
            closed_signals = [r for r in rows if r.get("status") == "CLOSED"]

            if len(closed_signals) < 10:
                logger.info(f"Not enough closed signals ({len(closed_signals)}) to retrain yet")
                return

            # Calculate win rate for each confluence factor
            logger.info(f"Retraining on {len(closed_signals)} closed signals...")

            factor_performance = {}
            for signal in closed_signals:
                outcome = signal.get("outcome", "")
                is_win = outcome in ["TP1_HIT", "TP2_HIT"]
                confluences = signal.get("confluences", "").split("|")

                for confluence in confluences:
                    if not confluence.strip():
                        continue

                    # Map confluence name to weight key
                    key = self._confluence_to_weight_key(confluence)
                    if key not in factor_performance:
                        factor_performance[key] = {"wins": 0, "total": 0}

                    factor_performance[key]["total"] += 1
                    if is_win:
                        factor_performance[key]["wins"] += 1

            # Adjust weights based on win rates
            changes = {}
            for factor_key, perf in factor_performance.items():
                if perf["total"] == 0:
                    continue

                win_rate = perf["wins"] / perf["total"]
                old_weight = self.weights.get(factor_key, 1.0)

                if win_rate > 0.60:  # Win rate > 60%, increase weight
                    new_weight = old_weight * 1.05
                elif win_rate < 0.40:  # Win rate < 40%, decrease weight
                    new_weight = old_weight * 0.90
                else:
                    new_weight = old_weight

                # Clamp between 0.1 and 4.0
                new_weight = max(0.1, min(4.0, new_weight))

                if abs(new_weight - old_weight) > 0.01:
                    changes[factor_key] = {
                        "old": round(old_weight, 2),
                        "new": round(new_weight, 2),
                        "win_rate": round(win_rate, 2),
                        "samples": perf["total"]
                    }
                    self.weights[factor_key] = new_weight

            # Save updated weights
            if changes:
                self.save_weights()
                logger.info(f"Weights retrained. Changes: {json.dumps(changes, indent=2)}")
            else:
                logger.info("No significant weight changes after retraining")

        except Exception as e:
            logger.error(f"Error in retrain: {e}")

    def _confluence_to_weight_key(self, confluence_name: str) -> str:
        """Map confluence factor name to weight key."""
        name_lower = confluence_name.lower()

        mapping = {
            "order flow imbalance": "orderflow_imbalance",
            "wall": "wall_support",
            "absorption": "absorption",
            "rsi oversold": "rsi_extreme",
            "rsi overbought": "rsi_extreme",
            "rsi divergence": "rsi_divergence",
            "macd": "macd_crossover",
            "acceleration": "macd_acceleration",
            "vwap": "vwap_deviation",
            "volume spike": "volume_spike",
            "cvd": "cvd_divergence",
            "ema": "ema_crossover",
            "multi-tf alignment": "multi_tf_alignment",
            "support": "sr_level",
            "resistance": "sr_level",
            "options": "options_unusual",
            "sentiment": "sentiment"
        }

        for key, weight_key in mapping.items():
            if key in name_lower:
                return weight_key

        return "sentiment"  # default

    def get_performance_stats(self) -> Dict:
        """Return current performance statistics."""
        try:
            rows = []
            with open(self.outcomes_file, "r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            closed_signals = [r for r in rows if r.get("status") == "CLOSED"]
            if not closed_signals:
                return {
                    "total_signals": len(rows),
                    "closed_signals": 0,
                    "win_rate": 0,
                    "tp1_hits": 0,
                    "tp2_hits": 0,
                    "losses": 0
                }

            outcomes = {}
            for signal in closed_signals:
                outcome = signal.get("outcome", "")
                outcomes[outcome] = outcomes.get(outcome, 0) + 1

            wins = outcomes.get("TP1_HIT", 0) + outcomes.get("TP2_HIT", 0)
            win_rate = wins / len(closed_signals) if closed_signals else 0

            return {
                "total_signals": len(rows),
                "closed_signals": len(closed_signals),
                "win_rate": round(win_rate, 2),
                "tp1_hits": outcomes.get("TP1_HIT", 0),
                "tp2_hits": outcomes.get("TP2_HIT", 0),
                "losses": outcomes.get("LOSS", 0),
                "expired": outcomes.get("EXPIRED", 0)
            }

        except Exception as e:
            logger.error(f"Error getting performance stats: {e}")
            return {}
