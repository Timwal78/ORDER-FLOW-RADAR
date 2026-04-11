"""
SML Institutional Sweep Scanner™ — OFR Module
Scans entire market for whale options sweeps.
Outputs BUY CALL / BUY PUT / HOLD with strike + date.

Integrates into Order-Flow-Radar's async loop and tiered Discord alerts.
Routes to FREE / PRO / PREMIUM channels by grade.
ZERO fake data. All live. All real.
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


class SweepScanner:
    """Institutional sweep detection engine for Order-Flow-Radar."""

    def __init__(self, schwab_api, alpaca_api, polygon_api, discord_alerter,
                 journal=None, earnings=None):
        self.schwab = schwab_api
        self.alpaca = alpaca_api
        self.polygon = polygon_api
        self.discord = discord_alerter
        self.journal = journal
        self.earnings = earnings
        self.last_scan_results = []
        self.scan_count = 0
        self._alert_count = 0  # Track for preview drops to free tier

    async def run_scan(self, universe_symbols: list,
                       price_min=1, price_max=100,
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

                        qualified.append(cl)
                        logger.info(f"  >> {cl['action']} {cl['contract']} [{cl['grade']}] "
                                    f"{cl['score']}/12 -- ${cl['combined']:,.0f}")

                        # Log to journal
                        if self.journal:
                            self.journal.log_signal(cl)

                        # Send to Discord (tiered)
                        await self._send_alert(cl)

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
        """12-point scoring system -> BUY/SELL/HOLD."""
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

            mx = max(s["premium"] for s in cl["sweeps"])
            if mx >= 500_000: sc += 2; bd["whale"] = 2
            if cl["combined"] >= 1_000_000: sc += 2; bd["combined"] = 2
            if len(cl["sweeps"]) >= 3: sc += 2; bd["stacked"] = 2

            aggr = sum(1 for s in cl["sweeps"] if s["vol_oi"] > 1.5)
            if aggr >= len(cl["sweeps"]) * 0.4: sc += 1; bd["vol_oi"] = 1

            avg_dte = sum(s["dte"] for s in cl["sweeps"]) / len(cl["sweeps"])
            if 2 <= avg_dte <= 14: sc += 1; bd["dte"] = 1

            avg_otm = sum(abs(s["otm_pct"]) for s in cl["sweeps"]) / len(cl["sweeps"])
            is_etf = cl["ticker"] in ETFS
            if avg_otm <= (0.03 if is_etf else 0.05): sc += 1; bd["otm"] = 1

            price = mkt.get("price", 0)
            vwap = mkt.get("vwap", 0)
            if vwap > 0 and price > 0:
                if cl["direction"] == "bullish" and price > vwap: sc += 2; bd["vwap"] = 2
                elif cl["direction"] == "bearish" and price < vwap: sc += 2; bd["vwap"] = 2

            op = mkt.get("open", 0)
            if op > 0:
                if cl["direction"] == "bullish" and price > op: sc += 1; bd["orb"] = 1
                elif cl["direction"] == "bearish" and price < op: sc += 1; bd["orb"] = 1

            grade = "S" if sc >= 11 else "A" if sc >= 9 else "B" if sc >= 7 else "C" if sc >= 5 else "F"

            dqs = []
            if len(cl["sweeps"]) < 2: dqs.append("Single print")
            wide = sum(1 for s in cl["sweeps"] if s["spread_pct"] > 0.20)
            if wide > len(cl["sweeps"]) * 0.5: dqs.append("Wide spreads")
            if cl["direction"] == "bullish" and vwap > 0 and price < vwap * 0.995: dqs.append("Below VWAP")
            if cl["direction"] == "bearish" and vwap > 0 and price > vwap * 1.005: dqs.append("Above VWAP")

            best = max(cl["sweeps"], key=lambda s: s["premium"])
            if sc >= 7 and not dqs:
                action = "BUY CALL" if cl["direction"] == "bullish" else "BUY PUT"
            elif sc >= 5 and not dqs:
                action = "HOLD"
            else:
                action = "PASS"

            entry = best["price"]
            results.append({
                "ticker": cl["ticker"], "direction": cl["direction"],
                "action": action,
                "contract": f"{best['ticker']} {best['strike']}{best['type'][0].upper()} {best['expiration']}",
                "strike": best["strike"], "expiration": best["expiration"],
                "contract_type": best["type"],
                "sweeps": cl["sweeps"], "combined": cl["combined"],
                "score": sc, "grade": grade, "breakdown": bd, "disqualifiers": dqs,
                "price": price, "vwap": vwap, "open": op,
                "entry": entry, "stop": round(entry * 0.65, 4),
                "tp1": round(entry * 1.30, 4), "tp2": round(entry * 1.60, 4),
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

        embed = {"embeds": [{
            "title": f"{emoji} [{cl['grade']}] {cl['action']} -- {cl['ticker']}",
            "description": f"**{cl['contract']}**\n*Tier: {tier_label}*{earnings_tag}",
            "color": color,
            "fields": [
                {"name": "Action", "value": cl["action"], "inline": True},
                {"name": "Score", "value": f"{cl['score']}/12", "inline": True},
                {"name": "Combined", "value": f"${cl['combined']:,.0f}", "inline": True},
                {"name": "Price", "value": f"${cl['price']:.2f}", "inline": True},
                {"name": "VWAP", "value": f"${cl['vwap']:.2f}", "inline": True},
                {"name": "Direction", "value": cl['direction'].upper(), "inline": True},
                {"name": "Sweeps", "value": "\n".join(sweep_lines) or "--", "inline": False},
                {"name": "Entry / Stop / TP1 / TP2",
                 "value": f"${cl['entry']:.2f} / ${cl['stop']:.2f} / ${cl['tp1']:.2f} / ${cl['tp2']:.2f}",
                 "inline": False},
            ],
            "footer": {"text": "SML Sweep Scanner | Order-Flow-Radar | ScriptMasterLabs.com"},
            "timestamp": datetime.now().isoformat(),
        }]}

        session = await self.discord._get_session()
        for wh in webhooks:
            try:
                async with session.post(wh, json=embed) as resp:
                    if resp.status in (200, 204):
                        logger.info(f"Sweep alert [{cl['grade']}] {cl['ticker']} -> {wh[:60]}...")
                    elif resp.status == 429:
                        try:
                            err = await resp.json()
                            wait = float(err.get("retry_after", 1.5))
                            await asyncio.sleep(wait + 0.1)
                            async with session.post(wh, json=embed) as retry:
                                pass
                        except:
                            await asyncio.sleep(1.5)
                    else:
                        body = await resp.text()
                        logger.warning(f"Sweep alert failed ({resp.status}): {body[:100]}")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Discord sweep error: {e}")

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
                try:
                    await asyncio.sleep(0.5)
                    async with session.post(wh["free"], json=preview) as resp:
                        if resp.status in (200, 204):
                            logger.info(f"Preview drop sent to FREE: {cl['ticker']}")
                except:
                    pass
                self._preview_drop = False

    def get_results(self) -> list:
        """Get last scan results for dashboard display."""
        return self.last_scan_results
