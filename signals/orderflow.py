import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import statistics

logger = logging.getLogger(__name__)


@dataclass
class Wall:
    side: str
    price: float
    size: float
    duration: float
    is_spoof: bool


@dataclass
class AbsorptionSignal:
    price: float
    side: str
    absorbed_volume: float
    held: bool


class OrderFlowSignals:
    def __init__(self, config):
        self.config = config
        self.wall_size = config.get("WALL_SIZE", 100000)
        self.wall_timeout = config.get("WALL_TIMEOUT_SECONDS", 30)
        self.spoof_timeout = config.get("SPOOF_TIMEOUT_SECONDS", 10)
        self.imbalance_threshold = config.get("IMBALANCE_THRESHOLD", 0.15)

        self.walls = {}  # {(symbol, side, price): (size, timestamp)}
        self.flow_bias_windows = {}  # {symbol: {window: [(volume, side, timestamp)]}}

    def detect_walls(self, symbol: str, book_data: Dict) -> List[Dict]:
        """
        Scan top 20 levels of bid/ask book for walls.
        Track persistence: >30s = real, <10s pulled = spoofing.
        """
        walls_detected = []

        try:
            bids = book_data.get("bids", [])[:20]
            asks = book_data.get("asks", [])[:20]
            timestamp = datetime.utcnow()

            for side, levels in [("bid", bids), ("ask", asks)]:
                for price, size in levels:
                    wall_key = (symbol, side, price)

                    if size > self.wall_size:
                        if wall_key in self.walls:
                            prev_size, prev_time = self.walls[wall_key]
                            duration = (timestamp - prev_time).total_seconds()

                            if duration > self.wall_timeout:
                                is_spoof = False
                            elif duration < self.spoof_timeout:
                                is_spoof = True
                            else:
                                is_spoof = False

                            walls_detected.append({
                                "side": side,
                                "price": price,
                                "size": size,
                                "duration": duration,
                                "is_spoof": is_spoof
                            })
                            self.walls[wall_key] = (size, timestamp)
                        else:
                            self.walls[wall_key] = (size, timestamp)
                    else:
                        if wall_key in self.walls:
                            del self.walls[wall_key]

            # Cleanup old walls
            keys_to_delete = []
            for wall_key, (_, wall_time) in self.walls.items():
                if (timestamp - wall_time).total_seconds() > 300:
                    keys_to_delete.append(wall_key)
            for key in keys_to_delete:
                del self.walls[key]

        except Exception as e:
            logger.error(f"Error detecting walls for {symbol}: {e}")

        return walls_detected

    def calculate_imbalance(self, symbol: str, book_data: Dict) -> Dict:
        """
        Calculate bid/ask imbalance from top 10 levels.
        imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
        """
        signals = {
            "current_imbalance": None,
            "imbalance_1min": None,
            "imbalance_5min": None,
            "imbalance_15min": None,
            "signal": None
        }

        try:
            bids = book_data.get("bids", [])[:10]
            asks = book_data.get("asks", [])[:10]

            bid_depth = sum(size for _, size in bids)
            ask_depth = sum(size for _, size in asks)

            if bid_depth + ask_depth == 0:
                return signals

            imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
            signals["current_imbalance"] = imbalance

            if symbol not in self.flow_bias_windows:
                self.flow_bias_windows[symbol] = {
                    "1min": [],
                    "5min": [],
                    "15min": []
                }

            now = datetime.utcnow()
            self.flow_bias_windows[symbol]["1min"].append((imbalance, now))
            self.flow_bias_windows[symbol]["5min"].append((imbalance, now))
            self.flow_bias_windows[symbol]["15min"].append((imbalance, now))

            # Cleanup old data
            for window_key, cutoff_mins in [("1min", 1), ("5min", 5), ("15min", 15)]:
                cutoff_time = now - timedelta(minutes=cutoff_mins)
                self.flow_bias_windows[symbol][window_key] = [
                    (val, ts) for val, ts in self.flow_bias_windows[symbol][window_key]
                    if ts > cutoff_time
                ]

                if self.flow_bias_windows[symbol][window_key]:
                    avg = statistics.mean(
                        val for val, _ in self.flow_bias_windows[symbol][window_key]
                    )
                    signals[f"imbalance_{window_key}"] = avg

                    if abs(avg) > self.imbalance_threshold:
                        direction = "bid_heavy" if avg > 0 else "ask_heavy"
                        signals["signal"] = {
                            "window": window_key,
                            "direction": direction,
                            "strength": abs(avg)
                        }

        except Exception as e:
            logger.error(f"Error calculating imbalance for {symbol}: {e}")

        return signals

    def calculate_flow_bias(self, symbol: str, trades: List[Dict]) -> Dict:
        """
        Calculate buy vs sell volume bias over rolling windows.
        flow_bias = buy_volume / (buy_volume + sell_volume)
        """
        signals = {
            "current_bias": None,
            "bias_1min": None,
            "bias_5min": None,
            "bias_15min": None,
            "flip_signal": None
        }

        try:
            if symbol not in self.flow_bias_windows:
                self.flow_bias_windows[symbol] = {
                    "1min": [],
                    "5min": [],
                    "15min": []
                }

            now = datetime.utcnow()

            for trade in trades:
                try:
                    side = trade.get("side", "").lower()
                    size = float(trade.get("size", 0))
                    timestamp = trade.get("timestamp")

                    if not timestamp:
                        timestamp = now
                    elif isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

                    self.flow_bias_windows[symbol]["1min"].append((side, size, timestamp))
                    self.flow_bias_windows[symbol]["5min"].append((side, size, timestamp))
                    self.flow_bias_windows[symbol]["15min"].append((side, size, timestamp))
                except (ValueError, KeyError):
                    continue

            # Calculate bias for each window
            last_bias = signals.get("current_bias")

            for window_key, cutoff_mins in [("1min", 1), ("5min", 5), ("15min", 15)]:
                cutoff_time = now - timedelta(minutes=cutoff_mins)
                self.flow_bias_windows[symbol][window_key] = [
                    item for item in self.flow_bias_windows[symbol][window_key]
                    if item[2] > cutoff_time
                ]

                if self.flow_bias_windows[symbol][window_key]:
                    buy_vol = sum(
                        size for side, size, _ in self.flow_bias_windows[symbol][window_key]
                        if side in ("buy", "b")
                    )
                    sell_vol = sum(
                        size for side, size, _ in self.flow_bias_windows[symbol][window_key]
                        if side in ("sell", "s")
                    )

                    total_vol = buy_vol + sell_vol
                    if total_vol > 0:
                        bias = buy_vol / total_vol
                        signals[f"bias_{window_key}"] = bias

                        if window_key == "1min":
                            signals["current_bias"] = bias

                            if last_bias is not None:
                                if (last_bias < 0.5 and bias >= 0.5) or \
                                   (last_bias >= 0.5 and bias < 0.5):
                                    signals["flip_signal"] = {
                                        "old_bias": last_bias,
                                        "new_bias": bias,
                                        "direction": "bullish" if bias > 0.5 else "bearish"
                                    }

        except Exception as e:
            logger.error(f"Error calculating flow bias for {symbol}: {e}")

        return signals

    def detect_absorption(self, symbol: str, book_data: Dict, trades: List[Dict]) -> List[Dict]:
        """
        Detect when walls are being absorbed by aggressive trades.
        Wall holds if it absorbs >50% and stays in place.
        """
        absorptions = []

        try:
            bids = {price: size for price, size in book_data.get("bids", [])[:20]}
            asks = {price: size for price, size in book_data.get("asks", [])[:20]}

            if symbol not in self.flow_bias_windows:
                self.flow_bias_windows[symbol] = {}

            if "last_book" not in self.flow_bias_windows[symbol]:
                self.flow_bias_windows[symbol]["last_book"] = (bids, asks)
                return absorptions

            last_bids, last_asks = self.flow_bias_windows[symbol]["last_book"]

            # Check for bid wall absorption
            for price, last_size in last_bids.items():
                current_size = bids.get(price, 0)
                if last_size > self.wall_size and current_size < last_size:
                    absorbed = last_size - current_size
                    if absorbed > last_size * 0.5:
                        held = current_size >= last_size * 0.5
                        absorptions.append({
                            "price": price,
                            "side": "bid",
                            "absorbed_volume": absorbed,
                            "held": held
                        })

            # Check for ask wall absorption
            for price, last_size in last_asks.items():
                current_size = asks.get(price, 0)
                if last_size > self.wall_size and current_size < last_size:
                    absorbed = last_size - current_size
                    if absorbed > last_size * 0.5:
                        held = current_size >= last_size * 0.5
                        absorptions.append({
                            "price": price,
                            "side": "ask",
                            "absorbed_volume": absorbed,
                            "held": held
                        })

            self.flow_bias_windows[symbol]["last_book"] = (bids, asks)

        except Exception as e:
            logger.error(f"Error detecting absorption for {symbol}: {e}")

        return absorptions

    def evaluate(self, symbol: str, book_data: Dict, trades: List[Dict] = None) -> Dict:
        """
        Main evaluation method returning all order flow signals.
        """
        if trades is None:
            trades = []

        try:
            walls = self.detect_walls(symbol, book_data)
            imbalance = self.calculate_imbalance(symbol, book_data)
            flow_bias = self.calculate_flow_bias(symbol, trades)
            absorption = self.detect_absorption(symbol, book_data, trades)

            return {
                "walls": walls,
                "imbalance": imbalance,
                "flow_bias": flow_bias,
                "absorption": absorption
            }
        except Exception as e:
            logger.error(f"Error in OrderFlowSignals.evaluate for {symbol}: {e}")
            return {
                "walls": [],
                "imbalance": {},
                "flow_bias": {},
                "absorption": []
            }
