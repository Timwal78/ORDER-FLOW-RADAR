"""
Options Recommendation Engine for Order Flow Radar.
Takes a trade card and recommends specific options contracts to trade.
Uses real Schwab API data only - no mock contracts.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import aiohttp

import config

logger = logging.getLogger(__name__)


class OptionsRecommender:
    """Recommends specific options contracts for trade setups."""

    def __init__(self, schwab_handler=None):
        """
        Initialize the recommender.

        Args:
            schwab_handler: Instance of SchwabOptionsHandler with OAuth token access.
                           If None, will attempt to create one or operate in degraded mode.
        """
        self.schwab = schwab_handler
        self.app_key = config.SCHWAB_APP_KEY
        self.app_secret = config.SCHWAB_APP_SECRET
        self.refresh_token = config.SCHWAB_REFRESH_TOKEN
        self.token_url = config.SCHWAB_TOKEN_URL
        self.base_url = config.SCHWAB_BASE

        # Token management (if we need to fetch independently)
        self.access_token = None
        self.token_expiry_time = 0

    async def recommend(self, trade_card: dict) -> Optional[dict]:
        """
        Given a trade card, find the optimal options contracts.

        Args:
            trade_card: Dict with keys: symbol, direction, entry, stop_loss, tp1, tp2,
                       score, timeframe, etc.

        Returns:
            Dict with:
            - primary_pick: best recommended contract
            - alternatives: 2 runner-up contracts
            - options_flow_context: PCR, unusual activity, sentiment
            Or None if recommendation fails or API unavailable.
        """
        try:
            if not trade_card or not trade_card.get("symbol"):
                logger.warning("Invalid trade card passed to options recommender")
                return None

            symbol = trade_card.get("symbol", "").upper()
            direction = trade_card.get("direction", "").lower()
            current_price = trade_card.get("entry", 0)
            tp1 = trade_card.get("tp1", 0)
            timeframe = trade_card.get("timeframe", "multi").lower()

            if not symbol or direction not in ["long", "short"] or current_price <= 0:
                logger.warning(f"Invalid trade card data: {symbol} {direction} {current_price}")
                return None

            # Fetch full options chain from Schwab
            chain_data = await self._fetch_options_chain(symbol)
            if not chain_data:
                logger.warning(f"No options chain data available for {symbol}")
                return None

            # Determine option type and DTE range
            option_type = "CALL" if direction == "long" else "PUT"
            dte_range = self._get_dte_range(timeframe)

            # Parse and filter contracts
            contracts = self._parse_schwab_chain(
                chain_data, option_type, current_price, dte_range
            )

            if not contracts:
                logger.warning(f"No suitable contracts found for {symbol} {option_type}")
                return None

            # Score each contract
            scored_contracts = []
            for contract in contracts:
                score = self._score_contract(contract, trade_card)
                scored_contracts.append({
                    "contract": contract,
                    "score": score
                })

            # Sort by score descending
            scored_contracts.sort(key=lambda x: x["score"], reverse=True)

            # Pick top 3
            if len(scored_contracts) == 0:
                return None

            primary = scored_contracts[0]["contract"]
            alternatives = [
                scored_contracts[i]["contract"]
                for i in range(1, min(3, len(scored_contracts)))
            ]

            # Enrich primary with metrics
            primary_enriched = self._enrich_contract(
                primary, trade_card, scored_contracts[0]["score"]
            )

            # Enrich alternatives
            alternatives_enriched = [
                self._enrich_contract(alt, trade_card, scored_contracts[i + 1]["score"])
                for i, alt in enumerate(alternatives)
            ]

            # Gather options flow context
            flow_context = self._extract_flow_context(chain_data)

            return {
                "primary_pick": primary_enriched,
                "alternatives": alternatives_enriched,
                "options_flow_context": flow_context,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error in options recommender: {e}")
            return None

    def _get_dte_range(self, timeframe: str) -> Tuple[int, int]:
        """Determine DTE range based on trade timeframe."""
        timeframe = timeframe.lower()

        if timeframe in ["scalp", "intraday"]:
            return (1, 7)  # 1-7 DTE for scalps
        elif timeframe == "swing":
            return (14, 45)  # 14-45 DTE for swing trades
        else:
            return (21, 60)  # 21-60 DTE for multi-day/default

    async def _fetch_options_chain(self, symbol: str) -> Optional[Dict]:
        """
        Fetch options chain from Schwab API.
        Uses schwab_handler if available, otherwise tries to get token independently.
        """
        try:
            # Try to use schwab handler if available
            if self.schwab and self.schwab.access_token:
                return self.schwab.options_chains.get(symbol, None)

            # Otherwise, fetch independently
            await self._refresh_token_if_needed()
            if not self.access_token:
                logger.warning("No Schwab access token available")
                return None

            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.access_token}"}
                url = f"{self.base_url}/chains"
                params = {
                    "symbol": symbol,
                    "contractType": "ALL",
                    "strikeCount": 20,
                    "includeUnderlyingQuote": "true",
                    "strategy": "SINGLE"
                }

                async with session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"Schwab chain fetch failed: {resp.status}")
                        return None

        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")
            return None

    async def _refresh_token_if_needed(self) -> None:
        """Refresh OAuth2 token if expired."""
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

                data = {
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.token_url,
                        headers=headers,
                        data=data,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            self.access_token = result.get("access_token")
                            expires_in = result.get("expires_in", 1800)
                            self.token_expiry_time = time.time() + expires_in - 60
                            logger.debug("Options recommender token refreshed")
                        else:
                            logger.error(f"Failed to refresh token: {resp.status}")

            except Exception as e:
                logger.error(f"Error refreshing token: {e}")

    def _parse_schwab_chain(
        self,
        chain_data: dict,
        option_type: str,
        current_price: float,
        dte_range: Tuple[int, int],
    ) -> List[Dict]:
        """
        Parse Schwab chain response and filter for suitable contracts.

        Schwab format:
        {
          "callExpDateMap": {
            "2026-04-18:9": {  # expiry:dte
              "140.0": [
                {
                  "bid": 3.40,
                  "ask": 3.55,
                  "last": 3.50,
                  "totalVolume": 12500,
                  "openInterest": 8200,
                  "impliedVolatility": 0.42,
                  "delta": 0.45,
                  "gamma": 0.03,
                  "theta": -0.15,
                  "vega": 0.08,
                  ...
                }
              ]
            }
          },
          "putExpDateMap": {...}
        }
        """
        try:
            contracts = []

            # Select the right map (call or put)
            exp_map_key = "callExpDateMap" if option_type == "CALL" else "putExpDateMap"
            exp_map = chain_data.get(exp_map_key, {})

            if not exp_map:
                return []

            min_dte, max_dte = dte_range

            for expiry_str, strike_map in exp_map.items():
                # Parse expiry: format is "2026-04-18:9"
                try:
                    expiry_date = expiry_str.split(":")[0]
                    dte = int(expiry_str.split(":")[1])
                except (ValueError, IndexError):
                    continue

                # Filter DTE
                if dte < min_dte or dte > max_dte:
                    continue

                # Process strikes
                for strike_str, contract_list in strike_map.items():
                    try:
                        strike = float(strike_str)
                    except ValueError:
                        continue

                    # Filter strike range:
                    # For calls: ATM to slightly OTM (0-5% above current price)
                    # For puts: ATM to slightly OTM (0-5% below current price)
                    if option_type == "CALL":
                        if strike < current_price or strike > current_price * 1.05:
                            continue
                    else:  # PUT
                        if strike > current_price or strike < current_price * 0.95:
                            continue

                    # Add all contracts at this strike/expiry
                    if contract_list and len(contract_list) > 0:
                        contract = contract_list[0]  # Take first contract

                        # Validate minimum data
                        bid = contract.get("bid", 0)
                        ask = contract.get("ask", 0)
                        if bid <= 0 or ask <= 0:
                            continue

                        # Build enriched contract dict
                        enriched = {
                            "strike": strike,
                            "expiry": expiry_date,
                            "dte": dte,
                            "type": option_type,
                            "bid": bid,
                            "ask": ask,
                            "mid": (bid + ask) / 2,
                            "last": contract.get("last", (bid + ask) / 2),
                            "volume": contract.get("totalVolume", 0),
                            "open_interest": contract.get("openInterest", 0),
                            "implied_volatility": contract.get(
                                "impliedVolatility", 0
                            ),
                            "delta": contract.get("delta", 0),
                            "gamma": contract.get("gamma", 0),
                            "theta": contract.get("theta", 0),
                            "vega": contract.get("vega", 0),
                        }

                        contracts.append(enriched)

            return contracts

        except Exception as e:
            logger.error(f"Error parsing Schwab chain: {e}")
            return []

    def _score_contract(self, contract: dict, trade_card: dict) -> float:
        """Score an individual options contract for the given setup."""
        score = 0.0

        try:
            # Volume/OI ratio (higher = more active)
            vol = float(contract.get("volume", 0))
            oi = float(contract.get("open_interest", 1))
            vol_oi = vol / max(oi, 1)

            if vol_oi > 1.0:
                score += 2.0  # High activity
            elif vol_oi > 0.5:
                score += 1.0  # Decent activity
            elif vol_oi < 0.1:
                score -= 1.0  # Dead contract

            # Bid/ask spread tightness (tighter = more liquid)
            bid = float(contract.get("bid", 0))
            ask = float(contract.get("ask", 0))
            mid = (bid + ask) / 2

            if mid > 0:
                spread_pct = (ask - bid) / mid
                if spread_pct < 0.05:
                    score += 2.0  # Very tight spread
                elif spread_pct < 0.10:
                    score += 1.0  # Decent spread
                elif spread_pct > 0.20:
                    score -= 1.0  # Wide spread, avoid

            # Delta sweet spot (0.30-0.60 for directional plays)
            delta = abs(float(contract.get("delta", 0)))
            if 0.35 <= delta <= 0.55:
                score += 2.0  # Perfect delta
            elif 0.30 <= delta <= 0.60:
                score += 1.0  # Good delta
            elif delta < 0.20 or delta > 0.80:
                score -= 1.0  # Too far ITM/OTM

            # Premium affordability (not too cheap = likely worthless, not too expensive)
            # Prefer contracts with mid-price between 0.50 and 20.00
            if 0.50 <= mid <= 20.0:
                score += 1.0

            # DTE alignment with timeframe
            dte = int(contract.get("dte", 0))
            timeframe = trade_card.get("timeframe", "multi").lower()

            if timeframe in ["scalp", "intraday"]:
                if 1 <= dte <= 7:
                    score += 1.5
            elif timeframe == "swing":
                if 14 <= dte <= 45:
                    score += 1.5
            else:  # multi or default
                if 21 <= dte <= 60:
                    score += 1.0

            # Implied volatility consideration (prefer elevated IV for selling, low for buying)
            # For simplicity, moderate IV is preferred
            iv = float(contract.get("implied_volatility", 0))
            if 0.20 <= iv <= 0.80:
                score += 0.5

        except Exception as e:
            logger.error(f"Error scoring contract: {e}")

        return score

    def _enrich_contract(
        self, contract: dict, trade_card: dict, contract_score: float
    ) -> dict:
        """
        Enrich a contract with calculated metrics: max risk, potential return, break-even.
        """
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

            # Max risk per contract (premium paid)
            max_risk_per_contract = ask * 100  # * 100 because options are per 100 shares

            # Potential return at TP1 (using delta as proxy for price movement)
            # Delta approximately equals % move in option for 1% move in stock
            if direction == "long":
                stock_move = tp1 - entry
            else:  # short
                stock_move = entry - tp1

            # Estimate option price move = delta * stock move
            estimated_option_return = abs(delta * stock_move) * 100

            # Risk/reward ratio
            if estimated_option_return > 0:
                risk_reward = estimated_option_return / max_risk_per_contract
            else:
                risk_reward = 0

            # Break-even price
            if option_type == "CALL":
                breakeven = strike + ask
            else:  # PUT
                breakeven = strike - ask

            # Format contract name
            expiry = contract.get("expiry", "")
            expiry_formatted = expiry[-5:]  # "04/18" from "2026-04-18"
            contract_name = f"{trade_card.get('symbol', '')} {expiry_formatted} ${strike:.0f} {option_type}"

            return {
                "contract": contract_name,
                "strike": strike,
                "expiry": expiry,
                "type": option_type,
                "dte": int(contract.get("dte", 0)),
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": float(contract.get("last", mid)),
                "volume": int(contract.get("volume", 0)),
                "open_interest": int(contract.get("open_interest", 0)),
                "implied_volatility": float(contract.get("implied_volatility", 0)),
                "delta": delta,
                "gamma": float(contract.get("gamma", 0)),
                "theta": float(contract.get("theta", 0)),
                "vega": float(contract.get("vega", 0)),
                "score": round(contract_score, 1),
                "max_risk_per_contract": round(max_risk_per_contract, 2),
                "estimated_return_tp1": round(estimated_option_return, 2),
                "risk_reward": f"{risk_reward:.1f}:1" if risk_reward > 0 else "N/A",
                "breakeven": round(breakeven, 2),
                "reasoning": self._generate_reasoning(contract, contract_score),
            }

        except Exception as e:
            logger.error(f"Error enriching contract: {e}")
            return contract

    def _generate_reasoning(self, contract: dict, score: float) -> str:
        """Generate human-readable reasoning for contract selection."""
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
        """Extract options flow context: PCR, unusual activity, sentiment."""
        try:
            total_call_vol = 0
            total_put_vol = 0
            unusual = []

            # Count volumes
            for contract_list in [
                chain_data.get("callExpDateMap", {}),
                chain_data.get("putExpDateMap", {}),
            ]:
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

                            # Detect unusual volume (> 3x open interest)
                            if open_interest > 0 and volume > 3 * open_interest:
                                unusual.append(
                                    {
                                        "strike": strike,
                                        "expiry": expiry,
                                        "type": "PUT" if is_put else "CALL",
                                        "volume": volume,
                                        "open_interest": open_interest,
                                        "volume_oi_ratio": round(
                                            volume / open_interest, 2
                                        ),
                                    }
                                )

            total_vol = total_put_vol + total_call_vol
            if total_vol > 0:
                pcr = total_put_vol / total_vol
            else:
                pcr = 0.5  # neutral default

            # Determine sentiment
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
                "unusual_activity": unusual[:5],  # Top 5 unusual
                "smart_money_bias": sentiment,
            }

        except Exception as e:
            logger.error(f"Error extracting flow context: {e}")
            return {
                "put_call_ratio": 0.5,
                "unusual_activity_count": 0,
                "unusual_activity": [],
                "smart_money_bias": "neutral",
            }
