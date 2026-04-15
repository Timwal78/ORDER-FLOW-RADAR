"""
Order Flow Radar™ — Discord Alerter
ScriptMasterLabs™

Low-level Discord webhook delivery with tier-specific formatting.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Dict, Any, Optional

import aiohttp

import config

logger = logging.getLogger("discord_alerter")


class DiscordAlerter:
    def __init__(self):
        self._hooks = {
            "free":    config.DISCORD_WEBHOOK_FREE,
            "pro":     config.DISCORD_WEBHOOK_PRO,
            "premium": config.DISCORD_WEBHOOK_PREMIUM,
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Semaphore(5)  # Max 5 concurrent Discord calls

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send_status(self, text: str):
        """Send a simple system status message to all configured webhooks."""
        for tier, url in self._hooks.items():
            if url:
                await self._send_raw(url, {"content": text})

    async def send_signal(self, sig: dict, tier: str = "premium"):
        """
        Send a formatted signal alert to a specific tier.
        Premium tier gets full options data. Free tier gets summary.
        """
        url = self._hooks.get(tier)
        if not url:
            return

        embed = self._build_embed(sig, tier)
        payload = {"embeds": [embed]}
        
        # Free tier gets a "Upgrade" footer
        if tier == "free":
            payload["content"] = "🔓 *Partial signal. Join Pro/Premium for real-time institutional flow.*"

        await self._send_raw(url, payload)

    def _build_embed(self, sig: dict, tier: str) -> dict:
        color = 0x00FF00 if sig["action"] == "LONG" else 0xFF0000
        emoji = "🟢" if sig["action"] == "LONG" else "🔴"
        
        embed = {
            "title": f"{emoji} {sig['action']} SIGNAL: {sig['symbol']}",
            "description": f"Institutional order flow detected for **{sig['symbol']}**.",
            "color": color,
            "fields": [
                {"name": "Price", "value": f"${sig['price']:.2f}", "inline": True},
                {"name": "Score", "value": f"{sig['score']:.1f}", "inline": True},
                {"name": "CVD Ratio", "value": f"{sig['cvd_ratio']:.0%}", "inline": True},
            ],
            "footer": {"text": f"Order-Flow-Radar™ | {sig['fired_at'][:19]}"}
        }

        # Add confluences
        embed["fields"].append({
            "name": "Confluences",
            "value": " • " + "\n • ".join(sig["confluences"]),
            "inline": False
        })

        # Add options recommendations (Premium only)
        if tier == "premium" and sig.get("options_recs"):
            rec_lines = []
            for r in sig["options_recs"]:
                rec_lines.append(
                    f"**{r['expiration']} ${r['strike']:.1f}** {r['direction']} "
                    f"(Delta: {r['delta']:.2f}, Mid: ${r['mid']:.2f}, OI: {r['open_interest']:,})"
                )
            embed["fields"].append({
                "name": "🎯 Alpha Strategies (Institutional)",
                "value": "\n".join(rec_lines),
                "inline": False
            })

        return embed

    async def _send_raw(self, url: str, payload: dict):
        async with self._lock:
            try:
                async with self._get_session().post(url, json=payload, timeout=10) as resp:
                    if resp.status not in (200, 204):
                        body = await resp.text()
                        logger.error(f"Discord error {resp.status} on {url[:40]}...: {body[:100]}")
                    # Law-compliant spacing to avoid 429 flood
                    await asyncio.sleep(0.5) 
            except Exception as e:
                logger.error(f"Discord request error: {e}")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
