import logging
from typing import Dict, List
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class LevelSignals:
    def __init__(self, config):
        self.config = config
        self.cluster_threshold = config.get("LEVEL_CLUSTER_THRESHOLD", 0.003)  # 0.3%
        self.level_history = {}  # {symbol: {price: touch_count}}
        self.last_tested = {}  # {symbol: {price: timestamp}}

    def find_swing_levels(self, bars_df: pd.DataFrame, lookback: int = 50) -> Dict[str, List[float]]:
        """
        Identify swing highs and lows.
        Swing high: candle higher than N candles on each side
        Swing low: candle lower than N candles on each side
        """
        levels = {"highs": [], "lows": []}

        try:
            if bars_df is None or len(bars_df) < lookback:
                return levels

            if "high" not in bars_df.columns or "low" not in bars_df.columns:
                return levels

            highs = bars_df["high"].values
            lows = bars_df["low"].values

            # Look for swings in recent data
            period = 5  # 5 candles on each side

            for i in range(period, len(highs) - period):
                # Swing high
                if highs[i] == max(highs[i-period:i+period]):
                    if highs[i] not in levels["highs"]:
                        levels["highs"].append(float(highs[i]))

                # Swing low
                if lows[i] == min(lows[i-period:i+period]):
                    if lows[i] not in levels["lows"]:
                        levels["lows"].append(float(lows[i]))

            # Clean up duplicates
            levels["highs"] = sorted(list(set(levels["highs"])))
            levels["lows"] = sorted(list(set(levels["lows"])))

        except Exception as e:
            logger.error(f"Error finding swing levels: {e}")

        return levels

    def cluster_levels(self, levels: List[float], threshold: float) -> List[float]:
        """
        Cluster nearby levels within threshold percentage.
        """
        if not levels or len(levels) < 2:
            return levels

        try:
            clustered = []
            levels = sorted(levels)
            current_cluster = [levels[0]]

            for level in levels[1:]:
                pct_diff = abs((level - current_cluster[0]) / current_cluster[0])

                if pct_diff <= threshold:
                    current_cluster.append(level)
                else:
                    # Close current cluster
                    clustered.append(np.mean(current_cluster))
                    current_cluster = [level]

            if current_cluster:
                clustered.append(np.mean(current_cluster))

            return sorted(clustered)
        except Exception as e:
            logger.error(f"Error clustering levels: {e}")
            return levels

    def identify_support_resistance(self, bars_df: pd.DataFrame, symbol: str) -> List[Dict]:
        """
        Identify support and resistance levels with touch counts.
        """
        levels = []

        try:
            if bars_df is None or len(bars_df) == 0:
                return levels

            if "high" not in bars_df.columns or "low" not in bars_df.columns:
                return levels

            # Find swings
            swings = self.find_swing_levels(bars_df)
            all_levels = swings["highs"] + swings["lows"]

            if not all_levels:
                return levels

            # Cluster levels
            clustered = self.cluster_levels(all_levels, self.cluster_threshold)

            # Initialize level history if needed
            if symbol not in self.level_history:
                self.level_history[symbol] = {}
                self.last_tested[symbol] = {}

            # Update touch counts based on recent price action
            closes = bars_df["close"].values if "close" in bars_df.columns else []

            for level in clustered:
                touches = 0

                # Count how many times price touched this level
                for close in closes[-50:]:  # Last 50 candles
                    if abs(close - level) <= level * self.cluster_threshold:
                        touches += 1

                if symbol in self.level_history:
                    self.level_history[symbol][level] = touches
                else:
                    self.level_history[symbol] = {level: touches}

                level_type = "resistance" if level in swings["highs"] else "support"

                levels.append({
                    "price": float(level),
                    "type": level_type,
                    "touches": touches,
                    "last_tested": self.last_tested[symbol].get(level)
                })

            # Sort by touches (strongest levels first)
            levels = sorted(levels, key=lambda x: x["touches"], reverse=True)

        except Exception as e:
            logger.error(f"Error identifying support/resistance for {symbol}: {e}")

        return levels

    def detect_round_numbers(self, current_price: float, symbol: str) -> List[Dict]:
        """
        Detect psychological round number levels.
        Equities: $5, $10 increments
        Crypto: $100, $1000 increments
        """
        levels = []

        try:
            is_crypto = symbol.upper().endswith("USDT") or symbol.upper().endswith("USD")

            if is_crypto:
                # Crypto: $100, $500, $1000
                increments = [100, 500, 1000]
                base = round(current_price, -3)
            else:
                # Equities: $5, $10, $50
                increments = [5, 10, 50]
                base = round(current_price, -1)

            # Find round levels around current price
            price_range = current_price * 0.1  # 10% range

            for increment in increments:
                # Levels above
                level = base
                while level < current_price + price_range:
                    if abs(level - current_price) > price_range * 0.1:
                        levels.append({
                            "price": float(level),
                            "type": "round",
                            "touches": 0,
                            "strength": "psychological"
                        })
                    level += increment

                # Levels below
                level = base
                while level > current_price - price_range:
                    if abs(level - current_price) > price_range * 0.1:
                        levels.append({
                            "price": float(level),
                            "type": "round",
                            "touches": 0,
                            "strength": "psychological"
                        })
                    level -= increment

            # Remove duplicates
            seen = set()
            unique_levels = []
            for level in levels:
                price = round(level["price"], 2)
                if price not in seen:
                    seen.add(price)
                    unique_levels.append(level)

            levels = sorted(unique_levels, key=lambda x: abs(x["price"] - current_price))

        except Exception as e:
            logger.error(f"Error detecting round numbers for {symbol}: {e}")

        return levels

    def evaluate(self, symbol: str, bars_df: pd.DataFrame, current_price: float) -> Dict:
        """
        Main evaluation method for support/resistance levels.
        """
        result = {
            "support_resistance": [],
            "round_levels": [],
            "nearest_support": None,
            "nearest_resistance": None
        }

        try:
            if bars_df is None or len(bars_df) == 0 or current_price <= 0:
                return result

            # Identify S/R levels
            sr_levels = self.identify_support_resistance(bars_df, symbol)
            result["support_resistance"] = sr_levels

            # Detect round numbers
            round_levels = self.detect_round_numbers(current_price, symbol)
            result["round_levels"] = round_levels[:5]  # Top 5 nearest

            # Find nearest support and resistance
            if sr_levels:
                support_levels = [l for l in sr_levels if l["type"] == "support" and l["price"] < current_price]
                resistance_levels = [l for l in sr_levels if l["type"] == "resistance" and l["price"] > current_price]

                if support_levels:
                    result["nearest_support"] = max(support_levels, key=lambda x: x["price"])

                if resistance_levels:
                    result["nearest_resistance"] = min(resistance_levels, key=lambda x: x["price"])

        except Exception as e:
            logger.error(f"Error in LevelSignals.evaluate for {symbol}: {e}")

        return result
