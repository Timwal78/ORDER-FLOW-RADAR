import logging
from typing import Dict
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class TrendSignals:
    def __init__(self, config):
        self.config = config
        self.ema_fast = config.get("EMA_FAST", 9)
        self.ema_slow = config.get("EMA_SLOW", 21)
        self.ema_50 = config.get("EMA_50", 50)

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate EMA for given period."""
        try:
            if len(prices) < period:
                return pd.Series(dtype=float)
            return prices.ewm(span=period, adjust=False).mean()
        except Exception as e:
            logger.error(f"Error calculating EMA({period}): {e}")
            return pd.Series(dtype=float)

    def detect_ema_crossover(self, bars_df: pd.DataFrame) -> Dict:
        """Detect EMA(9) and EMA(21) crossovers."""
        signals = {
            "ema_fast": None,
            "ema_slow": None,
            "ema_50": None,
            "crossover": None
        }

        try:
            if bars_df is None or len(bars_df) < self.ema_50:
                return signals

            if "close" not in bars_df.columns:
                return signals

            closes = bars_df["close"]

            ema_fast = self.calculate_ema(closes, self.ema_fast)
            ema_slow = self.calculate_ema(closes, self.ema_slow)
            ema_50 = self.calculate_ema(closes, self.ema_50)

            if len(ema_fast) == 0 or len(ema_slow) == 0 or len(ema_50) == 0:
                return signals

            signals["ema_fast"] = float(ema_fast.iloc[-1])
            signals["ema_slow"] = float(ema_slow.iloc[-1])
            signals["ema_50"] = float(ema_50.iloc[-1])

            if len(ema_fast) >= 2:
                prev_fast = ema_fast.iloc[-2]
                curr_fast = ema_fast.iloc[-1]
                prev_slow = ema_slow.iloc[-2]
                curr_slow = ema_slow.iloc[-1]

                if prev_fast < prev_slow and curr_fast > curr_slow:
                    signals["crossover"] = "bullish"
                elif prev_fast > prev_slow and curr_fast < curr_slow:
                    signals["crossover"] = "bearish"
                elif curr_fast > curr_slow:
                    signals["crossover"] = "bullish_aligned"
                elif curr_fast < curr_slow:
                    signals["crossover"] = "bearish_aligned"

        except Exception as e:
            logger.error(f"Error detecting EMA crossover: {e}")

        return signals

    def classify_trend(self, bars_df: pd.DataFrame, timeframe: str = "unknown") -> Dict:
        """
        Classify trend as uptrend, downtrend, or ranging.
        Uptrend: price > EMA21 > EMA50, higher highs/lows
        Downtrend: price < EMA21 < EMA50, lower highs/lows
        Ranging: EMAs flat and intertwined
        """
        classification = {
            "trend": "ranging",
            "strength": 0,
            "timeframe": timeframe,
            "details": {}
        }

        try:
            if bars_df is None or len(bars_df) < 50:
                return classification

            if "close" not in bars_df.columns or "high" not in bars_df.columns or "low" not in bars_df.columns:
                return classification

            closes = bars_df["close"]
            highs = bars_df["high"]
            lows = bars_df["low"]

            ema_21 = self.calculate_ema(closes, self.ema_slow)
            ema_50 = self.calculate_ema(closes, self.ema_50)

            if len(ema_21) == 0 or len(ema_50) == 0:
                return classification

            current_price = float(closes.iloc[-1])
            current_ema21 = float(ema_21.iloc[-1])
            current_ema50 = float(ema_50.iloc[-1])

            classification["details"]["current_price"] = current_price
            classification["details"]["ema_21"] = current_ema21
            classification["details"]["ema_50"] = current_ema50

            # Check higher highs/lows (uptrend) or lower highs/lows (downtrend)
            recent_highs = highs.iloc[-20:].values
            recent_lows = lows.iloc[-20:].values

            higher_highs = len([h for i, h in enumerate(recent_highs[:-1]) if h < recent_highs[i+1]]) >= 10
            higher_lows = len([l for i, l in enumerate(recent_lows[:-1]) if l < recent_lows[i+1]]) >= 10
            lower_highs = len([h for i, h in enumerate(recent_highs[:-1]) if h > recent_highs[i+1]]) >= 10
            lower_lows = len([l for i, l in enumerate(recent_lows[:-1]) if l > recent_lows[i+1]]) >= 10

            # Determine trend
            if current_price > current_ema21 > current_ema50:
                if higher_highs and higher_lows:
                    classification["trend"] = "uptrend"
                    classification["strength"] = min(10, 5 + (current_price - current_ema50) / current_ema50 * 100)
            elif current_price < current_ema21 < current_ema50:
                if lower_highs and lower_lows:
                    classification["trend"] = "downtrend"
                    classification["strength"] = min(10, 5 + (current_ema50 - current_price) / current_ema50 * 100)
            else:
                classification["trend"] = "ranging"
                classification["strength"] = 0

        except Exception as e:
            logger.error(f"Error classifying trend: {e}")

        return classification

    def evaluate(self, symbol: str, bars_dict: Dict[str, pd.DataFrame]) -> Dict:
        """
        Evaluate trend signals across multiple timeframes.
        bars_dict keys: "5min", "1hr", "1day", etc.
        """
        result = {
            "ema_crossover": {},
            "trend_classification": {},
            "multi_tf_alignment": None
        }

        try:
            # Get primary timeframe (prefer 1hr for equities, 5min for crypto)
            primary_tf = "1hr" if "1hr" in bars_dict else "5min"

            if primary_tf in bars_dict and bars_dict[primary_tf] is not None:
                result["ema_crossover"] = self.detect_ema_crossover(bars_dict[primary_tf])

            # Classify trend for each timeframe
            trends = []
            for tf, bars_df in bars_dict.items():
                if bars_df is not None and len(bars_df) > 0:
                    classification = self.classify_trend(bars_df, tf)
                    result["trend_classification"][tf] = classification
                    trends.append(classification["trend"])

            # Multi-timeframe alignment
            if len(trends) > 0:
                uptrends = len([t for t in trends if t == "uptrend"])
                downtrends = len([t for t in trends if t == "downtrend"])

                if uptrends > downtrends:
                    result["multi_tf_alignment"] = "bullish"
                elif downtrends > uptrends:
                    result["multi_tf_alignment"] = "bearish"
                else:
                    result["multi_tf_alignment"] = "mixed"

        except Exception as e:
            logger.error(f"Error in TrendSignals.evaluate for {symbol}: {e}")

        return result
