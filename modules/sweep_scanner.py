"""
SML Institutional Sweep Scanner™ — OFR Module
Scans entire market for whale options sweeps.
Outputs BUY CALL / BUY PUT / HOLD with strike + date.

Integrates into Order-Flow-Radar's async loop and tiered Discord alerts.
Routes to FREE / PRO / PREMIUM channels by grade.
Strictly Real-Time Data. All live. All real.
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("sweep")


def _get_webhooks():
    """Read tiered webhooks from env (lazy, so dotenv is already loaded)."""
    return {
        "free": os.getenv("DISCORD_WEBHOOK_FREE", ""),
        "pro": os.getenv("DISCORD_WEBHOOK_PRO", ""),
        "premium": os.getenv("DISCORD_WEBHOOK_PREMIUM", ""),
        "sweep": os.getenv("DISCORD_WEBHOOK_SWEEP", ""),
    }


ETFS = {
    "SPY","QQQ","IWM","DIA","XLF","XLE","XLK","XLV","XLI","XLP","XLU",
    "XLB","XLC","XLRE","XLY","GLD","SLV","TLT","HYG","EEM","EFA","VXX",
    "UVXY","SQQQ","TQQQ","SPXL","ARKK","SMH","KWEB","FXI","USO","GDX",
    "GDXJ","KRE","XBI","XOP","JETS","BITO","MSOS","SOXL","SOXS","LABU",
}

# Mega-caps that generate too much noise if uncapped.
# They get SCANNED (so we don't miss real whale plays), but
# only MAX_MEGA_CAP_ALERTS fire per scan cycle to avoid flooding Discord.
MEGA_CAPS = {
    'AAPL', 'MSFT', 'GOOG', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA',
    'LLY', 'V', 'MA', 'AVGO', 'HD', 'COST', 'JPM', 'UNH', 'WMT',
    'BAC', 'XOM', 'CVX', 'PG', 'ORCL', 'ABBV', 'CRM', 'ADBE', 'NFLX',
    'BRK.B', 'JNJ', 'MRK', 'PEP', 'KO', 'TMO', 'CSCO', 'ACN',
}
MAX_MEGA_CAP_ALERTS = 2  # Max mega-cap signals per scan cycle


class SweepScanner:
    """Institutional sweep detection engine for Order-Flow-Radar."""

    def __init__(self, schwab_api, alpaca_api, polygon_api, discord_alerter,
                 journal=None, earnings=None, paper=None, xbot=None):
        self.schwab = schwab_api
        self.alpaca = alpaca_api
        self.polygon = polygon_api
        self.discord = discord_alerter
        self.journal = journal
        self.earnings = earnings
        self.paper = paper
        self.xbot = xbot
        self.last_scan_results = []
        self.scan_count = 0
        self._alert_count = 0  # Track for preview drops to free tier

    async def run_scan(self, universe_symbols: list,
                       price_min=2, price_max=500,
                       min_premium=150_000, dte_min=2, dte_max=14,
                       min_score=5):
        """
        Full sweep scan cycle. Called from the main OFR loop.
        Uses existing OFR API clients (async).
        """
        self.scan_count += 1
        logger.info(f"=== SWEEP SCAN #{self.scan_count} | {len(universe_symbols)} universe tickers ===")

        # Refresh earnings calendar if available
        if self.earnings:
            try:
                await self.earnings.refresh_earnings_calendar(universe_symbols[:100])
            except Exception as e:
                logger.debug(f"Earnings refresh: {e}")

        # Filter to price range using Alpaca snapshots
        scan_targets = await self._filter_by_price(universe_symbols, price_min, price_max)
        if not scan_targets:
            logger.warning("No tickers in price range for sweep scan")
            return []

        logger.info(f"Sweep scanning {len(scan_targets)} tickers (${price_min}-${price_max})")

        qualified = []
        mega_cap_count = 0  # Throttle mega-cap alerts to avoid AAPL/TSLA flood
        for i, (symbol, price) in enumerate(scan_targets[:80]):  # Cap at 80 per cycle
            try:
                sweeps = await self._scan_chain(symbol, price, dte_min, dte_max, min_premium)
                if not sweeps:
                    continue

                logger.info(f"  [{i+1}] {symbol} -- {len(sweeps)} sweep candidates")

                # Get market data for scoring
                mkt = await self._get_market_context(symbol, price)

                # Cluster + Score
                clusters = self._cluster_and_score(sweeps, mkt)

                for cl in clusters:
                    if cl["score"] >= min_score and (not cl["disqualifiers"] or cl["score"] >= 9):
                        # Tag earnings if detected
                        if self.earnings:
                            has_er, days_until = self.earnings.has_upcoming_earnings(cl["ticker"])
                            if has_er:
                                cl["earnings_flag"] = True
                                cl["earnings_days"] = days_until
                                logger.info(f"  ** EARNINGS in {days_until}d for {cl['ticker']}!")

                        # Mega-cap throttle: scan all, but limit Discord alerts
                        is_mega = cl["ticker"] in MEGA_CAPS
                        if is_mega and mega_cap_count >= MAX_MEGA_CAP_ALERTS:
                            logger.info(f"  >> THROTTLED mega-cap {cl['ticker']} (already {mega_cap_count} this cycle)")
                            # Still log to journal + paper, just skip Discord
                            if self.journal:
                                self.journal.log_signal(cl)
                            continue
                        if is_mega:
                            mega_cap_count += 1

                        qualified.append(cl)
                        logger.info(f"  >> {cl['action']} {cl['contract']} [{cl['grade']}] "
                                    f"{cl['score']}/12 -- ${cl['combined']:,.0f}")

                        # Log to journal
                        if self.journal:
                            self.journal.log_signal(cl)

                        # Auto-follow in paper portfolio (BUY signals only)
                        if self.paper and cl["action"].startswith("BUY"):
                            try:
                                self.paper.open_position(cl)
                            except Exception as e:
                                logger.debug(f"Paper portfolio: {e}")

                        # Send to Discord (tiered)
                        await self._send_alert(cl)

                        # Queue for X.com delayed posting
                        if self.xbot:
                            self.xbot.queue_signal(cl)

            except Exception as e:
                logger.debug(f"  {symbol} scan error: {e}")
                continue

        self.last_scan_results = qualified
        logger.info(f"=== SWEEP SCAN COMPLETE | {len(qualified)} qualified setups ===")

        # Expire old journal entries
        if self.journal:
            self.journal.expire_old_signals()

        return qualified

    async def _filter_by_price(self, symbols, price_min, price_max):
        """Filter symbols by price range using Alpaca snapshots."""
        targets = []
        try:
            # Use Alpaca REST snapshots (already available in OFR)
            import aiohttp
            headers = {
                "APCA-API-KEY-ID": self.alpaca.api_key,
                "APCA-API-SECRET-KEY": self.alpaca.api_secret,
            }
            session = aiohttp.ClientSession()
            try:
                for i in range(0, len(symbols), 100):
                    batch = symbols[i:i+100]
                    url = "https://data.alpaca.markets/v2/stocks/snapshots"
                    async with session.get(url, headers=headers,
                                           params={"symbols": ",".join(batch), "feed": "iex"},
                                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for sym, snap in data.items():
                                latest = snap.get("latestTrade", {})
                                bar = snap.get("dailyBar", {})
                                price = latest.get("p") or bar.get("c", 0)
                                if price and price_min <= price <= price_max:
                                    targets.append((sym, price))
                    await asyncio.sleep(0.1)
            finally:
                await session.close()
        except Exception as e:
            logger.warning(f"Price filter error: {e}")

        # Sort by price (higher-priced stocks tend to have more options activity)
        targets.sort(key=lambda x: x[1], reverse=True)
        return targets

    async def _scan_chain(self, symbol, price, dte_min, dte_max, min_premium):
        """Scan options chain via Schwab API."""
        sweeps = []
        today = datetime.now().date()
        is_etf = symbol in ETFS

        try:
            chain = await self.schwab.get_options_chain(symbol, dte_min=dte_min, dte_max=dte_max)
            if not chain:
                return []
        except Exception as e:
            logger.debug(f"  {symbol} chain fetch failed: {e}")
            return []

        for side_key, side_label in [("callExpDateMap", "call"), ("putExpDateMap", "put")]:
            exp_map = chain.get(side_key, {})
            for exp_key, strikes in exp_map.items():
                try:
                    exp_str = exp_key.split(":")[0]
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                except:
                    continue

                dte = (exp_date - today).days
                if dte < dte_min or dte > dte_max:
                    continue

                for strike_str, contracts in strikes.items():
                    for contract in contracts:
                        strike = float(strike_str)
                        volume = int(contract.get("totalVolume", 0))
                        oi = int(contract.get("openInterest", 0))
                        last_price = float(contract.get("last", 0))
                        bid = float(contract.get("bid", 0))
                        ask = float(contract.get("ask", 0))
                        delta = float(contract.get("delta", 0))
                        gamma = float(contract.get("gamma", 0))
                        theta = float(contract.get("theta", 0))
                        iv = float(contract.get("volatility", 0)) / 100.0

                        if not volume or not last_price or not strike:
                            continue

                        # OTM distance
                        if price <= 0:
                            continue
                        otm_pct = ((strike - price) / price) if side_label == "call" else ((price - strike) / price)
                        otm_max = 0.03 if is_etf else 0.05
                        if otm_pct < -0.005 or otm_pct > otm_max:
                            continue

                        premium = volume * last_price * 100
                        if premium < min_premium:
                            continue

                        mid = (bid + ask) / 2 if (bid and ask) else last_price
                        spread_pct = (ask - bid) / mid if mid > 0 and bid and ask else 0
                        vol_oi = volume / max(oi, 1)

                        sweeps.append({
                            "ticker": symbol, "strike": strike, "expiration": exp_str,
                            "type": side_label, "premium": premium, "volume": volume,
                            "price": last_price, "bid": bid, "ask": ask,
                            "dte": dte, "otm_pct": otm_pct, "oi": oi,
                            "vol_oi": vol_oi, "spread_pct": spread_pct,
                            "iv": iv, "delta": delta, "gamma": gamma, "theta": theta,
                            "underlying_price": price,
                        })
        return sweeps

    async def _get_market_context(self, symbol, fallback_price):
        """Get VWAP + open/high/low for scoring."""
        try:
            quote = await self.schwab.get_quote(symbol)
            if quote:
                price = float(quote.get("lastPrice", 0) or quote.get("mark", 0) or fallback_price)
                high = float(quote.get("highPrice", 0) or fallback_price)
                low = float(quote.get("lowPrice", 0) or fallback_price)
                open_p = float(quote.get("openPrice", 0) or fallback_price)
                vwap = (high + low + price) / 3  # Approximation
                return {"price": price, "open": open_p, "high": high, "low": low, "vwap": vwap}
        except:
            pass
        return {"price": fallback_price, "open": fallback_price,
                "high": fallback_price, "low": fallback_price, "vwap": fallback_price}

    def _cluster_and_score(self, sweeps, mkt):
        """
        Institutional-grade 12-point scoring system → BUY/SELL/HOLD.
        v2: Graduated V/OI, IV-adjusted stops, expected-move TPs,
            IV crush warnings, spread quality gates.
        """
        import math

        groups = defaultdict(lambda: {"sweeps": [], "combined": 0})

        for s in sweeps:
            direction = "bullish" if s["type"] == "call" else "bearish"
            key = f"{s['ticker']}|{direction}"
            groups[key]["ticker"] = s["ticker"]
            groups[key]["direction"] = direction
            groups[key]["sweeps"].append(s)
            groups[key]["combined"] += s["premium"]

        results = []
        for cl in groups.values():
            sc = 0
            bd = {}

            # ── Whale detection (2pts) ──
            mx = max(s["premium"] for s in cl["sweeps"])
            if mx >= 500_000: sc += 2; bd["whale"] = 2

            # ── Combined cluster premium (2pts) ──
            if cl["combined"] >= 1_000_000: sc += 2; bd["combined"] = 2

            # ── Stacked prints — repeated conviction (2pts) ──
            if len(cl["sweeps"]) >= 3: sc += 2; bd["stacked"] = 2

            # ── Volume/OI ratio — GRADUATED (up to 2pts) ──
            # Truly abnormal V/OI is the hallmark of informed flow
            vol_oi_values = [s["vol_oi"] for s in cl["sweeps"]]
            max_vol_oi = max(vol_oi_values) if vol_oi_values else 0
            avg_vol_oi = sum(vol_oi_values) / len(vol_oi_values) if vol_oi_values else 0
            if max_vol_oi >= 10.0 or avg_vol_oi >= 5.0:
                sc += 2; bd["vol_oi"] = 2   # Extreme — 10x+ single or 5x+ average
            elif max_vol_oi >= 5.0 or avg_vol_oi >= 2.5:
                sc += 1; bd["vol_oi"] = 1   # Strong — 5x+ single or 2.5x+ average
            # Below 5x max and 2.5x avg = no points (not abnormal enough)

            # ── DTE sweet spot (1pt) ──
            avg_dte = sum(s["dte"] for s in cl["sweeps"]) / len(cl["sweeps"])
            if 2 <= avg_dte <= 14: sc += 1; bd["dte"] = 1

            # ── OTM proximity (1pt) ──
            avg_otm = sum(abs(s["otm_pct"]) for s in cl["sweeps"]) / len(cl["sweeps"])
            is_etf = cl["ticker"] in ETFS
            if avg_otm <= (0.03 if is_etf else 0.05): sc += 1; bd["otm"] = 1

            # ── VWAP confirmation (1pt — reduced from 2, rebalanced to V/OI) ──
            price = mkt.get("price", 0)
            vwap = mkt.get("vwap", 0)
            if vwap > 0 and price > 0:
                if cl["direction"] == "bullish" and price > vwap: sc += 1; bd["vwap"] = 1
                elif cl["direction"] == "bearish" and price < vwap: sc += 1; bd["vwap"] = 1

            # ── Opening Range Breakout confirmation (1pt) ──
            op = mkt.get("open", 0)
            if op > 0:
                if cl["direction"] == "bullish" and price > op: sc += 1; bd["orb"] = 1
                elif cl["direction"] == "bearish" and price < op: sc += 1; bd["orb"] = 1

            # ── Counter-Trend Premium Boost (1pt) ──
            # Whales buying against the tape is contrarian conviction — reward, don't punish
            if vwap > 0 and price > 0:
                if cl["direction"] == "bullish" and price < vwap and cl["combined"] >= 500_000:
                    sc += 1; bd["contrarian"] = 1
                elif cl["direction"] == "bearish" and price > vwap and cl["combined"] >= 500_000:
                    sc += 1; bd["contrarian"] = 1

            # ── Grade assignment ──
            grade = "S" if sc >= 11 else "A" if sc >= 9 else "B" if sc >= 7 else "C" if sc >= 5 else "F"

            # ── Disqualifiers ──
            dqs = []
            if len(cl["sweeps"]) < 2: dqs.append("Single print")
            wide = sum(1 for s in cl["sweeps"] if s["spread_pct"] > 0.20)
            if wide > len(cl["sweeps"]) * 0.5: dqs.append("Wide spreads")
            # VWAP against direction = soft penalty (-1pt), NOT a hard disqualifier.
            # Whale contra-VWAP sweeps are contrarian plays that should still fire.
            if cl["direction"] == "bullish" and vwap > 0 and price < vwap * 0.995:
                sc -= 1; bd["vwap_against"] = -1
            if cl["direction"] == "bearish" and vwap > 0 and price > vwap * 1.005:
                sc -= 1; bd["vwap_against"] = -1

            # IV crush warning (not a disqualifier, but flagged)
            avg_iv = sum(s.get("iv", 0) for s in cl["sweeps"]) / len(cl["sweeps"])
            iv_crush_warning = avg_iv > 0.80

            # ── Action decision ──
            best = max(cl["sweeps"], key=lambda s: s["premium"])
            if sc >= 7 and not dqs:
                action = "BUY CALL" if cl["direction"] == "bullish" else "BUY PUT"
            elif sc >= 4 and not dqs:
                action = "HOLD"
            else:
                action = "PASS"

            # ═══════════════════════════════════════════════════════════════
            # ENTRY / STOP / TP — IV-adjusted, DTE-aware
            # No more flat percentages. Levels based on the underlying's
            # expected move and the option's delta sensitivity.
            # ═══════════════════════════════════════════════════════════════
            entry = best["price"]
            underlying_price = best.get("underlying_price", price) or price
            iv = best.get("iv", 0.30) or 0.30
            dte = best.get("dte", 7) or 7
            delta = abs(best.get("delta", 0.45)) or 0.45

            # Expected move of the UNDERLYING (1-sigma)
            # σ_move = Price × IV × √(DTE/365)
            t_years = max(dte, 1) / 365.0
            sigma_move = underlying_price * iv * math.sqrt(t_years)

            # Option's expected move ≈ delta × underlying_move
            # This gives us a statistically-grounded option price change estimate
            option_1sigma = delta * sigma_move

            # STOP: Based on 0.75σ adverse move (tighter for short DTE)
            # Short DTE options move faster, so stops must be tighter
            dte_tightening = max(0.5, min(1.0, dte / 14.0))  # Scale: 0.5x at 1 DTE → 1x at 14 DTE
            stop_distance = option_1sigma * 0.75 * dte_tightening
            stop = max(round(entry * 0.30, 4), round(entry - stop_distance, 4))  # Floor at 70% loss

            # TP1: 1.0σ favorable move (high-probability target)
            tp1_distance = option_1sigma * 1.0
            tp1 = round(entry + tp1_distance, 4)

            # TP2: 1.5σ favorable move (extended target, trail stop here)
            tp2_distance = option_1sigma * 1.5
            tp2 = round(entry + tp2_distance, 4)

            # Sanity checks — ensure TPs are actually above entry
            if tp1 <= entry: tp1 = round(entry * 1.20, 4)
            if tp2 <= tp1: tp2 = round(tp1 * 1.25, 4)
            if stop >= entry: stop = round(entry * 0.50, 4)

            # Risk/Reward ratio for the signal card
            risk = entry - stop if entry > stop else entry * 0.35
            reward = tp1 - entry if tp1 > entry else entry * 0.20
            rr_ratio = round(reward / risk, 2) if risk > 0 else 0

            results.append({
                "ticker": cl["ticker"], "direction": cl["direction"],
                "action": action,
                "contract": f"{best['ticker']} {best['strike']}{best['type'][0].upper()} {best['expiration']}",
                "strike": best["strike"], "expiration": best["expiration"],
                "contract_type": best["type"],
                "sweeps": cl["sweeps"], "combined": cl["combined"],
                "score": sc, "grade": grade, "breakdown": bd, "disqualifiers": dqs,
                "price": price, "vwap": vwap, "open": op,
                "entry": entry, "stop": stop,
                "tp1": tp1, "tp2": tp2,
                "risk_reward": rr_ratio,
                "expected_move_1sigma": round(sigma_move, 2),
                "iv_crush_warning": iv_crush_warning,
                "avg_vol_oi": round(avg_vol_oi, 1),
                "avg_dte": round(avg_dte), "avg_otm": avg_otm, "max_single": mx,
                "delta": best.get("delta", 0), "gamma": best.get("gamma", 0),
                "theta": best.get("theta", 0), "iv": best.get("iv", 0),
                "signal_type": "sweep",
            })

        return sorted(results, key=lambda x: x["score"], reverse=True)

    def _get_tier_webhooks(self, grade):
        """
        Route alerts to Discord channels by grade (best = most exclusive):
          S grade (11-12) -> PREMIUM ONLY (whale plays, what people pay for)
          A grade (9-10)  -> PRO + PREMIUM (strong setups, drives upgrades)
          B grade (7-8)   -> PRO + PREMIUM (solid setups, paid tiers only)
          C grade (5-6)   -> FREE + PRO + PREMIUM (watchlist teasers only)
          + Every 5th A-grade: preview drop to FREE with upgrade CTA
          + Always send to dedicated SWEEP channel if configured
        """
        wh = _get_webhooks()
        webhooks = []
        self._preview_drop = False  # Flag for preview formatting

        if grade == "S":
            # ELITE EXCLUSIVE
            if wh["premium"]: webhooks.append(wh["premium"])
        elif grade == "A":
            # PRO + ELITE
            if wh["pro"]: webhooks.append(wh["pro"])
            if wh["premium"]: webhooks.append(wh["premium"])
            # Preview drop: every 5th A-grade signal gets a redacted teaser to FREE
            self._alert_count += 1
            if self._alert_count % 5 == 0 and wh["free"]:
                self._preview_drop = True
        elif grade == "B":
            # PRO + ELITE only — not free
            if wh["pro"]: webhooks.append(wh["pro"])
            if wh["premium"]: webhooks.append(wh["premium"])
        else:
            # C grade — free tier gets these as engagement teasers
            if wh["free"]: webhooks.append(wh["free"])
            if wh["pro"]: webhooks.append(wh["pro"])
            if wh["premium"]: webhooks.append(wh["premium"])

        # Always the dedicated sweep channel
        if wh["sweep"] and wh["sweep"] not in webhooks:
            webhooks.append(wh["sweep"])

        # Fallback to OFR's main webhook
        if not webhooks and self.discord and self.discord.webhook_url:
            webhooks.append(self.discord.webhook_url)

        return webhooks

    async def _send_alert(self, cl):
        """Send sweep alert to tiered Discord channels based on grade."""
        webhooks = self._get_tier_webhooks(cl["grade"])
        if not webhooks:
            return

        color = {"BUY CALL": 0x00FF6A, "BUY PUT": 0xFF2D7B, "HOLD": 0xFFD700}.get(cl["action"], 0x808080)
        emoji = {"S": "\U0001f48e", "A": "\U0001f525", "B": "\u2705", "C": "\u26a0\ufe0f"}.get(cl["grade"], "")

        # Tier badge for the embed
        tier_label = {"S": "ELITE EXCLUSIVE", "A": "PRO + ELITE",
                      "B": "PRO + ELITE", "C": "ALL TIERS"}.get(cl["grade"], "")

        # Earnings tag
        earnings_tag = ""
        if cl.get("earnings_flag"):
            earnings_tag = f"\n**EARNINGS in {cl['earnings_days']}d**"

        sweep_lines = []
        for s in cl["sweeps"][:5]:
            greek = ""
            if s.get("delta"):
                greek = f" | D{s['delta']:.2f} G{s['gamma']:.4f} T{s['theta']:.2f}"
            sweep_lines.append(
                f"* {s['type'].upper()} ${s['strike']} {s['expiration']} | "
                f"${s['premium']:,.0f} | {s['volume']}v OI:{s['oi']} | "
                f"V/OI:{s['vol_oi']:.1f} | {s['dte']}d | {abs(s['otm_pct'])*100:.1f}%OTM{greek}"
            )

        # IV crush warning tag
        iv_tag = ""
        if cl.get("iv_crush_warning"):
            iv_tag = "\n⚠️ **IV CRUSH RISK** — IV > 80%"

        # Entry line with R:R
        entry_line = (
            f"${cl['entry']:.2f} / ${cl['stop']:.2f} / "
            f"${cl['tp1']:.2f} / ${cl['tp2']:.2f}"
        )
        if cl.get("risk_reward"):
            entry_line += f"  (R:R {cl['risk_reward']})"

        embed = {"embeds": [{
            "title": f"{emoji} [{cl['grade']}] {cl['action']} -- {cl['ticker']}",
            "description": f"**{cl['contract']}**\n*Tier: {tier_label}*{earnings_tag}{iv_tag}",
            "color": color,
            "fields": [
                {"name": "Action", "value": cl["action"], "inline": True},
                {"name": "Score", "value": f"{cl['score']}/12", "inline": True},
                {"name": "Combined", "value": f"${cl['combined']:,.0f}", "inline": True},
                {"name": "Price", "value": f"${cl['price']:.2f}", "inline": True},
                {"name": "VWAP", "value": f"${cl['vwap']:.2f}", "inline": True},
                {"name": "Direction", "value": cl['direction'].upper(), "inline": True},
                {"name": "Exp. Move (1σ)", "value": f"${cl.get('expected_move_1sigma', 0):.2f}", "inline": True},
                {"name": "Avg V/OI", "value": f"{cl.get('avg_vol_oi', 0):.1f}x", "inline": True},
                {"name": "R:R", "value": f"{cl.get('risk_reward', 0):.1f}:1", "inline": True},
                {"name": "Sweeps", "value": "\n".join(sweep_lines) or "--", "inline": False},
                {"name": "Entry / Stop / TP1 / TP2",
                 "value": entry_line, "inline": False},
            ],
            "footer": {"text": "SML Sweep Scanner v2 | Order-Flow-Radar | ScriptMasterLabs.com"},
            "timestamp": datetime.now().isoformat(),
        }]}

        for wh in webhooks:
            tier_name = "SWEEP"
            if wh == _get_webhooks().get("free"): tier_name = "FREE"
            elif wh == _get_webhooks().get("pro"): tier_name = "PRO"
            elif wh == _get_webhooks().get("premium"): tier_name = "PREMIUM"
            
            ok = await self.discord._post_webhook(wh, embed, f"SWEEP-{tier_name}")
            if ok:
                logger.info(f"Sweep alert [{cl['grade']}] {cl['ticker']} → {tier_name}")
            else:
                logger.error(f"FAILED sweep alert [{cl['grade']}] {cl['ticker']} → {tier_name}")
            await asyncio.sleep(0.4)

        # PREVIEW DROP: Send redacted teaser to FREE tier
        if getattr(self, '_preview_drop', False):
            wh = _get_webhooks()
            if wh["free"]:
                preview = {"embeds": [{
                    "title": f"{emoji} [{cl['grade']}] SIGNAL DETECTED -- {cl['ticker']}",
                    "description": (
                        f"**An [{cl['grade']}]-grade {cl['action']} signal was just fired.**\n"
                        f"Combined premium: ${cl['combined']:,.0f}\n\n"
                        f"Upgrade to **PRO** or **ELITE** to see:\n"
                        f"- Exact strike + expiration\n"
                        f"- Entry / Stop / TP levels\n"
                        f"- Full Greeks (Delta, Gamma, Theta)\n"
                        f"- All sweep details\n\n"
                        f"**ScriptMasterLabs.com**"
                    ),
                    "color": 0x9B59B6,
                    "footer": {"text": "Upgrade to PRO/ELITE | ScriptMasterLabs.com"},
                    "timestamp": datetime.now().isoformat(),
                }]}
                await asyncio.sleep(0.5)
                ok = await self.discord._post_webhook(wh["free"], preview, "SWEEP-FREE-PREVIEW")
                if ok:
                    logger.info(f"Preview drop sent to FREE: {cl['ticker']}")
                self._preview_drop = False

    def get_results(self) -> list:
        """Get last scan results for dashboard display."""
        return self.last_scan_results
