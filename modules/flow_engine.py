"""
Flow Engine — Real-time order flow analysis from Alpaca trade stream.
Tracks: CVD (cumulative volume delta), bid/ask imbalance, volume spikes,
aggressive buyer/seller detection. No fake data.
"""
import time
import logging
from collections import defaultdict, deque

logger = logging.getLogger("flow")


class FlowState:
    """Per-symbol flow state maintained in memory."""
    __slots__ = [
        "symbol", "last_price", "bid", "ask", "spread",
        "buy_volume", "sell_volume", "total_volume",
        "cvd", "cvd_history", "trade_history",
        "large_buy_count", "large_sell_count",
        "last_update", "volume_ma", "prev_volumes",
    ]

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_price = 0.0
        self.bid = 0.0
        self.ask = 0.0
        self.spread = 0.0
        self.buy_volume = 0
        self.sell_volume = 0
        self.total_volume = 0
        self.cvd = 0.0
        self.cvd_history: deque = deque(maxlen=500)
        self.trade_history: deque = deque(maxlen=1000)
        self.large_buy_count = 0
        self.large_sell_count = 0
        self.last_update = 0.0
        self.volume_ma = 0.0
        self.prev_volumes: deque = deque(maxlen=20)


class FlowEngine:
    def __init__(self):
        self.states: dict[str, FlowState] = {}
        self._large_trade_threshold = 10000  # $10k+ = large trade

    def get_state(self, symbol: str) -> FlowState:
        if symbol not in self.states:
            self.states[symbol] = FlowState(symbol)
        return self.states[symbol]

    async def on_trade(self, symbol: str, event: dict):
        """Process a real-time trade event from Alpaca."""
        state = self.get_state(symbol)
        price = event.get("p", 0.0)
        size = event.get("s", 0)
        timestamp = time.time()

        if price <= 0 or size <= 0:
            return

        state.last_price = price
        state.last_update = timestamp
        notional = price * size

        # Classify as buy or sell using tick rule
        is_buy = True
        if state.bid > 0 and state.ask > 0:
            mid = (state.bid + state.ask) / 2.0
            is_buy = price >= mid
        elif len(state.trade_history) > 0:
            prev_price = state.trade_history[-1]["price"]
            is_buy = price >= prev_price

        if is_buy:
            state.buy_volume += size
            state.cvd += size
            if notional >= self._large_trade_threshold:
                state.large_buy_count += 1
        else:
            state.sell_volume += size
            state.cvd -= size
            if notional >= self._large_trade_threshold:
                state.large_sell_count += 1

        state.total_volume += size
        state.cvd_history.append({"t": timestamp, "cvd": state.cvd})
        state.trade_history.append({
            "t": timestamp, "price": price, "size": size,
            "side": "buy" if is_buy else "sell", "notional": notional,
        })

    async def on_quote(self, symbol: str, event: dict):
        """Process a real-time quote event."""
        state = self.get_state(symbol)
        state.bid = event.get("bp", 0.0)
        state.ask = event.get("ap", 0.0)
        if state.bid > 0 and state.ask > 0:
            state.spread = state.ask - state.bid

    def get_flow_score(self, symbol: str) -> dict:
        """
        Compute flow score for a symbol.
        Returns dict with all flow metrics + composite score 0-100.
        """
        state = self.get_state(symbol)
        if state.total_volume == 0:
            return {"symbol": symbol, "score": 0, "direction": "neutral", "metrics": {}}

        # Buy/sell ratio
        buy_pct = state.buy_volume / state.total_volume * 100 if state.total_volume > 0 else 50
        sell_pct = 100 - buy_pct

        # CVD trend (last 100 trades)
        cvd_trend = 0.0
        if len(state.cvd_history) >= 10:
            recent = list(state.cvd_history)[-50:]
            early = list(state.cvd_history)[-100:-50] if len(state.cvd_history) >= 100 else list(state.cvd_history)[:len(recent)]
            if early:
                cvd_now = recent[-1]["cvd"]
                cvd_then = early[0]["cvd"]
                cvd_trend = cvd_now - cvd_then

        # Large trade imbalance
        large_total = state.large_buy_count + state.large_sell_count
        large_buy_pct = state.large_buy_count / large_total * 100 if large_total > 0 else 50

        # Spread score — institutional grade (0.1% to 1.5% is common range)
        spread_score = 100
        if state.last_price > 0:
            spread_pct = state.spread / state.last_price * 100
            # Standard spread scoring: tight = liquid. Penalty factor from config.
            spread_score = max(0, min(100, 100 - (spread_pct * config.SPREAD_PENALTY_MULT)))

        # Composite scoring
        # Direction: positive = bullish, negative = bearish
        direction_raw = (buy_pct - 50) * 2  # -100 to +100

        # Weight large trades more heavily using LARGE_TRADE_WEIGHT
        if large_total >= 3:
            direction_raw = direction_raw * (1 - config.LARGE_TRADE_WEIGHT) + (large_buy_pct - 50) * 2 * config.LARGE_TRADE_WEIGHT

        # CVD confirmation — ensure this is symmetric and properly handles neutral tape
        cvd_confirms = (cvd_trend > 0 and direction_raw > 0) or (cvd_trend < 0 and direction_raw < 0)

        # Final score 0-100 (how strong is the signal)
        intensity = abs(direction_raw)
        
        # Boost if confirming CVD using parameters from config
        if cvd_confirms:
            intensity = min(100, intensity * config.CVD_BOOST_FACTOR)
        elif abs(cvd_trend) < 500: # Neutral tape doesn't penalize
            intensity = min(100, intensity * config.NEUTRAL_TAPE_BOOST)

        score = min(100, intensity * (spread_score / 100) if spread_score > 0 else intensity * 0.7)

        # Refined direction thresholds — ±8 to be slightly more responsive than ±10
        direction = "bullish" if direction_raw > 8 else "bearish" if direction_raw < -8 else "neutral"

        return {
            "symbol": symbol,
            "score": round(score, 1),
            "direction": direction,
            "last_price": state.last_price,
            "metrics": {
                "buy_pct": round(buy_pct, 1),
                "sell_pct": round(sell_pct, 1),
                "cvd": round(state.cvd, 0),
                "cvd_trend": round(cvd_trend, 0),
                "large_buys": state.large_buy_count,
                "large_sells": state.large_sell_count,
                "spread": round(state.spread, 4),
                "spread_score": round(spread_score, 1),
                "total_volume": state.total_volume,
            },
        }

    def reset_session(self, symbol: str):
        """Reset flow state for a new session."""
        if symbol in self.states:
            self.states[symbol] = FlowState(symbol)
