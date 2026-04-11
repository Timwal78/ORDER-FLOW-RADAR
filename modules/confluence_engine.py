"""
Confluence Engine — Merges all signals into a single actionable output.
Flow score + options chain quality + volume anomaly + momentum = GO/NO-GO.
"""
import logging
from datetime import datetime

import config

logger = logging.getLogger("confluence")


class Signal:
    """A complete actionable signal with options recommendation."""
    __slots__ = [
        "symbol", "direction", "action", "score", "confidence",
        "flow_data", "options_recs", "timestamp", "reasons",
    ]

    def __init__(self):
        self.symbol = ""
        self.direction = ""
        self.action = ""  # "BUY CALL", "BUY PUT", "WATCH"
        self.score = 0.0
        self.confidence = ""
        self.flow_data = {}
        self.options_recs = []
        self.timestamp = ""
        self.reasons = []

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "action": self.action,
            "score": self.score,
            "confidence": self.confidence,
            "flow": self.flow_data,
            "options": self.options_recs,
            "timestamp": self.timestamp,
            "reasons": self.reasons,
        }


class ConfluenceEngine:
    def __init__(self, flow_engine, options_recommender):
        self.flow = flow_engine
        self.options_rec = options_recommender
        self.active_signals: dict[str, Signal] = {}
        self.signal_history: list[dict] = []

    async def evaluate(self, symbol: str) -> Signal | None:
        """
        Evaluate a symbol. If confluence >= threshold, generate signal
        with options recommendation.
        """
        flow_data = self.flow.get_flow_score(symbol)
        score = flow_data.get("score", 0)
        direction = flow_data.get("direction", "neutral")
        last_price = flow_data.get("last_price", 0)

        if score < config.MIN_CONFLUENCE_SCORE:
            # Remove from active if it was there
            self.active_signals.pop(symbol, None)
            return None

        if direction == "neutral":
            return None

        # Build signal
        sig = Signal()
        sig.symbol = symbol
        sig.direction = direction
        sig.score = score
        sig.flow_data = flow_data
        sig.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Reasons
        metrics = flow_data.get("metrics", {})
        if metrics.get("buy_pct", 50) > 65:
            sig.reasons.append(f"Aggressive buying: {metrics['buy_pct']:.0f}% buy volume")
        elif metrics.get("sell_pct", 50) > 65:
            sig.reasons.append(f"Aggressive selling: {metrics['sell_pct']:.0f}% sell volume")

        if metrics.get("large_buys", 0) > metrics.get("large_sells", 0) + 2:
            sig.reasons.append(f"Large buyer dominance: {metrics['large_buys']} blocks vs {metrics['large_sells']}")
        elif metrics.get("large_sells", 0) > metrics.get("large_buys", 0) + 2:
            sig.reasons.append(f"Large seller dominance: {metrics['large_sells']} blocks vs {metrics['large_buys']}")

        cvd_trend = metrics.get("cvd_trend", 0)
        if abs(cvd_trend) > 1000:
            sig.reasons.append(f"CVD trend: {'↑' if cvd_trend > 0 else '↓'} {abs(cvd_trend):,.0f}")

        # Get options recommendations
        options = await self.options_rec.recommend(symbol, direction, last_price, score)
        sig.options_recs = [o for o in options]

        if options:
            top = options[0]
            sig.action = f"BUY {top['direction']}"
            sig.confidence = top["confidence"]
        else:
            sig.action = f"{'BULLISH' if direction == 'bullish' else 'BEARISH'} — no liquid options found"
            sig.confidence = "LOW"

        # Store
        self.active_signals[symbol] = sig
        self.signal_history.append(sig.to_dict())
        # Cap history at 500
        if len(self.signal_history) > 500:
            self.signal_history = self.signal_history[-500:]

        return sig

    def get_active_signals(self) -> list[dict]:
        """All currently active signals sorted by score."""
        signals = [s.to_dict() for s in self.active_signals.values()]
        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals

    def get_history(self, limit: int = 50) -> list[dict]:
        """Recent signal history."""
        return self.signal_history[-limit:]
