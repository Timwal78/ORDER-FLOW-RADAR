"""
Order Flow Radar™ — Flow Engine
ScriptMasterLabs™

LAW 1.2 COMPLIANCE: Volume delta classification via Tick Rule ONLY.
  - Uptick   (price > last_price) → trade is a BUY  → delta += size
  - Downtick (price < last_price) → trade is a SELL → delta -= size
  - Neutral  (price == last_price) → delta += 0 (ZERO — not estimated)

FORBIDDEN: Any ratio-based split, buy_ratio, 0.70/0.30 allocation,
or any method that invents a buy/sell classification without a real
observed price direction. See AGENT_LAW.md Law 1.2.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

import config

logger = logging.getLogger("flow_engine")


@dataclass
class TickerState:
    """Real-time state for a single symbol. All values from live market data."""
    symbol: str

    # Price — from latest real trade
    last_price: float = 0.0
    prev_price: float = 0.0   # Used for tick rule direction

    # OHLCV — from real bars
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0

    # Bid/Ask — from real quotes
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0

    # CVD — computed via Tick Rule only (Law 1.2)
    buy_volume:  int = 0
    sell_volume: int = 0
    neutral_volume: int = 0    # Neutral ticks — NOT allocated to either side
    total_volume: int = 0
    cvd: float = 0.0           # Cumulative Volume Delta = buy_vol - sell_vol

    # Block trade tracking
    large_buy_count:  int = 0
    large_sell_count: int = 0

    # Signal state
    last_signal_at: Optional[datetime] = None
    signal_count: int = 0

    # Timestamps
    last_trade_at: Optional[datetime] = None
    last_quote_at: Optional[datetime] = None
    last_bar_at:   Optional[datetime] = None

    @property
    def cvd_ratio(self) -> float:
        """Buy volume as fraction of classified volume. Returns 0.5 if no data."""
        classified = self.buy_volume + self.sell_volume
        if classified == 0:
            return 0.5
        return self.buy_volume / classified

    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as % of mid price."""
        mid = (self.bid + self.ask) / 2
        if mid <= 0:
            return 0.0
        return (self.spread / mid) * 100

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "last_price": self.last_price,
            "bid": self.bid,
            "ask": self.ask,
            "spread_pct": round(self.spread_pct, 4),
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "neutral_volume": self.neutral_volume,
            "total_volume": self.total_volume,
            "cvd": round(self.cvd, 2),
            "cvd_ratio": round(self.cvd_ratio, 4),
            "large_buy_count": self.large_buy_count,
            "large_sell_count": self.large_sell_count,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
        }


class FlowEngine:
    """
    Maintains real-time TickerState for all symbols.
    Implements Tick Rule CVD as the ONLY volume classification method.

    See AGENT_LAW.md Law 1.2:
    'Real-time volume must be strictly classified via the Tick Rule
    or exchange-provided side. If the side is unknown, the volume delta is 0.'
    """

    def __init__(self):
        self.states: Dict[str, TickerState] = {}
        # Pre-populate always-scan symbols
        for sym in config.ALWAYS_SCAN:
            self.states[sym] = TickerState(symbol=sym)
        logger.info(f"FlowEngine initialized | Always-scan: {config.ALWAYS_SCAN}")

    def get_state(self, symbol: str) -> TickerState:
        if symbol not in self.states:
            self.states[symbol] = TickerState(symbol=symbol)
        return self.states[symbol]

    def on_trade(self, symbol: str, price: float, size: int, conditions: list = None, side: str = None):
        """
        Process a real trade tick.

        LAW 1.2: Classification priority:
          1. Exchange-provided side (if available in trade conditions)
          2. Tick Rule: compare price to previous price
          3. Neutral tick: delta = 0

        NEVER invents a side. NEVER uses ratio-based estimation.
        """
        if price <= 0 or size <= 0:
            return

        state = self.get_state(symbol)
        now = datetime.utcnow()
        state.last_trade_at = now
        state.total_volume += size

        # ── Determine trade side ──────────────────────────────────────────────
        # Priority 1: Exchange-provided side from trade tape conditions
        classified_side = None
        if side and side.upper() in ("B", "BUY", "BID"):
            classified_side = "buy"
        elif side and side.upper() in ("S", "SELL", "ASK"):
            classified_side = "sell"

        # Priority 2: Tick Rule (requires a previous price to compare)
        elif state.prev_price > 0:
            if price > state.prev_price:
                classified_side = "buy"    # Uptick
            elif price < state.prev_price:
                classified_side = "sell"   # Downtick
            else:
                classified_side = "neutral"  # Neutral tick — delta = 0

        # Priority 3: First trade with no prior reference — neutral
        else:
            classified_side = "neutral"

        # ── Apply classification ───────────────────────────────────────────────
        if classified_side == "buy":
            state.buy_volume += size
            state.cvd += size
            if size >= config.LARGE_TRADE_THRESHOLD:
                state.large_buy_count += 1
        elif classified_side == "sell":
            state.sell_volume += size
            state.cvd -= size
            if size >= config.LARGE_TRADE_THRESHOLD:
                state.large_sell_count += 1
        else:
            # Neutral tick: volume counted in total but NOT in CVD (Law 1.2)
            state.neutral_volume += size

        # ── Update price ───────────────────────────────────────────────────────
        state.prev_price = state.last_price if state.last_price > 0 else price
        state.last_price = price

    def on_quote(self, symbol: str, bid: float, ask: float):
        """Process a real bid/ask quote update."""
        if bid <= 0 or ask <= 0:
            return
        state = self.get_state(symbol)
        state.bid = bid
        state.ask = ask
        state.spread = ask - bid
        state.last_quote_at = datetime.utcnow()

    def on_bar(self, symbol: str, o: float, h: float, l: float, c: float, v: int):
        """Process a completed bar (from REST or WebSocket bars feed)."""
        state = self.get_state(symbol)
        state.open = o
        state.high = max(state.high, h) if state.high > 0 else h
        state.low = min(state.low, l) if state.low > 0 else l
        state.close = c
        # Update last_price from bar close if no real-time trade yet
        if state.last_price == 0 and c > 0:
            state.prev_price = c
            state.last_price = c
        if state.last_price == 0:  # safety
            state.last_price = c
        state.last_bar_at = datetime.utcnow()

    def inject_price_only(self, symbol: str, price: float):
        """
        Inject a price from REST snapshot when only the last trade price is known
        and no size is available. Does NOT affect CVD.
        Used only to initialize last_price for display purposes.
        """
        if price <= 0:
            return
        state = self.get_state(symbol)
        if state.last_price == 0:
            state.last_price = price
            state.prev_price = price

    def add_symbol(self, symbol: str):
        """Register a symbol discovered by the universe engine."""
        if symbol not in self.states:
            self.states[symbol] = TickerState(symbol=symbol)

    def active_symbols(self) -> list:
        return list(self.states.keys())

    def snapshot(self) -> list:
        """Current state of all symbols with price data."""
        return [
            s.to_dict()
            for s in self.states.values()
            if s.last_price > 0
        ]
