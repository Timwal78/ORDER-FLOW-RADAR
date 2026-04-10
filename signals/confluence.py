import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import uuid
import asyncio

logger = logging.getLogger(__name__)


class ConfluenceEngine:
    def __init__(self, config, options_recommender=None):
        self.config = config
        self.confluence_min = config.get("CONFLUENCE_MIN", 5.0)
        self.signal_cooldown = config.get("SIGNAL_COOLDOWN_SECONDS", 300)
        self.last_signals = {}  # {symbol: {direction: timestamp}}
        self.options_recommender = options_recommender  # Optional OptionsRecommender instance

        # Default weights (will be overridden by learner if available)
        self.weights = {
            "orderflow_imbalance": 2.0,
            "wall_support": 1.5,
            "absorption": 2.0,
            "rsi_extreme": 1.5,
            "rsi_divergence": 2.0,
            "macd_crossover": 1.0,
            "macd_acceleration": 0.5,
            "vwap_deviation": 1.5,
            "volume_spike": 1.0,
            "cvd_divergence": 1.5,
            "ema_crossover": 1.0,
            "multi_tf_alignment": 2.0,
            "sr_level": 1.5,
            "options_unusual": 1.5,
            "sentiment": 0.5
        }

    def set_weights(self, weights: Dict[str, float]):
        """Update scoring weights from the learner."""
        if weights:
            self.weights.update(weights)
            logger.info(f"Confluence engine weights updated from learner")

    def score_signals(self, all_signals: Dict) -> Dict:
        """
        Score all signals and aggregate for confluence.
        Returns score, contributing factors, and bias.
        """
        score = 0.0
        confluences = []
        bias = "neutral"
        direction = None

        try:
            # Order flow signals
            orderflow = all_signals.get("orderflow", {})

            # Imbalance check
            if orderflow:
                imbalance_sig = orderflow.get("imbalance", {}).get("signal")
                if imbalance_sig:
                    direction_map = {"bid_heavy": "long", "ask_heavy": "short"}
                    new_direction = direction_map.get(imbalance_sig.get("direction"))

                    if new_direction:
                        score += self.weights.get("orderflow_imbalance", 2.0)
                        confluences.append({
                            "factor": "Order Flow Imbalance",
                            "direction": new_direction,
                            "strength": imbalance_sig.get("strength", 0)
                        })
                        direction = new_direction

            # Wall detection
            if orderflow:
                walls = orderflow.get("walls", [])
                for wall in walls:
                    if not wall.get("is_spoof", False):
                        direction_map = {"bid": "long", "ask": "short"}
                        wall_direction = direction_map.get(wall.get("side"))

                        if wall_direction == direction or direction is None:
                            score += self.weights.get("wall_support", 1.5)
                            confluences.append({
                                "factor": f"Wall {wall.get('side').upper()} @ {wall.get('price')}",
                                "direction": wall_direction,
                                "duration": wall.get("duration")
                            })

            # Absorption detection
            if orderflow:
                absorptions = orderflow.get("absorption", [])
                for absorption in absorptions:
                    if absorption.get("held"):
                        direction_map = {"bid": "long", "ask": "short"}
                        abs_direction = direction_map.get(absorption.get("side"))

                        if abs_direction == direction or direction is None:
                            score += self.weights.get("absorption", 2.0)
                            confluences.append({
                                "factor": f"Absorption {absorption.get('side').upper()}",
                                "direction": abs_direction,
                                "volume": absorption.get("absorbed_volume")
                            })

            # Momentum signals
            momentum = all_signals.get("momentum", {})

            # RSI signals
            rsi_sig = momentum.get("rsi", {})
            if rsi_sig:
                if rsi_sig.get("oversold"):
                    score += self.weights.get("rsi_extreme", 1.5)
                    confluences.append({
                        "factor": "RSI Oversold",
                        "direction": "long",
                        "rsi": rsi_sig.get("current_rsi")
                    })
                    if direction is None:
                        direction = "long"

                if rsi_sig.get("overbought"):
                    score += self.weights.get("rsi_extreme", 1.5)
                    confluences.append({
                        "factor": "RSI Overbought",
                        "direction": "short",
                        "rsi": rsi_sig.get("current_rsi")
                    })
                    if direction is None:
                        direction = "short"

                if rsi_sig.get("divergence"):
                    score += self.weights.get("rsi_divergence", 2.0)
                    div_direction = "long" if rsi_sig.get("divergence") == "bullish" else "short"
                    confluences.append({
                        "factor": f"RSI Divergence {rsi_sig.get('divergence')}",
                        "direction": div_direction
                    })

            # MACD signals
            macd_sig = momentum.get("macd", {})
            if macd_sig:
                if macd_sig.get("crossover"):
                    crossover_map = {"bullish": "long", "bearish": "short"}
                    macd_direction = crossover_map.get(macd_sig.get("crossover"))
                    score += self.weights.get("macd_crossover", 1.0)
                    confluences.append({
                        "factor": f"MACD {macd_sig.get('crossover')} Crossover",
                        "direction": macd_direction
                    })

                if macd_sig.get("acceleration"):
                    acc_map = {"bullish": "long", "bearish": "short"}
                    acc_direction = acc_map.get(macd_sig.get("acceleration"))
                    score += self.weights.get("macd_acceleration", 0.5)
                    confluences.append({
                        "factor": f"MACD {macd_sig.get('acceleration')} Acceleration",
                        "direction": acc_direction
                    })

            # VWAP signals
            vwap_sig = momentum.get("vwap_deviation", {})
            if vwap_sig and vwap_sig.get("mean_reversion_signal"):
                score += self.weights.get("vwap_deviation", 1.5)
                confluences.append({
                    "factor": "VWAP Mean Reversion",
                    "direction": vwap_sig.get("mean_reversion_signal"),
                    "deviation": vwap_sig.get("deviation")
                })

            # Volume signals
            volume = all_signals.get("volume", {})

            # Volume spike
            vol_spike = volume.get("volume_spike", {})
            if vol_spike and vol_spike.get("spike_detected"):
                spike_map = {"buying_climax": "long", "selling_climax": "short"}
                spike_direction = spike_map.get(vol_spike.get("spike_type"))

                if spike_direction:
                    score += self.weights.get("volume_spike", 1.0)
                    confluences.append({
                        "factor": f"Volume Spike {vol_spike.get('spike_type')}",
                        "direction": spike_direction,
                        "strength": vol_spike.get("spike_strength")
                    })

            # CVD signals
            cvd_sig = volume.get("cvd", {})
            if cvd_sig and cvd_sig.get("divergence"):
                div_map = {"accumulation": "long", "distribution": "short"}
                cvd_direction = div_map.get(cvd_sig.get("divergence"))
                score += self.weights.get("cvd_divergence", 1.5)
                confluences.append({
                    "factor": f"CVD {cvd_sig.get('divergence')}",
                    "direction": cvd_direction
                })

            # Trend signals
            trend = all_signals.get("trend", {})

            # EMA crossover
            ema_sig = trend.get("ema_crossover", {})
            if ema_sig and ema_sig.get("crossover"):
                score += self.weights.get("ema_crossover", 1.0)

                crossover_map = {
                    "bullish": "long",
                    "bearish": "short",
                    "bullish_aligned": "long",
                    "bearish_aligned": "short"
                }
                ema_direction = crossover_map.get(ema_sig.get("crossover"))
                confluences.append({
                    "factor": "EMA Crossover",
                    "direction": ema_direction
                })

            # Multi-TF alignment
            tf_alignment = trend.get("multi_tf_alignment")
            if tf_alignment and tf_alignment != "mixed":
                alignment_map = {"bullish": "long", "bearish": "short"}
                alignment_direction = alignment_map.get(tf_alignment)
                score += self.weights.get("multi_tf_alignment", 2.0)
                confluences.append({
                    "factor": "Multi-TF Alignment",
                    "direction": alignment_direction,
                    "strength": tf_alignment
                })

            # Levels
            levels = all_signals.get("levels", {})

            # Support/Resistance
            if levels:
                sr_list = levels.get("support_resistance", [])
                if sr_list and len(sr_list) > 0:
                    score += self.weights.get("sr_level", 1.5)
                    confluences.append({
                        "factor": "Price at S/R Zone",
                        "type": sr_list[0].get("type"),
                        "touches": sr_list[0].get("touches")
                    })

            # Determine bias if no direction set
            if direction is None:
                direction = "long" if score > 0 else "short" if score < 0 else "neutral"

            bias = direction

        except Exception as e:
            logger.error(f"Error scoring signals: {e}")

        return {
            "score": max(0, score),
            "confluences": confluences,
            "bias": bias,
            "direction": direction
        }

    def check_cooldown(self, symbol: str, direction: str) -> bool:
        """Check if signal is on cooldown."""
        key = (symbol, direction)

        if key not in self.last_signals:
            return True

        last_time = self.last_signals[key]
        cooldown_passed = (datetime.utcnow() - last_time).total_seconds() > self.signal_cooldown

        return cooldown_passed

    def set_cooldown(self, symbol: str, direction: str):
        """Set cooldown for symbol/direction."""
        key = (symbol, direction)
        self.last_signals[key] = datetime.utcnow()

    def calculate_atr_based_stops(self, current_price: float, atr: Optional[float] = None,
                                  direction: str = "long") -> Dict:
        """Calculate stop loss and take profit based on ATR."""
        multipliers = {
            "stop_loss": 1.0,
            "tp1": 2.0,
            "tp2": 3.5
        }

        if atr is None:
            atr = current_price * 0.02  # Default to 2% if no ATR

        if direction == "long":
            stop_loss = current_price - (atr * multipliers["stop_loss"])
            tp1 = current_price + (atr * multipliers["tp1"])
            tp2 = current_price + (atr * multipliers["tp2"])
        else:
            stop_loss = current_price + (atr * multipliers["stop_loss"])
            tp1 = current_price - (atr * multipliers["tp1"])
            tp2 = current_price - (atr * multipliers["tp2"])

        return {
            "stop_loss": float(stop_loss),
            "tp1": float(tp1),
            "tp2": float(tp2),
            "atr": float(atr)
        }

    def generate_trade_card(self, symbol: str, scoring_result: Dict,
                           current_price: float, atr: Optional[float] = None,
                           timeframe: str = "multi") -> Optional[Dict]:
        """
        Generate trade card if confluence score meets threshold.
        Optionally attaches options recommendations if recommender is available.
        """
        score = scoring_result.get("score", 0)

        if score < self.confluence_min:
            return None

        direction = scoring_result.get("direction", "neutral")

        if direction == "neutral":
            return None

        # Check cooldown
        if not self.check_cooldown(symbol, direction):
            logger.debug(f"Signal on cooldown for {symbol} {direction}")
            return None

        # Set cooldown
        self.set_cooldown(symbol, direction)

        # Calculate stops and targets
        stops = self.calculate_atr_based_stops(current_price, atr, direction)

        # Determine signal quality
        if score >= 9:
            alert_level = "FIRE"
        elif score >= 7:
            alert_level = "GO"
        else:
            alert_level = "WARNING"

        # Calculate risk/reward ratios
        if direction == "long":
            risk = current_price - stops["stop_loss"]
            rr1 = (stops["tp1"] - current_price) / risk if risk > 0 else 0
            rr2 = (stops["tp2"] - current_price) / risk if risk > 0 else 0
        else:
            risk = stops["stop_loss"] - current_price
            rr1 = (current_price - stops["tp1"]) / risk if risk > 0 else 0
            rr2 = (current_price - stops["tp2"]) / risk if risk > 0 else 0

        trade_card = {
            "id": str(uuid.uuid4())[:8],
            "symbol": symbol,
            "direction": direction,
            "entry": float(current_price),
            "stop_loss": float(stops["stop_loss"]),
            "tp1": float(stops["tp1"]),
            "tp2": float(stops["tp2"]),
            "risk_reward_1": float(rr1),
            "risk_reward_2": float(rr2),
            "score": float(score),
            "max_score": 20.0,
            "confluence_count": len(scoring_result.get("confluences", [])),
            "confluences": scoring_result.get("confluences", []),
            "bias": scoring_result.get("bias", "neutral"),
            "timeframe": timeframe,
            "alert_level": alert_level,
            "valid_for_minutes": 60,
            "timestamp": datetime.utcnow().isoformat(),
            "atr": float(atr) if atr else None
        }

        return trade_card

    async def evaluate_async(self, symbol: str, all_signals: Dict, current_price: float,
                            atr: Optional[float] = None, timeframe: str = "multi") -> Optional[Dict]:
        """
        Main async evaluation method: score all signals, generate trade card, and optionally
        attach options recommendations if recommender is available.
        """
        try:
            if not all_signals or current_price <= 0:
                return None

            # Score signals
            scoring = self.score_signals(all_signals)

            # Generate trade card
            trade_card = self.generate_trade_card(
                symbol,
                scoring,
                current_price,
                atr,
                timeframe
            )

            if not trade_card:
                return None

            # Attempt to get options recommendation if recommender is available
            if self.options_recommender:
                try:
                    options_rec = await self.options_recommender.recommend(trade_card)
                    if options_rec:
                        trade_card["options_recommendation"] = options_rec
                except Exception as e:
                    logger.warning(f"Failed to get options recommendation for {symbol}: {e}")

            return trade_card

        except Exception as e:
            logger.error(f"Error in ConfluenceEngine.evaluate_async for {symbol}: {e}")
            return None

    def evaluate(self, symbol: str, all_signals: Dict, current_price: float,
                atr: Optional[float] = None, timeframe: str = "multi") -> Optional[Dict]:
        """Synchronous evaluation method (no options recommendations)."""
        try:
            if not all_signals or current_price <= 0:
                return None

            scoring = self.score_signals(all_signals)

            trade_card = self.generate_trade_card(
                symbol,
                scoring,
                current_price,
                atr,
                timeframe
            )

            return trade_card

        except Exception as e:
            logger.error(f"Error in ConfluenceEngine.evaluate for {symbol}: {e}")
            return None
