import logging
from typing import Dict, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class MomentumSignals:
    def __init__(self, config):
        self.config = config
        self.rsi_period = config.get("RSI_PERIOD", 14)
        self.rsi_oversold = config.get("RSI_OVERSOLD", 30)
        self.rsi_overbought = config.get("RSI_OVERBOUGHT", 70)
        self.vwap_dev_threshold = config.get("VWAP_DEV_THRESHOLD", 0.02)

        self.price_history = {}  # {symbol: [prices]}
        self.rsi_history = {}  # {symbol: [rsi_values]}

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI from price series."""
        try:
            if len(prices) < period:
                return pd.Series(dtype=float)

            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            return rsi
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}")
            return pd.Series(dtype=float)

    def detect_rsi_signals(self, symbol: str, rsi: pd.Series) -> Dict:
        """Detect RSI oversold/overbought conditions."""
        signals = {
            "current_rsi": None,
            "oversold": False,
            "overbought": False,
            "divergence": None
        }

        try:
            if len(rsi) == 0:
                return signals

            current_rsi = rsi.iloc[-1]
            signals["current_rsi"] = float(current_rsi)

            if current_rsi < self.rsi_oversold:
                signals["oversold"] = True
            elif current_rsi > self.rsi_overbought:
                signals["overbought"] = True

            if len(rsi) >= 20 and symbol in self.price_history:
                prices = self.price_history[symbol]
                if len(prices) >= 20:
                    # Bullish divergence: price new low, RSI higher low
                    price_min_idx = np.argmin(prices[-20:])
                    rsi_slice = rsi.iloc[-20:].values
                    rsi_min_idx = np.argmin(rsi_slice)

                    if price_min_idx > rsi_min_idx and prices[-1] > prices[price_min_idx]:
                        if rsi_slice[-1] > rsi_slice[rsi_min_idx]:
                            signals["divergence"] = "bullish"

                    # Bearish divergence: price new high, RSI lower high
                    price_max_idx = np.argmax(prices[-20:])
                    rsi_max_idx = np.argmax(rsi_slice)

                    if price_max_idx > rsi_max_idx and prices[-1] < prices[price_max_idx]:
                        if rsi_slice[-1] < rsi_slice[rsi_max_idx]:
                            signals["divergence"] = "bearish"

        except Exception as e:
            logger.error(f"Error detecting RSI signals for {symbol}: {e}")

        return signals

    def calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """Calculate MACD, signal line, and histogram."""
        result = {
            "macd": None,
            "signal": None,
            "histogram": None,
            "crossover": None,
            "acceleration": None
        }

        try:
            if len(prices) < slow:
                return result

            ema_fast = prices.ewm(span=fast).mean()
            ema_slow = prices.ewm(span=slow).mean()
            macd = ema_fast - ema_slow
            signal_line = macd.ewm(span=signal).mean()
            histogram = macd - signal_line

            result["macd"] = float(macd.iloc[-1]) if len(macd) > 0 else None
            result["signal"] = float(signal_line.iloc[-1]) if len(signal_line) > 0 else None
            result["histogram"] = float(histogram.iloc[-1]) if len(histogram) > 0 else None

            if len(macd) >= 2:
                prev_macd = macd.iloc[-2]
                curr_macd = macd.iloc[-1]
                prev_signal = signal_line.iloc[-2]
                curr_signal = signal_line.iloc[-1]

                if (prev_macd < prev_signal and curr_macd > curr_signal):
                    result["crossover"] = "bullish"
                elif (prev_macd > prev_signal and curr_macd < curr_signal):
                    result["crossover"] = "bearish"

            if len(histogram) >= 2:
                prev_hist = histogram.iloc[-2]
                curr_hist = histogram.iloc[-1]

                if curr_hist > 0 and curr_hist > prev_hist:
                    result["acceleration"] = "bullish"
                elif curr_hist < 0 and curr_hist < prev_hist:
                    result["acceleration"] = "bearish"

        except Exception as e:
            logger.error(f"Error calculating MACD: {e}")

        return result

    def calculate_vwap_deviation(self, current_price: float, vwap: Optional[float],
                                 rsi: Optional[float] = None) -> Dict:
        """
        Compare price to VWAP.
        Mean reversion: below VWAP + oversold = long, above VWAP + overbought = short.
        """
        signals = {
            "deviation": None,
            "position": None,
            "mean_reversion_signal": None
        }

        try:
            if vwap is None or vwap == 0:
                return signals

            deviation = (current_price - vwap) / vwap
            signals["deviation"] = deviation

            if current_price < vwap:
                signals["position"] = "below"
            elif current_price > vwap:
                signals["position"] = "above"
            else:
                signals["position"] = "at"

            if abs(deviation) > self.vwap_dev_threshold:
                if current_price < vwap and rsi is not None and rsi < 30:
                    signals["mean_reversion_signal"] = "long"
                elif current_price > vwap and rsi is not None and rsi > 70:
                    signals["mean_reversion_signal"] = "short"

        except Exception as e:
            logger.error(f"Error calculating VWAP deviation: {e}")

        return signals

    def evaluate(self, symbol: str, bars_df: pd.DataFrame, vwap: Optional[float] = None) -> Dict:
        """
        Main evaluation method for momentum signals.
        bars_df should have columns: close, volume, high, low
        """
        result = {
            "rsi": {},
            "macd": {},
            "vwap_deviation": {}
        }

        try:
            if bars_df is None or len(bars_df) == 0:
                return result

            closes = bars_df["close"] if "close" in bars_df.columns else bars_df.iloc[:, 0]

            # Store price history for divergence detection
            if symbol not in self.price_history:
                self.price_history[symbol] = []

            self.price_history[symbol].extend(closes.tolist())
            if len(self.price_history[symbol]) > 100:
                self.price_history[symbol] = self.price_history[symbol][-100:]

            # Calculate RSI
            rsi = self.calculate_rsi(closes, self.rsi_period)
            result["rsi"] = self.detect_rsi_signals(symbol, rsi)

            # Calculate MACD
            result["macd"] = self.calculate_macd(closes)

            # Calculate VWAP deviation
            if len(bars_df) > 0:
                current_price = float(closes.iloc[-1])
                result["vwap_deviation"] = self.calculate_vwap_deviation(
                    current_price,
                    vwap,
                    rsi.iloc[-1] if len(rsi) > 0 else None
                )

        except Exception as e:
            logger.error(f"Error in MomentumSignals.evaluate for {symbol}: {e}")

        return result
