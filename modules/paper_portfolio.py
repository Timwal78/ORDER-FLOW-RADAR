"""
SML Paper Trading Portfolio — Simulated P&L Tracker
Free tier users can "follow" sweep signals in a virtual portfolio.
Shows them the money they're missing by not being Premium.
Sends weekly P&L summary to FREE tier with upgrade CTA.
"""
import os
import json
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger("paper")

PORTFOLIO_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "signal_data", "paper_portfolio.json"
)


class PaperPortfolio:
    """Virtual portfolio that auto-follows all sweep signals."""

    def __init__(self, starting_balance=10000):
        self.starting_balance = starting_balance
        self.data = self._load()

    def _load(self):
        if os.path.exists(PORTFOLIO_FILE):
            try:
                with open(PORTFOLIO_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return {
            "balance": self.starting_balance,
            "starting_balance": self.starting_balance,
            "positions": [],
            "closed_trades": [],
            "total_pnl": 0,
            "win_count": 0,
            "loss_count": 0,
            "created_at": datetime.now().isoformat(),
        }

    def _save(self):
        try:
            os.makedirs(os.path.dirname(PORTFOLIO_FILE), exist_ok=True)
            with open(PORTFOLIO_FILE, "w") as f:
                json.dump(self.data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Paper portfolio save error: {e}")

    def open_position(self, signal: dict):
        """
        Auto-follow a sweep signal with a fixed risk allocation.
        Risk 2% of balance per trade ($200 on $10K).
        """
        balance = self.data["balance"]
        risk_pct = 0.02  # 2% risk per trade
        risk_amount = balance * risk_pct

        entry_price = signal["entry"]
        if entry_price <= 0:
            return

        # How many contracts can we afford with 2% risk?
        contract_cost = entry_price * 100  # 1 contract = 100 shares
        if contract_cost <= 0:
            return

        contracts = max(1, int(risk_amount / contract_cost))
        total_cost = contracts * contract_cost

        position = {
            "id": f"{signal['ticker']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "opened_at": datetime.now().isoformat(),
            "ticker": signal["ticker"],
            "action": signal["action"],
            "direction": signal["direction"],
            "contract": signal["contract"],
            "strike": signal["strike"],
            "expiration": signal["expiration"],
            "grade": signal["grade"],
            "score": signal["score"],
            "entry_price": entry_price,
            "contracts": contracts,
            "total_cost": total_cost,
            "stop_price": signal["stop"],
            "tp1": signal["tp1"],
            "tp2": signal["tp2"],
            "current_price": entry_price,
            "current_value": total_cost,
            "unrealized_pnl": 0,
            "unrealized_pnl_pct": 0,
            "status": "OPEN",  # OPEN, TP1_HIT, TP2_HIT, STOPPED, EXPIRED
        }

        self.data["positions"].append(position)
        self.data["balance"] -= total_cost
        self._save()
        logger.info(f"Paper: Opened {contracts}x {signal['contract']} @ ${entry_price:.2f} (${total_cost:.0f})")

    def update_prices(self, price_updates: dict):
        """
        Update current prices for open positions.
        price_updates: {ticker: current_underlying_price}
        """
        for pos in self.data["positions"]:
            if pos["status"] not in ("OPEN", "TP1_HIT"):
                continue

            # Approximate option price change based on delta
            # This is simplified — in reality you'd need real option quotes
            underlying_price = price_updates.get(pos["ticker"])
            if not underlying_price:
                continue

            # Simple delta approximation
            price_change = underlying_price - pos.get("_last_underlying", pos["strike"])
            pos["_last_underlying"] = underlying_price

            # For now, just track underlying movement
            entry = pos["entry_price"]
            current = pos["current_price"]

            # Check stops and targets
            if current <= pos["stop_price"]:
                self._close_position(pos, pos["stop_price"], "STOPPED")
            elif current >= pos["tp2"]:
                self._close_position(pos, pos["tp2"], "TP2_HIT")
            elif current >= pos["tp1"] and pos["status"] != "TP1_HIT":
                pos["status"] = "TP1_HIT"
                # Close half at TP1
                half_contracts = max(1, pos["contracts"] // 2)
                pnl = (pos["tp1"] - entry) * half_contracts * 100
                self.data["balance"] += half_contracts * pos["tp1"] * 100
                self.data["total_pnl"] += pnl
                pos["contracts"] -= half_contracts
                logger.info(f"Paper: TP1 hit on {pos['ticker']} — closed {half_contracts} contracts (+${pnl:.0f})")

            # Update unrealized P&L
            pos["unrealized_pnl"] = (current - entry) * pos["contracts"] * 100
            pos["unrealized_pnl_pct"] = ((current - entry) / entry * 100) if entry > 0 else 0

        # Check expirations
        today = datetime.now().date()
        for pos in self.data["positions"]:
            if pos["status"] in ("OPEN", "TP1_HIT"):
                try:
                    exp = datetime.strptime(pos["expiration"], "%Y-%m-%d").date()
                    if exp <= today:
                        self._close_position(pos, pos["current_price"], "EXPIRED")
                except:
                    pass

        self._save()

    def _close_position(self, pos, exit_price, reason):
        """Close a position and move to closed trades."""
        pnl = (exit_price - pos["entry_price"]) * pos["contracts"] * 100
        self.data["balance"] += pos["contracts"] * exit_price * 100
        self.data["total_pnl"] += pnl

        if pnl > 0:
            self.data["win_count"] += 1
        else:
            self.data["loss_count"] += 1

        pos["status"] = reason
        pos["exit_price"] = exit_price
        pos["closed_at"] = datetime.now().isoformat()
        pos["realized_pnl"] = pnl

        self.data["closed_trades"].append(pos)
        self.data["positions"] = [p for p in self.data["positions"] if p["id"] != pos["id"]]

        logger.info(f"Paper: Closed {pos['ticker']} ({reason}) — P&L: ${pnl:+.0f}")

    def get_summary(self):
        """Get portfolio summary for display."""
        open_positions = [p for p in self.data["positions"] if p["status"] in ("OPEN", "TP1_HIT")]
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in open_positions)
        total_closed = len(self.data["closed_trades"])
        wins = self.data["win_count"]
        losses = self.data["loss_count"]
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        return {
            "balance": round(self.data["balance"], 2),
            "starting_balance": self.data["starting_balance"],
            "total_pnl": round(self.data["total_pnl"], 2),
            "total_return_pct": round((self.data["balance"] - self.data["starting_balance"]) / self.data["starting_balance"] * 100, 1),
            "unrealized_pnl": round(total_unrealized, 2),
            "open_positions": len(open_positions),
            "closed_trades": total_closed,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
        }

    async def send_weekly_summary(self):
        """Send weekly P&L summary to FREE tier — shows what they're missing."""
        webhook_free = os.getenv("DISCORD_WEBHOOK_FREE", "")
        if not webhook_free:
            return

        summary = self.get_summary()

        # Only send if we have meaningful data
        if summary["closed_trades"] < 3:
            return

        pnl_emoji = "+" if summary["total_pnl"] >= 0 else ""

        embed = {"embeds": [{
            "title": "SML Sweep Scanner -- Paper Trading Results",
            "description": (
                f"**Virtual Portfolio Performance**\n"
                f"Starting: ${summary['starting_balance']:,.0f}\n"
                f"Current: ${summary['balance']:,.0f}\n\n"
                f"**These are REAL signals you missed.**\n"
                f"Upgrade to PRO/ELITE to get them in real-time."
            ),
            "color": 0x00FF6A if summary["total_pnl"] >= 0 else 0xFF2D7B,
            "fields": [
                {"name": "Total P&L", "value": f"{pnl_emoji}${summary['total_pnl']:,.0f} ({summary['total_return_pct']:+.1f}%)", "inline": True},
                {"name": "Win Rate", "value": f"{summary['win_rate']}%", "inline": True},
                {"name": "Record", "value": f"{summary['wins']}W / {summary['losses']}L", "inline": True},
                {"name": "Trades", "value": f"{summary['closed_trades']} closed / {summary['open_positions']} open", "inline": False},
                {"name": "Want these signals LIVE?", "value": "**ScriptMasterLabs.com** -- Upgrade to PRO or ELITE", "inline": False},
            ],
            "footer": {"text": "Paper trading results | Past performance not indicative of future results"},
            "timestamp": datetime.now().isoformat(),
        }]}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_free, json=embed) as resp:
                    if resp.status in (200, 204):
                        logger.info("Paper portfolio weekly summary sent to FREE")
        except Exception as e:
            logger.warning(f"Paper summary send error: {e}")
