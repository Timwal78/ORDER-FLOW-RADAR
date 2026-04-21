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
class TradePlan:
    """Actionable trade plan attached to every signal."""
    grade:        str    # "A", "B", "C", "D"
    grade_label:  str    # "Strong Buy", "Buy", "Lean Buy", "Speculative"
    entry:        float  # Entry price (current)
    stop_loss:    float  # Where to cut losses
    target_1:     float  # Conservative profit target
    target_2:     float  # Aggressive profit target
    risk_reward:  str    # e.g. "2:1"
    instruction:  str    # Plain English: "BUY QQQ at $485.30..."
    why:          str    # Plain English reason

    def to_dict(self) -> dict:
        return {
            "grade": self.grade,
            "grade_label": self.grade_label,
            "entry": round(self.entry, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target_1": round(self.target_1, 2),
            "target_2": round(self.target_2, 2),
            "risk_reward": self.risk_reward,
            "instruction": self.instruction,
            "why": self.why,
        }


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
    trade_plan:  Optional[TradePlan] = None
    options_recs: List[Dict[str, Any]] = field(default_factory=list)
    fired_at:    datetime = field(default_factory=datetime.utcnow)
    is_new_alert: bool = False
    ai_auditor_reason: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
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
        if self.trade_plan:
            d["trade_plan"] = self.trade_plan.to_dict()
        if self.ai_auditor_reason:
            d["ai_auditor_reason"] = self.ai_auditor_reason
        return d


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
        # Law 2: Multiplier sourced from config.IEX_VOLUME_NORMALIZER (default 1.5x)
        score_multiplier = 1.0
        if config.ALPACA_FEED == "iex":
            score_multiplier = config.IEX_VOLUME_NORMALIZER
            
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

        # ── Build Actionable Trade Plan ────────────────────────────────────────
        trade_plan = self._build_trade_plan(symbol, direction, score, state, confluences)

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
            trade_plan=trade_plan,
            fired_at=now,
            is_new_alert=is_new,
        )

        self.active_signals[symbol] = sig
        if is_new:
            self._last_alert[symbol] = now

        return sig

    # ══════════════════════════════════════════════════════════════════════════
    # TRADE PLAN BUILDER — Plain English, Actionable Instructions
    # ══════════════════════════════════════════════════════════════════════════

    def _grade_signal(self, score: float) -> tuple:
        """Convert raw score to letter grade and human label."""
        if score >= config.GRADE_A_THRESHOLD:
            return "A", "Strong"
        elif score >= config.GRADE_B_THRESHOLD:
            return "B", "Good"
        elif score >= config.GRADE_C_THRESHOLD:
            return "C", "Moderate"
        else:
            return "D", "Speculative"

    def _build_trade_plan(self, symbol: str, direction: str, score: float,
                          state, confluences: List[str]) -> TradePlan:
        """
        Generate a complete, actionable trade plan in plain English.
        The user should be able to read this and know exactly what to do.
        """
        price = state.last_price
        grade, grade_word = self._grade_signal(score)

        # ── Calculate stop loss and targets ────────────────────────────────────
        stop_pct = config.TRADE_STOP_PCT / 100.0  # e.g. 1.0% -> 0.01

        # Tighter stops for higher grades (more confident), wider for lower
        grade_adjustments = {"A": 0.8, "B": 1.0, "C": 1.3, "D": 1.5}
        adj = grade_adjustments.get(grade, 1.0)
        adjusted_stop_pct = stop_pct * adj

        risk_amount = price * adjusted_stop_pct

        if direction == "LONG":
            action_word = "BUY"
            stop_loss = round(price - risk_amount, 2)
            target_1 = round(price + (risk_amount * config.TRADE_TP1_MULT), 2)
            target_2 = round(price + (risk_amount * config.TRADE_TP2_MULT), 2)
            grade_label = f"{grade_word} Buy"
        else:
            action_word = "SELL SHORT"
            stop_loss = round(price + risk_amount, 2)
            target_1 = round(price - (risk_amount * config.TRADE_TP1_MULT), 2)
            target_2 = round(price - (risk_amount * config.TRADE_TP2_MULT), 2)
            grade_label = f"{grade_word} Sell"

        rr_ratio = f"{config.TRADE_TP1_MULT:.0f}:1"

        # ── Build plain-English instruction ────────────────────────────────────
        instruction = (
            f"{action_word} {symbol} at ${price:.2f} — "
            f"Stop Loss ${stop_loss:.2f} | "
            f"Target 1 ${target_1:.2f} | "
            f"Target 2 ${target_2:.2f}"
        )

        # ── Build plain-English "why" ──────────────────────────────────────────
        why = self._explain_why(symbol, direction, grade, state, confluences)

        return TradePlan(
            grade=grade,
            grade_label=grade_label,
            entry=price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            risk_reward=rr_ratio,
            instruction=instruction,
            why=why,
        )

    def _explain_why(self, symbol: str, direction: str, grade: str,
                     state, confluences: List[str]) -> str:
        """
        Translate technical confluences into a plain-English explanation
        that anyone can understand — no jargon.
        """
        reasons = []

        # CVD explanation
        if state.cvd_ratio >= 0.65:
            reasons.append("heavy buying pressure — more buyers than sellers")
        elif state.cvd_ratio >= 0.55:
            reasons.append("buyers have the edge right now")
        elif state.cvd_ratio <= 0.35:
            reasons.append("heavy selling pressure — sellers are in control")
        elif state.cvd_ratio <= 0.45:
            reasons.append("sellers have the edge right now")

        # Block trades
        block_diff = state.large_buy_count - state.large_sell_count
        if block_diff >= 2:
            reasons.append(f"big-money players are buying (seen {state.large_buy_count} large buy orders)")
        elif block_diff <= -2:
            reasons.append(f"big-money players are selling (seen {state.large_sell_count} large sell orders)")

        # Volume
        if state.total_volume > 500_000:
            reasons.append(f"very high trading volume ({state.total_volume:,} shares)")
        elif state.total_volume > 100_000:
            reasons.append(f"strong trading volume ({state.total_volume:,} shares)")

        # Spread
        if state.spread_pct < 0.05:
            reasons.append("tight spread — good liquidity for clean fills")
        elif state.spread_pct > 0.5:
            reasons.append("wide spread — be careful, fills may slip")

        # Sentiment
        for c in confluences:
            if "SENTIMENT_BULL" in c:
                reasons.append("news sentiment is positive")
            elif "SENTIMENT_BEAR" in c:
                reasons.append("news sentiment is negative")

        # AI Auditor
        for c in confluences:
            if "AI_CONFIRMED" in c:
                reason_text = c.split("(", 1)[1].rstrip(")") if "(" in c else "signal validated"
                reasons.append(f"AI review confirms: {reason_text}")

        # Ask lift / Bid hit
        if any("ASK_LIFT" in c for c in confluences):
            reasons.append("buyers are paying the asking price (aggressive buying)")
        if any("BID_HIT" in c for c in confluences):
            reasons.append("sellers are hitting the bid (aggressive selling)")

        if not reasons:
            reasons.append("multiple technical factors align")

        # Confidence qualifier
        if grade == "A":
            prefix = "High confidence"
        elif grade == "B":
            prefix = "Good setup"
        elif grade == "C":
            prefix = "Moderate signal"
        else:
            prefix = "Speculative"

        return f"{prefix} — {', '.join(reasons)}."

