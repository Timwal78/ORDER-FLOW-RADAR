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
        self._queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = True

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _worker(self):
        """Background worker that releases alerts sequentially to avoid 429s."""
        logger.info("Discord worker started (Meter: 1.5s delay)")
        while self._running:
            try:
                url, payload = await self._queue.get()
                
                # Send with retry logic
                await self._send_raw_guaranteed(url, payload)
                
                # Mandatory inter-message delay (Headroom for external hooks like SqueezeOS)
                await asyncio.sleep(1.5)
                self._queue.task_done()
            except Exception as e:
                logger.error(f"Discord worker error: {e}")
                await asyncio.sleep(1)

    async def _send_raw_guaranteed(self, url: str, payload: dict):
        """Attempts to send with exponential backoff on 429."""
        retries = 0
        while retries < 3:
            async with self._get_session().post(url, json=payload, timeout=10) as resp:
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", 5))
                    logger.warning(f"Discord 429 on {url[:30]}! Sleeping {retry_after}s...")
                    await asyncio.sleep(retry_after + 0.5)
                    retries += 1
                elif resp.status not in (200, 204):
                    body = await resp.text()
                    logger.error(f"Discord error {resp.status}: {body[:100]}")
                    break
                else:
                    return # Success
        logger.error(f"Gave up on Discord message after {retries} retries.")

    async def send_status(self, text: str):
        """Queue a status message for all hooks."""
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._worker())
            
        for tier, url in self._hooks.items():
            if url:
                self._queue.put_nowait((url, {"content": text}))

    async def send_signal(self, sig: dict, tier: str = "premium"):
        """Queue a signal for a specific tier."""
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._worker())

        url = self._hooks.get(tier)
        if not url:
            return

        embed = self._build_embed(sig, tier)
        payload = {"embeds": [embed]}
        
        if tier == "free":
            payload["content"] = "🔓 *Partial signal. Join Pro/Premium for real-time institutional flow.*"

        self._queue.put_nowait((url, payload))

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

        # Add AI Audit if present
        if sig.get("ai_auditor_reason"):
            embed["fields"].append({
                "name": "🤖 Institutional AI Auditor",
                "value": f"*{sig['ai_auditor_reason']}*",
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

    async def close(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
