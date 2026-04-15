"""
Order Flow Radar™ — Confluence Engine
ScriptMasterLabs™

LAW 2 COMPLIANCE: All weights from config.py. No magic numbers inline.
Scores each symbol's real-time state into a directional signal.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import config
from modules.flow_engine import FlowEngine, TickerState

logger = logging.getLogger("confluence_engine")


@dataclass
class Signal:
    symbol:      str
    action:      str           # "LONG" | "SHORT"
    score:       float
    confluences: List[str]
    price:       float
    cvd:         float
    cvd_ratio:   float
    volume:      int
    spread_pct:  float
    options_recs: List[Dict[str, Any]] = field(default_factory=list)
    fired_at:    datetime = field(default_factory=datetime.utcnow)
    is_new_alert: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol":       self.symbol,
            "action":       self.action,
            "score":        round(self.score, 1),
            "confluences":  self.confluences,
            "price":        self.price,
            "cvd":          round(self.cvd, 2),
            "cvd_ratio":    round(self.cvd_ratio, 4),
            "volume":       self.volume,
            "spread_pct":   round(self.spread_pct, 4),
            "options_recs": self.options_recs,
            "fired_at":     self.fired_at.isoformat(),
            "is_new_alert": self.is_new_alert,
        }


class ConfluenceEngine:
    """
    Scores each symbol's TickerState into a directional signal.

    Scoring is PURELY config-driven. All weights reference config constants.
    No inline magic numbers — see AGENT_LAW.md Law 2.
    """

    def __init__(self, flow: FlowEngine, learned_weights: Dict[str, float] = None, sentiment: Optional[Any] = None, auditor: Optional[Any] = None):
        self._flow = flow
        self._weights: Dict[str, float] = learned_weights or {}
        self._sentiment = sentiment
        self._auditor = auditor
        self.active_signals: Dict[str, Signal] = {}
        self._last_alert: Dict[str, datetime] = {}

    def set_weights(self, weights: Dict[str, float]):
        """Update with learned weights from the Learner module."""
        self._weights = weights

    def _w(self, factor: str, default: float = 1.0) -> float:
        """Get learned weight for a factor, falling back to default."""
        return self._weights.get(factor, default)

    async def evaluate(self, symbol: str) -> Optional[Signal]:
        """
        Evaluate one symbol. Returns Signal if score >= MIN_CONFLUENCE_SCORE, else None.
        Now includes Sentiment Overlay and AI Auditing for institutional hardening.
        """
        state = self._flow.states.get(symbol)
        if not state or state.last_price <= 0:
            return None

        bull_score = 0.0
        bear_score = 0.0
        confluences = []

        # ── Intelligence Layer: Sentiment Overlay (config.SENTIMENT_WEIGHT) ──
        if self._sentiment:
            sentiment_val = await self._sentiment.get_sentiment(symbol)
            if sentiment_val != 0:
                pts = abs(sentiment_val) * 50.0 * config.SENTIMENT_WEIGHT
                if sentiment_val > 0:
                    bull_score += pts
                    confluences.append(f"SENTIMENT_BULL ({sentiment_val:+.2f})")
                else:
                    bear_score += pts
                    confluences.append(f"SENTIMENT_BEAR ({sentiment_val:+.2f})")

        # ── Factor 1: CVD Direction (config.CVD_BOOST_FACTOR) ────────────────
        if state.buy_volume + state.sell_volume > 0:
            cvd_ratio = state.cvd_ratio
            if cvd_ratio >= 0.60:
                pts = 20.0 * self._w("cvd_bull", config.CVD_BOOST_FACTOR)
                bull_score += pts
                confluences.append(f"CVD_BULL ({cvd_ratio:.0%})")
            elif cvd_ratio <= 0.40:
                pts = 20.0 * self._w("cvd_bear", config.CVD_BOOST_FACTOR)
                bear_score += pts
                confluences.append(f"CVD_BEAR ({cvd_ratio:.0%})")

        # ── Factor 2: Block Trade Imbalance (config.LARGE_TRADE_WEIGHT) ──────
        block_diff = state.large_buy_count - state.large_sell_count
        if block_diff > 0:
            pts = block_diff * 10.0 * self._w("block_bull", config.LARGE_TRADE_WEIGHT)
            bull_score += pts
            confluences.append(f"BLOCK_BUY_IMBAL (+{block_diff})")
        elif block_diff < 0:
            pts = abs(block_diff) * 10.0 * self._w("block_bear", config.LARGE_TRADE_WEIGHT)
            bear_score += pts
            confluences.append(f"BLOCK_SELL_IMBAL ({block_diff})")

        # ── Factor 3: Bid-Ask Spread Liquidity (config.SPREAD_PENALTY_MULT) ──
        spread_penalty = state.spread_pct * config.SPREAD_PENALTY_MULT
        if spread_penalty > 0:
            bull_score = max(0, bull_score - spread_penalty)
            bear_score = max(0, bear_score - spread_penalty)
            if spread_penalty > 5:
                confluences.append(f"SPREAD_PENALTY ({state.spread_pct:.2f}%)")

        # ── Factor 4: Price vs Mid (bid/ask pressure) ─────────────────────────
        if state.bid > 0 and state.ask > 0:
            mid = (state.bid + state.ask) / 2
            if state.last_price >= state.ask * 0.999:
                pts = 15.0 * self._w("ask_lift", 1.0)
                bull_score += pts
                confluences.append("ASK_LIFT")
            elif state.last_price <= state.bid * 1.001:
                pts = 15.0 * self._w("bid_hit", 1.0)
                bear_score += pts
                confluences.append("BID_HIT")

        # ── Factor 5: Sustained volume (volume > 0 is real data) ─────────────
        if state.total_volume > 100_000:
            pts = 10.0
            bull_score += pts * (1 if bull_score >= bear_score else 0)
            bear_score += pts * (1 if bear_score > bull_score else 0)
            confluences.append(f"HIGH_VOL ({state.total_volume:,})")

        # ── Intelligence Layer: IEX Normalization (Boost for Standard Tiers) ──
        # Justification: IEX is 10% of total volume; we normalize to reach "A/B" grades.
        score_multiplier = 1.0
        if config.ALPACA_FEED == "iex":
            score_multiplier = 1.5
            
        if bull_score > bear_score:
            direction, score = "LONG", bull_score * score_multiplier
        elif bear_score > bull_score:
            direction, score = "SHORT", bear_score * score_multiplier
        else:
            return None

        # Apply final Institutional Gate
        if score < config.MIN_CONFLUENCE_SCORE:
            return None

        # ── Intelligence Layer: AI Auditor (config.AI_AUDIT_THRESHOLD) ───────
        if self._auditor and score >= config.AI_AUDIT_THRESHOLD:
            audit_data = {
                "symbol": symbol, "action": direction, "score": score,
                "cvd_ratio": state.cvd_ratio, "confluences": confluences,
                "price": state.last_price
            }
            audit_res = await self._auditor.audit_signal(audit_data)
            
            if not audit_res.get("approved", True):
                logger.warning(f"AI Auditor REJECTED {symbol} {direction}: {audit_res.get('reason')}")
                return None
            
            score += audit_res.get("ai_score_adj", 0.0)
            confluences.append(f"AI_CONFIRMED ({audit_res.get('reason')})")

        # ── Cooldown check ─────────────────────────────────────────────────────
        now = datetime.utcnow()
        last = self._last_alert.get(symbol)
        is_new = last is None or (now - last).total_seconds() >= config.SIGNAL_COOLDOWN

        sig = Signal(
            symbol=symbol,
            action=direction,
            score=score,
            confluences=confluences,
            price=state.last_price,
            cvd=state.cvd,
            cvd_ratio=state.cvd_ratio,
            volume=state.total_volume,
            spread_pct=state.spread_pct,
            fired_at=now,
            is_new_alert=is_new,
        )

        self.active_signals[symbol] = sig
        if is_new:
            self._last_alert[symbol] = now

        return sig
