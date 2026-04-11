"""
Discord Alerter — Rich embeds with exact options recommendations.
Strike + Date + Delta + Direction + Confidence.
No placeholder text. Real data only.
"""
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger("discord")


class DiscordAlerter:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_signal(self, signal: dict):
        """Send a full signal with options recs to Discord."""
        if not self.webhook_url:
            logger.warning("No Discord webhook configured")
            return

        symbol = signal.get("symbol", "?")
        direction = signal.get("direction", "?")
        action = signal.get("action", "?")
        score = signal.get("score", 0)
        confidence = signal.get("confidence", "?")
        reasons = signal.get("reasons", [])
        options = signal.get("options", [])
        flow = signal.get("flow", {}).get("metrics", {})
        timestamp = signal.get("timestamp", "")

        # Color: green for bullish, red for bearish
        color = 0x00FF00 if direction == "bullish" else 0xFF0000

        # Confidence emoji
        conf_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🟠", "SPECULATIVE": "🔴"}.get(confidence, "⚪")

        # Build embed
        embed = {
            "title": f"{'🟢' if direction == 'bullish' else '🔴'} {symbol} — {action}",
            "color": color,
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "Order-Flow-Radar™ | ScriptMasterLabs™"},
            "fields": [],
        }

        # Signal overview
        embed["fields"].append({
            "name": "📊 Signal",
            "value": (
                f"**Score:** {score:.0f}/100\n"
                f"**Confidence:** {conf_emoji} {confidence}\n"
                f"**Direction:** {direction.upper()}"
            ),
            "inline": True,
        })

        # Flow metrics
        embed["fields"].append({
            "name": "📈 Flow",
            "value": (
                f"**Buy:** {flow.get('buy_pct', 0):.0f}%\n"
                f"**CVD:** {flow.get('cvd', 0):,.0f}\n"
                f"**Lg Buys:** {flow.get('large_buys', 0)} | **Sells:** {flow.get('large_sells', 0)}"
            ),
            "inline": True,
        })

        # Reasons
        if reasons:
            embed["fields"].append({
                "name": "💡 Why",
                "value": "\n".join(f"• {r}" for r in reasons[:5]),
                "inline": False,
            })

        # OPTIONS RECOMMENDATIONS — THE MONEY SHOT
        if options:
            for i, opt in enumerate(options):
                emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
                embed["fields"].append({
                    "name": f"{emoji} {opt['direction']} — ${opt['strike']:.2f} — {opt['expiration']}",
                    "value": (
                        f"**DTE:** {opt['dte']}d | **Delta:** {opt['delta']:.2f}\n"
                        f"**Bid/Ask:** ${opt['bid']:.2f}/${opt['ask']:.2f} (mid ${opt['mid']:.2f})\n"
                        f"**Vol:** {opt['volume']:,} | **OI:** {opt['open_interest']:,}\n"
                        f"**IV:** {opt['iv']:.0%} | **Spread:** {opt['spread_pct']:.1f}%\n"
                        f"**Contract Score:** {opt['score']:.0f}/100 ({opt['confidence']})"
                    ),
                    "inline": False,
                })
        else:
            embed["fields"].append({
                "name": "⚠️ Options",
                "value": "No liquid contracts found in target DTE/delta range",
                "inline": False,
            })

        payload = {"embeds": [embed]}

        try:
            session = await self._get_session()
            for attempt in range(4):  # Try up to 4 times
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status == 429:
                        try:
                            error_data = await resp.json()
                            wait_time = float(error_data.get("retry_after", 1.0))
                            # Optional: you can uncomment the next line if you want to see when it's waiting
                            # logger.debug(f"Discord throttle hit. Waiting {wait_time}s before sending {symbol}...")
                            await asyncio.sleep(wait_time + 0.1)
                            continue
                        except:
                            await asyncio.sleep(1.5)
                            continue
                    elif resp.status not in (200, 204):
                        body = await resp.text()
                        logger.warning(f"Discord send failed ({resp.status}): {body[:200]}")
                        break
                    else:
                        logger.info(f"Discord alert sent: {symbol} {action}")
                        # Add a tiny micro-delay globally to prevent bursting too hard
                        await asyncio.sleep(0.3)
                        break
        except Exception as e:
            logger.error(f"Discord send error: {e}")

    async def send_status(self, message: str):
        """Send a plain status message."""
        if not self.webhook_url:
            return
        payload = {"content": message}
        try:
            session = await self._get_session()
            await session.post(self.webhook_url, json=payload)
        except Exception:
            pass
