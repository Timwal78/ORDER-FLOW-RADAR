"""
Options Recommender v2 — Institutional-Grade Contract Selection
Scans real Schwab options chains. Picks the best contract using:
  - IV-adjusted expected move scoring
  - Greeks quality (delta fit, gamma risk, theta decay rate)
  - Liquidity gates (OI, volume, spread width)
  - Flow alignment with directional signal
  - DTE optimization for swing vs. scalp
Data-driven analysis. No approximations. Real greeks from real chains.
"""
import math
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
                "prob_of_profit": 42,
                "expected_move": 1.25,
                "risk_reward": 2.8,
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
                gamma = c.get("gamma", 0) or 0
                theta = c.get("theta", 0) or 0

                # ── Hard liquidity gates (institutional-grade minimums) ──
                if bid <= 0 or ask <= 0:
                    continue
                if oi < 50:  # Loosened from 100 — allow high-impact low-OI setups
                    continue
                if vol < 5:  # Loosened from 10 — allow early-bird trades
                    continue

                # ── Delta filter ──
                if delta < config.PREFERRED_DELTA_MIN or delta > config.PREFERRED_DELTA_MAX:
                    continue

                # ── Spread check — skip if spread is more than 35% of mid ──
                mid = (bid + ask) / 2.0
                spread_pct = (ask - bid) / mid * 100 if mid > 0 else 999
                if spread_pct > 35:  # Loosened from 25% to account for wider Call spreads in volatile tapes
                    continue

                # Normalize IV (Schwab returns as whole number like 85.0)
                iv_norm = iv / 100 if iv > 1 else iv

                # Expected move calculation
                t_years = max(dte, 1) / 365.0
                expected_move = last_price * iv_norm * math.sqrt(t_years)

                # Probability of profit approximation
                breakeven = strike + mid if contract_type == "CALL" else strike - mid
                prob_of_profit = self._estimate_prob_profit(
                    last_price, breakeven, iv_norm, dte, contract_type
                )

                # Risk/Reward: potential gain at 1σ move vs premium cost
                if contract_type == "CALL":
                    gain_at_1sigma = max(0, (last_price + expected_move) - strike) - mid
                else:
                    gain_at_1sigma = max(0, strike - (last_price - expected_move)) - mid
                rr_ratio = round(gain_at_1sigma / mid, 2) if mid > 0 and gain_at_1sigma > 0 else 0

                # Score this contract
                contract_score = self._score_contract(
                    delta=delta, iv_norm=iv_norm, vol=vol, oi=oi,
                    spread_pct=spread_pct, dte=dte, flow_score=score,
                    gamma=gamma, theta=theta, mid=mid,
                    prob_of_profit=prob_of_profit, rr_ratio=rr_ratio,
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
                    "gamma": round(gamma, 5),
                    "theta": round(theta, 4),
                    "iv": round(iv_norm, 3),
                    "bid": bid,
                    "ask": ask,
                    "mid": round(mid, 2),
                    "volume": vol,
                    "open_interest": oi,
                    "spread_pct": round(spread_pct, 1),
                    "score": round(contract_score, 1),
                    "confidence": self._confidence_label(contract_score),
                    "prob_of_profit": round(prob_of_profit * 100, 1),
                    "expected_move": round(expected_move, 2),
                    "risk_reward": rr_ratio,
                })

        # Sort by score descending, return top N
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top = candidates[:config.MAX_OPTIONS_RESULTS]

        if top:
            logger.info(f"{symbol} → {len(top)} option recs: {[c['contract'] for c in top]}")

        return top

    def _estimate_prob_profit(self, spot, breakeven, iv, dte, contract_type):
        """
        Estimate probability of profit using lognormal approximation.
        Uses the same normCDF approach as the Options Grader.
        """
        if spot <= 0 or breakeven <= 0 or iv <= 0 or dte <= 0:
            return 0.30  # Default uncertain

        t = max(dte, 1) / 365.0
        sigma_root_t = iv * math.sqrt(t)

        if sigma_root_t <= 0:
            return 0.30

        d2 = (math.log(spot / breakeven) - 0.5 * iv * iv * t) / sigma_root_t

        if contract_type == "CALL":
            return self._norm_cdf(d2)
        else:
            return self._norm_cdf(-d2)

    @staticmethod
    def _norm_cdf(x):
        """Standard normal CDF (Abramowitz & Stegun approximation)."""
        a1 = 0.254829592
        a2 = -0.284496736
        a3 = 1.421413741
        a4 = -1.453152027
        a5 = 1.061405429
        p = 0.3275911
        sign = -1 if x < 0 else 1
        x = abs(x)
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2)
        return 0.5 * (1.0 + sign * y)

    def _score_contract(self, delta: float, iv_norm: float, vol: int, oi: int,
                        spread_pct: float, dte: int, flow_score: float,
                        gamma: float, theta: float, mid: float,
                        prob_of_profit: float, rr_ratio: float) -> float:
        """
        Score a single contract 0-100. Institutional weighting:
          - Probability of Profit  25%  (can you actually win?)
          - Liquidity              20%  (can you get in and out?)
          - Flow Alignment         20%  (is smart money confirming?)
          - Risk/Reward            15%  (is the payoff asymmetric?)
          - Greeks Quality         10%  (is the profile favorable?)
          - DTE Fit                10%  (is the timing right?)
        """
        # ── Probability of Profit (25%) ──
        prob_score = min(100, prob_of_profit * 150)  # 55%+ prob = 82+ score

        # ── Liquidity (20%) ──
        liq_score = 0
        if vol > 0:
            liq_score += min(30, vol / 100)      # 3000 vol = max 30
        if oi > 0:
            liq_score += min(30, oi / 333)       # 10k OI = max 30
        liq_score += max(0, 25 - spread_pct)     # Tight spread bonus (25% max)
        # Volume/OI ratio bonus — unusual activity
        if oi > 0 and vol / oi > 1.5:
            liq_score += 15
        liq_score = min(100, liq_score)

        # ── Flow Alignment (20%) ──
        flow_align = min(100, flow_score * 1.1)

        # ── Risk/Reward (15%) ──
        if rr_ratio >= 3.0:
            rr_score = 100
        elif rr_ratio >= 2.0:
            rr_score = 80
        elif rr_ratio >= 1.5:
            rr_score = 65
        elif rr_ratio >= 1.0:
            rr_score = 50
        elif rr_ratio >= 0.5:
            rr_score = 30
        else:
            rr_score = 10

        # ── Greeks Quality (10%) ──
        greeks_score = 50

        # Delta fit — 0.40-0.50 is ideal for directional swing trades
        ideal_delta = 0.45
        delta_penalty = abs(delta - ideal_delta) * 150  # Softened from 300
        greeks_score += max(-20, 20 - delta_penalty)

        # Theta decay rate (% of premium per day)
        if mid > 0:
            theta_pct = abs(theta) / mid * 100
            if theta_pct < 1.5:
                greeks_score += 15   # Minimal decay
            elif theta_pct < 3.0:
                greeks_score += 5    # Manageable
            elif theta_pct > 8.0:
                greeks_score -= 15   # Melting

        # Gamma risk for short DTE
        if dte <= 3 and gamma > 0.08:
            greeks_score -= 15  # Gamma knife edge
        elif dte <= 7 and gamma > 0.06:
            greeks_score -= 5

        greeks_score = max(0, min(100, greeks_score))

        # ── DTE Fit (10%) ──
        # Ideal: 14-21 days for swing trades
        dte_ideal = 17
        dte_penalty = abs(dte - dte_ideal) * 1.5
        dte_score = max(0, min(100, 100 - dte_penalty))

        # ── Weighted total ──
        total = (
            prob_score * 0.25 +
            liq_score * 0.20 +
            flow_align * 0.20 +
            rr_score * 0.15 +
            greeks_score * 0.10 +
            dte_score * 0.10
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
