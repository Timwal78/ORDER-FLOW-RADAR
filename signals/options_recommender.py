"""
Options Recommendation Engine for Order Flow Radar.
Two-tier system:
  1. Schwab API: Real chain data when available (preferred).
  2. Algorithmic: Smart strike/date/grade calculation from trade card data (always works).
Every qualified signal WILL get an options recommendation with strike, date, and grade.
"""

import asyncio
import logging
import math
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
import aiohttp

import config

logger = logging.getLogger(__name__)


# ─── Grade thresholds ───────────────────────────────────────────
GRADE_THRESHOLDS = [
    (9.5, "A+"), (8.5, "A"), (7.5, "A-"),
    (6.5, "B+"), (6.0, "B"), (5.5, "B-"),
    (5.0, "C+"), (4.0, "C"), (0.0, "C-"),
]


def _letter_grade(composite_score: float) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if composite_score >= threshold:
            return grade
    return "C-"


def _next_friday(from_date: date, weeks_ahead: int = 0) -> date:
    """Return the next Friday on or after *from_date*, offset by *weeks_ahead*."""
    days_ahead = (4 - from_date.weekday()) % 7  # 4 = Friday
    if days_ahead == 0 and weeks_ahead == 0:
        days_ahead = 7  # don't use today if it's already Friday
    target = from_date + timedelta(days=days_ahead + 7 * weeks_ahead)
    return target


def _standard_strike(price: float, direction: str, offset_pct: float) -> float:
    """Round to the nearest standard strike increment."""
    if price < 5:
        increment = 0.50
    elif price < 25:
        increment = 1.0
    elif price < 100:
        increment = 2.50
    elif price < 250:
        increment = 5.0
    else:
        increment = 10.0

    if direction == "long":
        raw = price * (1 + offset_pct)
        return math.ceil(raw / increment) * increment
    else:
        raw = price * (1 - offset_pct)
        return math.floor(raw / increment) * increment


class OptionsRecommender:
    """Recommends specific options contracts for trade setups."""

    def __init__(self, schwab_handler=None):
        self.schwab = schwab_handler
        self.app_key = config.SCHWAB_APP_KEY
        self.app_secret = config.SCHWAB_APP_SECRET
        self.refresh_token = config.SCHWAB_REFRESH_TOKEN
        self.token_url = config.SCHWAB_TOKEN_URL
        self.base_url = config.SCHWAB_BASE

        self.access_token = None
        self.token_expiry_time = 0

    # ─── PUBLIC API ──────────────────────────────────────────────
    async def recommend(self, trade_card: dict) -> Optional[dict]:
        """
        Generate an options recommendation for a trade card.
        Tries Schwab first; falls back to algorithmic recommendation.
        ALWAYS returns a recommendation for valid trade cards.
        """
        try:
            if not trade_card or not trade_card.get("symbol"):
                return None

            symbol = trade_card.get("symbol", "").upper()
            direction = trade_card.get("direction", "").lower()
            current_price = trade_card.get("entry", 0)

            if not symbol or direction not in ["long", "short"] or current_price <= 0:
                return None

            # ── Tier 1: Try Schwab real chain data ──
            schwab_rec = await self._recommend_from_schwab(trade_card)
            if schwab_rec:
                logger.info(f"Options rec for {symbol}: Schwab chain data")
                return schwab_rec

            # ── Tier 2: Algorithmic recommendation (always works) ──
            algo_rec = self._recommend_algorithmic(trade_card)
            if algo_rec:
                logger.info(f"Options rec for {symbol}: Algorithmic")
                return algo_rec

            return None

        except Exception as e:
            logger.error(f"Options recommender error for {trade_card.get('symbol', '?')}: {e}")
            return None

    # ─── ALGORITHMIC RECOMMENDATION ENGINE ───────────────────────
    def _recommend_algorithmic(self, trade_card: dict) -> Optional[dict]:
        """
        Generate options recommendation purely from trade card data.
        Calculates optimal strike, expiry, and grade without any API.
        """
        try:
            symbol = trade_card.get("symbol", "").upper()
            direction = trade_card.get("direction", "").lower()
            entry = float(trade_card.get("entry", 0))
            stop_loss = float(trade_card.get("stop_loss", 0))
            tp1 = float(trade_card.get("tp1", 0))
            tp2 = float(trade_card.get("tp2", 0))
            score = float(trade_card.get("score", 0))
            timeframe = trade_card.get("timeframe", "multi").lower()
            rr1 = float(trade_card.get("risk_reward_1", 0))
            rr2 = float(trade_card.get("risk_reward_2", 0))
            confluence_count = int(trade_card.get("confluence_count", 0))

            if entry <= 0:
                return None

            option_type = "CALL" if direction == "long" else "PUT"
            today = date.today()

            # ── Calculate DTE based on timeframe ──
            if timeframe in ["scalp", "intraday"]:
                dte_target = 5
                expiry_date = _next_friday(today, 0)
                if (expiry_date - today).days < 2:
                    expiry_date = _next_friday(today, 1)
            elif timeframe == "swing":
                dte_target = 21
                expiry_date = _next_friday(today, 3)
            elif timeframe == "24/7":
                dte_target = 14
                expiry_date = _next_friday(today, 2)
            else:  # multi
                dte_target = 30
                expiry_date = _next_friday(today, 4)

            actual_dte = (expiry_date - today).days

            # ── Calculate strikes ──
            # Primary: near ATM (slightly OTM for better R:R)
            primary_strike = _standard_strike(entry, direction, 0.01)
            # Alt 1: ATM
            alt1_strike = _standard_strike(entry, direction, 0.00)
            # Alt 2: slightly more OTM (cheaper, more leveraged)
            alt2_strike = _standard_strike(entry, direction, 0.03)

            # ── Estimate premium using Black-Scholes-lite ──
            risk_per_share = abs(entry - stop_loss) if stop_loss else entry * 0.02
            iv_estimate = min(max(risk_per_share / entry * 4, 0.20), 1.50)

            # Simplified premium estimate: premium ≈ price × IV × sqrt(DTE/365) × adjustment
            time_factor = math.sqrt(actual_dte / 365)
            primary_premium = round(entry * iv_estimate * time_factor * 0.4, 2)
            primary_premium = max(primary_premium, 0.10)

            alt1_premium = round(primary_premium * 1.15, 2)  # ATM costs more
            alt2_premium = round(primary_premium * 0.65, 2)  # OTM costs less

            # ── Calculate composite grade ──
            # Grade factors: confluence score, risk/reward, confluence count, timeframe alignment
            grade_score = 0.0
            grade_score += min(score / 2, 5.0)  # Score contributes up to 5 pts
            grade_score += min(rr1 * 1.5, 3.0)  # R:R contributes up to 3 pts
            grade_score += min(confluence_count * 0.4, 2.0)  # Confluences up to 2 pts

            grade = _letter_grade(grade_score)

            # ── Calculate risk/reward for options ──
            if direction == "long":
                stock_move_tp1 = tp1 - entry
                stock_move_tp2 = tp2 - entry
            else:
                stock_move_tp1 = entry - tp1
                stock_move_tp2 = entry - tp2

            delta_estimate = 0.45  # near-ATM delta
            opt_return_tp1 = abs(delta_estimate * stock_move_tp1) * 100
            opt_return_tp2 = abs(delta_estimate * stock_move_tp2) * 100
            max_risk = primary_premium * 100

            opt_rr = opt_return_tp1 / max_risk if max_risk > 0 else 0

            # ── Breakeven ──
            if option_type == "CALL":
                breakeven = primary_strike + primary_premium
            else:
                breakeven = primary_strike - primary_premium

            # ── Format expiry ──
            expiry_str = expiry_date.strftime("%Y-%m-%d")
            expiry_display = expiry_date.strftime("%m/%d")

            # ── Build contract names ──
            contract_name = f"{symbol} {expiry_display} ${primary_strike:.0f} {option_type}"
            alt1_name = f"{symbol} {expiry_display} ${alt1_strike:.0f} {option_type}"
            alt2_exp = _next_friday(today, (actual_dte // 7) + 1)
            alt2_exp_display = alt2_exp.strftime("%m/%d")
            alt2_name = f"{symbol} {alt2_exp_display} ${alt2_strike:.0f} {option_type}"

            # ── Build reasoning ──
            reasons = []
            if score >= 8:
                reasons.append(f"Strong confluence ({score:.1f})")
            elif score >= 6:
                reasons.append(f"Solid confluence ({score:.1f})")
            else:
                reasons.append(f"Moderate confluence ({score:.1f})")

            reasons.append(f"{actual_dte} DTE")

            if rr1 >= 2.0:
                reasons.append(f"Excellent R:R ({rr1:.1f}:1)")
            elif rr1 >= 1.5:
                reasons.append(f"Good R:R ({rr1:.1f}:1)")

            reasons.append(f"Near-ATM δ≈0.45")

            primary_pick = {
                "contract": contract_name,
                "strike": primary_strike,
                "expiry": expiry_str,
                "type": option_type,
                "dte": actual_dte,
                "bid": round(primary_premium * 0.95, 2),
                "ask": round(primary_premium * 1.05, 2),
                "mid": primary_premium,
                "last": primary_premium,
                "volume": 0,
                "open_interest": 0,
                "implied_volatility": round(iv_estimate, 3),
                "delta": delta_estimate if direction == "long" else -delta_estimate,
                "gamma": round(0.02 / max(entry / 100, 1), 4),
                "theta": round(-primary_premium / max(actual_dte, 1) * 0.7, 4),
                "vega": round(entry * 0.01 * time_factor, 3),
                "score": round(grade_score, 1),
                "grade": grade,
                "max_risk_per_contract": round(max_risk, 2),
                "estimated_return_tp1": round(opt_return_tp1, 2),
                "estimated_return_tp2": round(opt_return_tp2, 2),
                "risk_reward": f"{opt_rr:.1f}:1" if opt_rr > 0 else "N/A",
                "breakeven": round(breakeven, 2),
                "reasoning": ", ".join(reasons),
                "data_source": "algorithmic",
            }

            # ── Alternatives ──
            alt1_pick = {
                "contract": alt1_name,
                "strike": alt1_strike,
                "expiry": expiry_str,
                "type": option_type,
                "dte": actual_dte,
                "mid": alt1_premium,
                "grade": _letter_grade(grade_score - 0.5),
                "delta": 0.50 if direction == "long" else -0.50,
                "max_risk_per_contract": round(alt1_premium * 100, 2),
                "breakeven": round((alt1_strike + alt1_premium) if option_type == "CALL" else (alt1_strike - alt1_premium), 2),
                "reasoning": f"ATM strike, higher delta, {actual_dte} DTE",
                "data_source": "algorithmic",
            }

            alt2_dte = (alt2_exp - today).days
            alt2_pick = {
                "contract": alt2_name,
                "strike": alt2_strike,
                "expiry": alt2_exp.strftime("%Y-%m-%d"),
                "type": option_type,
                "dte": alt2_dte,
                "mid": alt2_premium,
                "grade": _letter_grade(grade_score - 1.0),
                "delta": 0.35 if direction == "long" else -0.35,
                "max_risk_per_contract": round(alt2_premium * 100, 2),
                "breakeven": round((alt2_strike + alt2_premium) if option_type == "CALL" else (alt2_strike - alt2_premium), 2),
                "reasoning": f"OTM strike, cheaper premium, {alt2_dte} DTE",
                "data_source": "algorithmic",
            }

            return {
                "primary_pick": primary_pick,
                "alternatives": [alt1_pick, alt2_pick],
                "options_flow_context": {
                    "put_call_ratio": 0.50,
                    "unusual_activity_count": 0,
                    "unusual_activity": [],
                    "smart_money_bias": "neutral",
                },
                "grade": grade,
                "data_source": "algorithmic",
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Algorithmic recommendation error: {e}")
            return None

    # ─── SCHWAB TIER ─────────────────────────────────────────────
    async def _recommend_from_schwab(self, trade_card: dict) -> Optional[dict]:
        """Try to generate recommendation from Schwab chain data."""
        try:
            symbol = trade_card.get("symbol", "").upper()
            direction = trade_card.get("direction", "").lower()
            current_price = trade_card.get("entry", 0)
            timeframe = trade_card.get("timeframe", "multi").lower()

            chain_data = await self._fetch_options_chain(symbol)
            if not chain_data:
                return None

            option_type = "CALL" if direction == "long" else "PUT"
            dte_range = self._get_dte_range(timeframe)

            contracts = self._parse_schwab_chain(chain_data, option_type, current_price, dte_range)
            if not contracts:
                return None

            scored_contracts = []
            for contract in contracts:
                sc = self._score_contract(contract, trade_card)
                scored_contracts.append({"contract": contract, "score": sc})

            scored_contracts.sort(key=lambda x: x["score"], reverse=True)
            if not scored_contracts:
                return None

            primary = scored_contracts[0]["contract"]
            alternatives = [scored_contracts[i]["contract"] for i in range(1, min(3, len(scored_contracts)))]

            primary_enriched = self._enrich_contract(primary, trade_card, scored_contracts[0]["score"])
            alternatives_enriched = [
                self._enrich_contract(alt, trade_card, scored_contracts[i + 1]["score"])
                for i, alt in enumerate(alternatives)
            ]

            flow_context = self._extract_flow_context(chain_data)

            return {
                "primary_pick": primary_enriched,
                "alternatives": alternatives_enriched,
                "options_flow_context": flow_context,
                "grade": primary_enriched.get("grade", "B"),
                "data_source": "schwab",
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Schwab recommendation error: {e}")
            return None

    # ─── HELPERS ─────────────────────────────────────────────────
    def _get_dte_range(self, timeframe: str) -> Tuple[int, int]:
        timeframe = timeframe.lower()
        if timeframe in ["scalp", "intraday"]:
            return (1, 7)
        elif timeframe == "swing":
            return (14, 45)
        else:
            return (21, 60)

    async def _fetch_options_chain(self, symbol: str) -> Optional[Dict]:
        try:
            if self.schwab and self.schwab.access_token:
                return self.schwab.options_chains.get(symbol, None)

            await self._refresh_token_if_needed()
            if not self.access_token:
                return None

            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.access_token}"}
                url = f"{self.base_url}/chains"
                params = {
                    "symbol": symbol,
                    "contractType": "ALL",
                    "strikeCount": 20,
                    "includeUnderlyingQuote": "true",
                    "strategy": "SINGLE",
                }
                async with session.get(url, headers=headers, params=params,
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")
            return None

    async def _refresh_token_if_needed(self) -> None:
        import time
        import base64

        current_time = time.time()
        if self.access_token is None or current_time >= self.token_expiry_time:
            try:
                credentials = f"{self.app_key}:{self.app_secret}"
                encoded_credentials = base64.b64encode(credentials.encode()).decode()
                headers = {
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}

                async with aiohttp.ClientSession() as session:
                    async with session.post(self.token_url, headers=headers, data=data,
                                            timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            self.access_token = result.get("access_token")
                            expires_in = result.get("expires_in", 1800)
                            self.token_expiry_time = time.time() + expires_in - 60
                        else:
                            logger.debug(f"Schwab token refresh failed: {resp.status}")
            except Exception as e:
                logger.debug(f"Schwab token refresh error: {e}")

    def _parse_schwab_chain(self, chain_data: dict, option_type: str,
                            current_price: float, dte_range: Tuple[int, int]) -> List[Dict]:
        try:
            contracts = []
            exp_map_key = "callExpDateMap" if option_type == "CALL" else "putExpDateMap"
            exp_map = chain_data.get(exp_map_key, {})
            if not exp_map:
                return []

            min_dte, max_dte = dte_range
            for expiry_str, strike_map in exp_map.items():
                try:
                    expiry_date = expiry_str.split(":")[0]
                    dte = int(expiry_str.split(":")[1])
                except (ValueError, IndexError):
                    continue
                if dte < min_dte or dte > max_dte:
                    continue

                for strike_str, contract_list in strike_map.items():
                    try:
                        strike = float(strike_str)
                    except ValueError:
                        continue

                    if option_type == "CALL":
                        if strike < current_price or strike > current_price * 1.05:
                            continue
                    else:
                        if strike > current_price or strike < current_price * 0.95:
                            continue

                    if contract_list and len(contract_list) > 0:
                        contract = contract_list[0]
                        bid = contract.get("bid", 0)
                        ask = contract.get("ask", 0)
                        if bid <= 0 or ask <= 0:
                            continue

                        contracts.append({
                            "strike": strike, "expiry": expiry_date, "dte": dte,
                            "type": option_type, "bid": bid, "ask": ask,
                            "mid": (bid + ask) / 2,
                            "last": contract.get("last", (bid + ask) / 2),
                            "volume": contract.get("totalVolume", 0),
                            "open_interest": contract.get("openInterest", 0),
                            "implied_volatility": contract.get("impliedVolatility", 0),
                            "delta": contract.get("delta", 0),
                            "gamma": contract.get("gamma", 0),
                            "theta": contract.get("theta", 0),
                            "vega": contract.get("vega", 0),
                        })
            return contracts
        except Exception as e:
            logger.error(f"Error parsing Schwab chain: {e}")
            return []

    def _score_contract(self, contract: dict, trade_card: dict) -> float:
        score = 0.0
        try:
            vol = float(contract.get("volume", 0))
            oi = float(contract.get("open_interest", 1))
            vol_oi = vol / max(oi, 1)
            if vol_oi > 1.0:
                score += 2.0
            elif vol_oi > 0.5:
                score += 1.0
            elif vol_oi < 0.1:
                score -= 1.0

            bid = float(contract.get("bid", 0))
            ask = float(contract.get("ask", 0))
            mid = (bid + ask) / 2
            if mid > 0:
                spread_pct = (ask - bid) / mid
                if spread_pct < 0.05:
                    score += 2.0
                elif spread_pct < 0.10:
                    score += 1.0
                elif spread_pct > 0.20:
                    score -= 1.0

            delta = abs(float(contract.get("delta", 0)))
            if 0.35 <= delta <= 0.55:
                score += 2.0
            elif 0.30 <= delta <= 0.60:
                score += 1.0
            elif delta < 0.20 or delta > 0.80:
                score -= 1.0

            if 0.50 <= mid <= 20.0:
                score += 1.0

            dte = int(contract.get("dte", 0))
            timeframe = trade_card.get("timeframe", "multi").lower()
            if timeframe in ["scalp", "intraday"]:
                if 1 <= dte <= 7:
                    score += 1.5
            elif timeframe == "swing":
                if 14 <= dte <= 45:
                    score += 1.5
            else:
                if 21 <= dte <= 60:
                    score += 1.0

            iv = float(contract.get("implied_volatility", 0))
            if 0.20 <= iv <= 0.80:
                score += 0.5

            # Add grade to Schwab contracts too
            trade_score = float(trade_card.get("score", 0))
            rr1 = float(trade_card.get("risk_reward_1", 0))
            confluence_count = int(trade_card.get("confluence_count", 0))
            grade_score = min(trade_score / 2, 5.0) + min(rr1 * 1.5, 3.0) + min(confluence_count * 0.4, 2.0)
            contract["grade"] = _letter_grade(grade_score)

        except Exception as e:
            logger.error(f"Error scoring contract: {e}")
        return score

    def _enrich_contract(self, contract: dict, trade_card: dict, contract_score: float) -> dict:
        try:
            strike = float(contract.get("strike", 0))
            ask = float(contract.get("ask", 0))
            mid = float(contract.get("mid", 0))
            bid = float(contract.get("bid", 0))
            delta = float(contract.get("delta", 0))
            option_type = contract.get("type", "CALL")
            direction = trade_card.get("direction", "").lower()
            entry = float(trade_card.get("entry", 0))
            tp1 = float(trade_card.get("tp1", 0))

            max_risk_per_contract = ask * 100

            if direction == "long":
                stock_move = tp1 - entry
            else:
                stock_move = entry - tp1

            estimated_option_return = abs(delta * stock_move) * 100
            risk_reward = estimated_option_return / max_risk_per_contract if max_risk_per_contract > 0 else 0

            if option_type == "CALL":
                breakeven = strike + ask
            else:
                breakeven = strike - ask

            expiry = contract.get("expiry", "")
            expiry_formatted = expiry[-5:] if len(expiry) >= 5 else expiry
            contract_name = f"{trade_card.get('symbol', '')} {expiry_formatted} ${strike:.0f} {option_type}"

            return {
                "contract": contract_name,
                "strike": strike,
                "expiry": expiry,
                "type": option_type,
                "dte": int(contract.get("dte", 0)),
                "bid": bid, "ask": ask, "mid": mid,
                "last": float(contract.get("last", mid)),
                "volume": int(contract.get("volume", 0)),
                "open_interest": int(contract.get("open_interest", 0)),
                "implied_volatility": float(contract.get("implied_volatility", 0)),
                "delta": delta,
                "gamma": float(contract.get("gamma", 0)),
                "theta": float(contract.get("theta", 0)),
                "vega": float(contract.get("vega", 0)),
                "score": round(contract_score, 1),
                "grade": contract.get("grade", "B"),
                "max_risk_per_contract": round(max_risk_per_contract, 2),
                "estimated_return_tp1": round(estimated_option_return, 2),
                "risk_reward": f"{risk_reward:.1f}:1" if risk_reward > 0 else "N/A",
                "breakeven": round(breakeven, 2),
                "reasoning": self._generate_reasoning(contract, contract_score),
                "data_source": "schwab",
            }
        except Exception as e:
            logger.error(f"Error enriching contract: {e}")
            return contract

    def _generate_reasoning(self, contract: dict, score: float) -> str:
        reasons = []
        vol = float(contract.get("volume", 0))
        oi = float(contract.get("open_interest", 1))
        vol_oi = vol / max(oi, 1)
        if vol_oi > 1.0:
            reasons.append(f"High vol/OI ({vol_oi:.2f})")

        bid = float(contract.get("bid", 0))
        ask = float(contract.get("ask", 0))
        mid = (bid + ask) / 2
        if mid > 0:
            spread_pct = (ask - bid) / mid
            if spread_pct < 0.10:
                reasons.append(f"Tight spread ({spread_pct*100:.1f}%)")

        delta = abs(float(contract.get("delta", 0)))
        if 0.35 <= delta <= 0.55:
            reasons.append(f"Optimal delta ({delta:.2f})")

        dte = int(contract.get("dte", 0))
        reasons.append(f"{dte} DTE")
        return ", ".join(reasons) if reasons else "Selected contract"

    def _extract_flow_context(self, chain_data: dict) -> dict:
        try:
            total_call_vol = 0
            total_put_vol = 0
            unusual = []

            for contract_list in [chain_data.get("callExpDateMap", {}), chain_data.get("putExpDateMap", {})]:
                is_put = contract_list == chain_data.get("putExpDateMap", {})
                for expiry, strike_map in contract_list.items():
                    for strike, contracts in strike_map.items():
                        for contract in contracts:
                            volume = float(contract.get("totalVolume", 0))
                            open_interest = float(contract.get("openInterest", 0))
                            if is_put:
                                total_put_vol += volume
                            else:
                                total_call_vol += volume
                            if open_interest > 0 and volume > 3 * open_interest:
                                unusual.append({
                                    "strike": strike, "expiry": expiry,
                                    "type": "PUT" if is_put else "CALL",
                                    "volume": volume, "open_interest": open_interest,
                                    "volume_oi_ratio": round(volume / open_interest, 2),
                                })

            total_vol = total_put_vol + total_call_vol
            pcr = total_put_vol / total_vol if total_vol > 0 else 0.5

            if pcr > 0.70:
                sentiment = "bearish"
            elif pcr > 0.55:
                sentiment = "slightly_bearish"
            elif pcr < 0.30:
                sentiment = "bullish"
            elif pcr < 0.45:
                sentiment = "slightly_bullish"
            else:
                sentiment = "neutral"

            return {
                "put_call_ratio": round(pcr, 2),
                "unusual_activity_count": len(unusual),
                "unusual_activity": unusual[:5],
                "smart_money_bias": sentiment,
            }
        except Exception as e:
            logger.error(f"Error extracting flow context: {e}")
            return {"put_call_ratio": 0.5, "unusual_activity_count": 0,
                    "unusual_activity": [], "smart_money_bias": "neutral"}
