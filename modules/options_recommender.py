"""
Options Recommender — Scans real Schwab options chains.
Picks the best contract: exact strike, exact date, delta, volume, OI.
No placeholders. No guessing. Real greeks from real chains.
"""
import logging
from datetime import datetime, timedelta

import config

logger = logging.getLogger("options_rec")


class OptionsRecommender:
    def __init__(self, schwab_api):
        self.schwab = schwab_api

    async def recommend(self, symbol: str, direction: str, last_price: float, score: float) -> list[dict]:
        """
        Given a symbol + direction (bullish/bearish) + price + score,
        find the best options contracts.

        Returns list of recommendations:
        [
            {
                "symbol": "AMC",
                "contract": "AMC 240621C00005500",
                "direction": "CALL",
                "strike": 5.50,
                "expiration": "Jun 21, 2025",
                "dte": 14,
                "delta": 0.45,
                "iv": 0.85,
                "bid": 0.35,
                "ask": 0.40,
                "volume": 1200,
                "open_interest": 8500,
                "score": 82.5,
                "confidence": "HIGH",
            }
        ]
        """
        if not direction or direction == "neutral":
            return []

        contract_type = "CALL" if direction == "bullish" else "PUT"

        try:
            chain = await self.schwab.get_options_chain(
                symbol,
                dte_min=config.PREFERRED_DTE_MIN,
                dte_max=config.PREFERRED_DTE_MAX,
            )
        except Exception as e:
            logger.warning(f"Chain fetch failed for {symbol}: {e}")
            return []

        if not chain:
            return []

        # Extract the right side of the chain
        map_key = "callExpDateMap" if contract_type == "CALL" else "putExpDateMap"
        exp_map = chain.get(map_key, {})

        if not exp_map:
            return []

        candidates = []
        for exp_date_str, strikes in exp_map.items():
            # exp_date_str format: "2025-06-20:14"
            exp_date_clean = exp_date_str.split(":")[0]
            try:
                exp_dt = datetime.strptime(exp_date_clean, "%Y-%m-%d")
            except ValueError:
                continue

            dte = (exp_dt - datetime.now()).days
            if dte < config.PREFERRED_DTE_MIN or dte > config.PREFERRED_DTE_MAX:
                continue

            for strike_str, contracts in strikes.items():
                if not contracts:
                    continue
                c = contracts[0] if isinstance(contracts, list) else contracts

                delta = abs(c.get("delta", 0) or 0)
                iv = c.get("volatility", 0) or 0
                bid = c.get("bid", 0) or 0
                ask = c.get("ask", 0) or 0
                vol = c.get("totalVolume", 0) or 0
                oi = c.get("openInterest", 0) or 0
                strike = c.get("strikePrice", 0) or float(strike_str)
                contract_sym = c.get("symbol", f"{symbol} {strike_str}{contract_type[0]}")

                # Skip illiquid contracts
                if bid <= 0 or ask <= 0:
                    continue
                if oi < 50:
                    continue

                # Delta filter
                if delta < config.PREFERRED_DELTA_MIN or delta > config.PREFERRED_DELTA_MAX:
                    continue

                # Spread check — skip if spread is more than 30% of mid
                mid = (bid + ask) / 2.0
                spread_pct = (ask - bid) / mid * 100 if mid > 0 else 999
                if spread_pct > 30:
                    continue

                # Score this contract
                contract_score = self._score_contract(
                    delta=delta, iv=iv, vol=vol, oi=oi,
                    spread_pct=spread_pct, dte=dte, flow_score=score,
                )

                candidates.append({
                    "symbol": symbol,
                    "contract": contract_sym,
                    "direction": contract_type,
                    "strike": strike,
                    "expiration": exp_dt.strftime("%b %d, %Y"),
                    "exp_date": exp_date_clean,
                    "dte": dte,
                    "delta": round(delta, 3),
                    "iv": round(iv / 100, 2) if iv > 1 else round(iv, 2),
                    "bid": bid,
                    "ask": ask,
                    "mid": round(mid, 2),
                    "volume": vol,
                    "open_interest": oi,
                    "spread_pct": round(spread_pct, 1),
                    "score": round(contract_score, 1),
                    "confidence": self._confidence_label(contract_score),
                })

        # Sort by score descending, return top N
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top = candidates[:config.MAX_OPTIONS_RESULTS]

        if top:
            logger.info(f"{symbol} → {len(top)} option recs: {[c['contract'] for c in top]}")

        return top

    def _score_contract(self, delta: float, iv: float, vol: int, oi: int,
                        spread_pct: float, dte: int, flow_score: float) -> float:
        """
        Score a single contract 0-100.
        Weights: delta fit (25%), liquidity (25%), flow alignment (30%), value (20%)
        """
        # Delta fit — 0.45 is ideal for directional, penalize extremes
        ideal_delta = 0.45
        delta_score = max(0, 100 - abs(delta - ideal_delta) * 300)

        # Liquidity — volume + OI + tight spread
        liq_score = 0
        if vol > 0:
            liq_score += min(40, vol / 50)  # 2000 vol = max 40
        if oi > 0:
            liq_score += min(40, oi / 250)  # 10k OI = max 40
        liq_score += max(0, 20 - spread_pct)  # Tight spread bonus
        liq_score = min(100, liq_score)

        # Flow alignment — how strong is the directional signal
        flow_align = min(100, flow_score * 1.2)

        # Value — prefer moderate IV, not too cheap not too expensive
        # Lower IV = cheaper premium = better value for directional
        iv_norm = iv / 100 if iv > 1 else iv
        value_score = max(0, 100 - iv_norm * 80)  # Penalize very high IV

        # DTE sweet spot: 14-21 days ideal
        dte_ideal = 17
        dte_penalty = abs(dte - dte_ideal) * 2
        dte_score = max(0, 100 - dte_penalty)

        total = (
            delta_score * 0.20 +
            liq_score * 0.25 +
            flow_align * 0.30 +
            value_score * 0.10 +
            dte_score * 0.15
        )
        return min(100, total)

    def _confidence_label(self, score: float) -> str:
        if score >= 80:
            return "HIGH"
        elif score >= 60:
            return "MEDIUM"
        elif score >= 40:
            return "LOW"
        return "SPECULATIVE"
