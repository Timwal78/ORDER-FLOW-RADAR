import logging
from typing import Dict, List
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class VolumeSignals:
    def __init__(self, config):
        self.config = config
        self.volume_spike_mult = config.get("VOLUME_SPIKE_MULT", 2.0)
        self.volume_sma_period = config.get("VOLUME_SMA_PERIOD", 20)
        self.cvd_history = {}  # {symbol: cumulative_volume_delta}

    def detect_volume_spike(self, bars_df: pd.DataFrame) -> Dict:
        """
        Compare current bar volume to 20-period SMA.
        Classify: spike on green candle = buying climax, spike on red = selling climax.
        """
        signals = {
            "current_volume": None,
            "volume_sma": None,
            "spike_detected": False,
            "spike_type": None,
            "spike_strength": None
        }

        try:
            if bars_df is None or len(bars_df) < self.volume_sma_period:
                return signals

            if "volume" not in bars_df.columns:
                return signals

            volumes = bars_df["volume"]
            sma = volumes.rolling(window=self.volume_sma_period).mean()

            current_volume = float(volumes.iloc[-1])
            sma_current = float(sma.iloc[-1])

            signals["current_volume"] = current_volume
            signals["volume_sma"] = sma_current

            if sma_current > 0 and current_volume > sma_current * self.volume_spike_mult:
                signals["spike_detected"] = True
                signals["spike_strength"] = current_volume / sma_current

                # Determine spike type (green = bullish, red = bearish)
                if "open" in bars_df.columns and "close" in bars_df.columns:
                    open_price = float(bars_df["open"].iloc[-1])
                    close_price = float(bars_df["close"].iloc[-1])

                    if close_price > open_price:
                        signals["spike_type"] = "buying_climax"
                    elif close_price < open_price:
                        signals["spike_type"] = "selling_climax"
                    else:
                        signals["spike_type"] = "neutral"

        except Exception as e:
            logger.error(f"Error detecting volume spike: {e}")

        return signals

    def calculate_cvd(self, symbol: str, bars_df: pd.DataFrame, trades: List[Dict] = None) -> Dict:
        """
        Calculate cumulative volume delta (buy volume - sell volume).
        Track divergence: price rising but CVD falling = distribution.
        """
        signals = {
            "current_cvd": None,
            "cvd_direction": None,
            "divergence": None
        }

        try:
            if trades is None or len(trades) == 0:
                return signals

            if symbol not in self.cvd_history:
                self.cvd_history[symbol] = {
                    "cvd": 0,
                    "prices": [],
                    "cvd_values": []
                }

            buy_volume = sum(
                float(trade.get("size", 0))
                for trade in trades
                if trade.get("side", "").lower() in ("buy", "b")
            )

            sell_volume = sum(
                float(trade.get("size", 0))
                for trade in trades
                if trade.get("side", "").lower() in ("sell", "s")
            )

            delta = buy_volume - sell_volume
            self.cvd_history[symbol]["cvd"] += delta
            signals["current_cvd"] = self.cvd_history[symbol]["cvd"]

            # Direction
            if delta > 0:
                signals["cvd_direction"] = "bullish"
            elif delta < 0:
                signals["cvd_direction"] = "bearish"
            else:
                signals["cvd_direction"] = "neutral"

            # Track for divergence detection
            if bars_df is not None and len(bars_df) > 0:
                if "close" in bars_df.columns:
                    current_price = float(bars_df["close"].iloc[-1])
                    self.cvd_history[symbol]["prices"].append(current_price)
                    self.cvd_history[symbol]["cvd_values"].append(self.cvd_history[symbol]["cvd"])

                    # Keep last 50 values for divergence
                    if len(self.cvd_history[symbol]["prices"]) > 50:
                        self.cvd_history[symbol]["prices"] = self.cvd_history[symbol]["prices"][-50:]
                        self.cvd_history[symbol]["cvd_values"] = self.cvd_history[symbol]["cvd_values"][-50:]

                    # Detect divergence
                    if len(self.cvd_history[symbol]["prices"]) >= 10:
                        prices = self.cvd_history[symbol]["prices"]
                        cvds = self.cvd_history[symbol]["cvd_values"]

                        # Distribution: price rising, CVD falling
                        if prices[-1] > prices[-10]:
                            if cvds[-1] < cvds[-10]:
                                signals["divergence"] = "distribution"

                        # Accumulation: price falling, CVD rising
                        if prices[-1] < prices[-10]:
                            if cvds[-1] > cvds[-10]:
                                signals["divergence"] = "accumulation"

        except Exception as e:
            logger.error(f"Error calculating CVD for {symbol}: {e}")

        return signals

    def evaluate(self, symbol: str, bars_df: pd.DataFrame, trades: List[Dict] = None) -> Dict:
        """
        Main evaluation method for volume signals.
        bars_df should have columns: volume, open, close
        """
        result = {
            "volume_spike": {},
            "cvd": {}
        }

        try:
            if bars_df is None or len(bars_df) == 0:
                return result

            result["volume_spike"] = self.detect_volume_spike(bars_df)
            result["cvd"] = self.calculate_cvd(symbol, bars_df, trades)

        except Exception as e:
            logger.error(f"Error in VolumeSignals.evaluate for {symbol}: {e}")

        return result
