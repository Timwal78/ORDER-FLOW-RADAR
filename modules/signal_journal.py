"""
SML Signal Journal & Win Rate Tracker
Logs every signal, tracks P&L, generates end-of-day report cards.
Integrates with sweep scanner for performance tracking.
"""
import os
import json
import csv
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("journal")

JOURNAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "signal_data")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "sweep_journal.json")
DAILY_DIR = os.path.join(JOURNAL_DIR, "daily")


def _ensure_dirs():
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    os.makedirs(DAILY_DIR, exist_ok=True)


class SignalJournal:
    """Tracks every sweep signal, logs entry prices, checks exits, computes win rates."""

    def __init__(self):
        _ensure_dirs()
        self.signals = self._load()

    def _load(self):
        if os.path.exists(JOURNAL_FILE):
            try:
                with open(JOURNAL_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return []

    def _save(self):
        try:
            with open(JOURNAL_FILE, "w") as f:
                json.dump(self.signals, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Journal save error: {e}")

    def log_signal(self, cl: dict):
        """Log a new sweep signal with timestamp and entry data."""
        entry = {
            "id": f"{cl['ticker']}_{cl['strike']}_{cl['expiration']}_{datetime.now().strftime('%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "ticker": cl["ticker"],
            "action": cl["action"],
            "direction": cl["direction"],
            "contract": cl["contract"],
            "strike": cl["strike"],
            "expiration": cl["expiration"],
            "contract_type": cl["contract_type"],
            "grade": cl["grade"],
            "score": cl["score"],
            "entry_price": cl["entry"],
            "stop_price": cl["stop"],
            "tp1": cl["tp1"],
            "tp2": cl["tp2"],
            "combined_premium": cl["combined"],
            "underlying_price": cl["price"],
            "vwap": cl["vwap"],
            "delta": cl.get("delta", 0),
            "iv": cl.get("iv", 0),
            # Tracking fields — filled later
            "current_price": None,
            "exit_price": None,
            "exit_time": None,
            "pnl_pct": None,
            "result": None,  # "WIN", "LOSS", "OPEN", "EXPIRED"
            "hit_tp1": False,
            "hit_tp2": False,
            "hit_stop": False,
        }
        self.signals.append(entry)
        self._save()
        logger.info(f"Journal: logged {cl['action']} {cl['contract']} [{cl['grade']}]")
        return entry

    async def update_prices(self, schwab_api):
        """Update current prices for all open signals using Schwab quotes."""
        open_signals = [s for s in self.signals if s["result"] in (None, "OPEN")]
        if not open_signals:
            return

        # Group by ticker for batch quotes
        tickers = list(set(s["ticker"] for s in open_signals))
        try:
            quotes = await schwab_api.get_quotes_batch(tickers)
        except:
            return

        updated = 0
        for sig in open_signals:
            quote = quotes.get(sig["ticker"], {})
            price = float(quote.get("lastPrice", 0) or quote.get("mark", 0) or 0)
            if not price:
                continue

            sig["current_price"] = price
            sig["result"] = "OPEN"

            entry = sig["entry_price"]
            if entry and entry > 0:
                pnl = ((price - entry) / entry) * 100
                # Flip for puts
                if sig["direction"] == "bearish":
                    underlying_now = float(quote.get("lastPrice", 0) or sig["underlying_price"])
                    # Rough approximation — option value increases when underlying drops for puts
                    pass

                sig["pnl_pct"] = round(pnl, 2)

                # Check targets
                if price >= sig["tp1"]:
                    sig["hit_tp1"] = True
                if price >= sig["tp2"]:
                    sig["hit_tp2"] = True
                    sig["result"] = "WIN"
                    sig["exit_price"] = price
                    sig["exit_time"] = datetime.now().isoformat()
                if price <= sig["stop_price"]:
                    sig["hit_stop"] = True
                    sig["result"] = "LOSS"
                    sig["exit_price"] = price
                    sig["exit_time"] = datetime.now().isoformat()

                updated += 1

        if updated:
            self._save()
            logger.info(f"Journal: updated {updated} open signals")

    def expire_old_signals(self):
        """Mark signals past their expiration as expired."""
        today = datetime.now().date()
        for sig in self.signals:
            if sig["result"] in (None, "OPEN"):
                try:
                    exp = datetime.strptime(sig["expiration"], "%Y-%m-%d").date()
                    if exp < today:
                        sig["result"] = "EXPIRED"
                        sig["exit_time"] = sig["expiration"]
                except:
                    pass
        self._save()

    def get_stats(self, days=30):
        """Calculate win rate and performance stats."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        recent = [s for s in self.signals if s["timestamp"] >= cutoff]

        total = len(recent)
        wins = sum(1 for s in recent if s["result"] == "WIN")
        losses = sum(1 for s in recent if s["result"] == "LOSS")
        open_count = sum(1 for s in recent if s["result"] in (None, "OPEN"))
        expired = sum(1 for s in recent if s["result"] == "EXPIRED")

        closed = wins + losses
        win_rate = (wins / closed * 100) if closed > 0 else 0

        # Stats by grade
        grade_stats = {}
        for grade in ["S", "A", "B", "C"]:
            g_signals = [s for s in recent if s["grade"] == grade]
            g_wins = sum(1 for s in g_signals if s["result"] == "WIN")
            g_closed = sum(1 for s in g_signals if s["result"] in ("WIN", "LOSS"))
            grade_stats[grade] = {
                "total": len(g_signals),
                "wins": g_wins,
                "closed": g_closed,
                "win_rate": (g_wins / g_closed * 100) if g_closed > 0 else 0,
            }

        # Average P&L
        pnls = [s["pnl_pct"] for s in recent if s["pnl_pct"] is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0

        return {
            "period_days": days,
            "total_signals": total,
            "wins": wins,
            "losses": losses,
            "open": open_count,
            "expired": expired,
            "win_rate": round(win_rate, 1),
            "avg_pnl_pct": round(avg_pnl, 1),
            "by_grade": grade_stats,
        }

    def get_todays_signals(self):
        """Get all signals from today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return [s for s in self.signals if s["date"] == today]

    async def generate_report_card(self, discord_webhooks: dict):
        """
        Generate end-of-day report card and send to Discord.
        Premium gets full report, Pro gets summary, Free gets teaser.
        """
        today_signals = self.get_todays_signals()
        if not today_signals:
            return

        stats = self.get_stats(days=1)
        overall = self.get_stats(days=30)

        # Build the full report
        signal_lines = []
        for sig in sorted(today_signals, key=lambda x: x["score"], reverse=True):
            result_emoji = {"WIN": "W", "LOSS": "L", "OPEN": "...", "EXPIRED": "X"}.get(sig["result"] or "OPEN", "...")
            pnl_str = f"{sig['pnl_pct']:+.1f}%" if sig["pnl_pct"] is not None else "pending"
            signal_lines.append(
                f"[{result_emoji}] [{sig['grade']}] {sig['action']} {sig['contract']} | {pnl_str}"
            )

        # --- PREMIUM REPORT (full details) ---
        premium_embed = {"embeds": [{
            "title": "SML Sweep Scanner -- Daily Report Card",
            "description": f"**{datetime.now().strftime('%A, %B %d, %Y')}**",
            "color": 0xFFD700,
            "fields": [
                {"name": "Today's Signals", "value": f"{len(today_signals)} total", "inline": True},
                {"name": "Wins", "value": str(stats["wins"]), "inline": True},
                {"name": "Losses", "value": str(stats["losses"]), "inline": True},
                {"name": "All Calls", "value": "\n".join(signal_lines[:10]) or "None", "inline": False},
                {"name": "30-Day Win Rate", "value": f"{overall['win_rate']}% ({overall['wins']}W / {overall['losses']}L)", "inline": True},
                {"name": "30-Day Avg P&L", "value": f"{overall['avg_pnl_pct']:+.1f}%", "inline": True},
                {"name": "S-Tier Win Rate", "value": f"{overall['by_grade']['S']['win_rate']:.0f}%", "inline": True},
            ],
            "footer": {"text": "SML Sweep Scanner | Order-Flow-Radar | ScriptMasterLabs.com"},
            "timestamp": datetime.now().isoformat(),
        }]}

        # --- PRO REPORT (summary only, no individual P&L) ---
        pro_embed = {"embeds": [{
            "title": "SML Sweep Scanner -- Daily Summary",
            "description": f"**{datetime.now().strftime('%A, %B %d, %Y')}**",
            "color": 0x00BFFF,
            "fields": [
                {"name": "Signals Today", "value": f"{len(today_signals)}", "inline": True},
                {"name": "Results", "value": f"{stats['wins']}W / {stats['losses']}L", "inline": True},
                {"name": "30-Day Win Rate", "value": f"{overall['win_rate']}%", "inline": True},
            ],
            "footer": {"text": "Upgrade to ELITE for full report | ScriptMasterLabs.com"},
            "timestamp": datetime.now().isoformat(),
        }]}

        # --- FREE REPORT (teaser) ---
        free_embed = {"embeds": [{
            "title": "SML Sweep Scanner -- End of Day",
            "description": f"**{len(today_signals)} institutional sweep signals** detected today.\nUpgrade to PRO/ELITE to see all signals + win rates.",
            "color": 0x808080,
            "fields": [
                {"name": "Want the full report?", "value": "ScriptMasterLabs.com", "inline": False},
            ],
            "footer": {"text": "SML Sweep Scanner | ScriptMasterLabs.com"},
            "timestamp": datetime.now().isoformat(),
        }]}

        # Send to appropriate channels with retries
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            for tier, embed_payload in [
                ("premium", premium_embed),
                ("pro", pro_embed),
                ("free", free_embed),
            ]:
                wh_url = discord_webhooks.get(tier, "")
                if not wh_url:
                    continue
                
                for attempt in range(3):
                    try:
                        async with session.post(wh_url, json=embed_payload) as resp:
                            if resp.status in (200, 204):
                                logger.info(f"Report card sent to {tier.upper()}")
                                break
                            elif resp.status == 429:
                                try:
                                    err = await resp.json()
                                    wait = float(err.get("retry_after", 2.0))
                                except:
                                    wait = 2.0 * (attempt + 1)
                                logger.warning(f"Report card rate-limited [{tier.upper()}], retry in {wait}s")
                                await asyncio.sleep(wait + 0.2)
                            else:
                                body = await resp.text()
                                logger.error(f"Report card failed [{tier.upper()}] ({resp.status}): {body[:200]}")
                                break
                    except Exception as e:
                        logger.error(f"Report card send error [{tier.upper()}]: {e}")
                        await asyncio.sleep(2 ** (attempt + 1))
                
                await asyncio.sleep(0.5)  # Space out between tiers

        # Save daily report
        report_file = os.path.join(DAILY_DIR, f"report_{datetime.now().strftime('%Y-%m-%d')}.json")
        try:
            with open(report_file, "w") as f:
                json.dump({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "signals": today_signals,
                    "stats": stats,
                    "overall_30d": overall,
                }, f, indent=2, default=str)
        except:
            pass
