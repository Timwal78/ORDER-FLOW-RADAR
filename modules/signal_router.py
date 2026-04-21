"""
Order Flow Radar™ — Signal Router
ScriptMasterLabs™

Processes directional signals and routes them to alert channels.
Handles tiered delivery delays (Free, Pro, Premium).
"""
from __future__ import annotations
import asyncio
import logging
from typing import Dict, Any, List

import config
from modules.confluence_engine import Signal
from modules.discord_alerter import DiscordAlerter
from modules.signal_journal import SignalJournal
from modules.dashboard import push_signal

logger = logging.getLogger("signal_router")


class SignalRouter:
    def __init__(self, discord: DiscordAlerter, journal: SignalJournal):
        self._discord = discord
        self._journal = journal
        self._queue = asyncio.Queue()
        self._running = False

    async def route(self, signal: Signal):
        """
        High-level routing:
        1. Push to Dashboard (Immediate SSE)
        2. Journal it (Real-time log)
        3. Dispatch to Discord (Tiered queuing)
        """
        sig_dict = signal.to_dict()

        # 1. Update Dashboard immediately
        await push_signal(sig_dict)

        # 2. Only Alert and Journal if it's a new unique signal
        if signal.is_new_alert:
            # Journal for performance tracking
            await self._journal.log_signal(sig_dict)
            
            # Queue for Discord tiers (Immediate Premium, Delayed Pro/Free)
            await self._dispatch_discord(sig_dict)

            # Log the actionable instruction, not just technical data
            plan = sig_dict.get("trade_plan", {})
            instruction = plan.get("instruction", f"{signal.symbol} {signal.action}")
            grade = plan.get("grade", "?")
            logger.info(f"[Grade {grade}] {instruction}")

    async def _dispatch_discord(self, sig_dict: dict):
        """Dispatches to Discord tiers with appropriate delays."""
        # Premium: Immediate
        asyncio.create_task(self._send_delayed(
            sig_dict, "premium", config.DISCORD_PREMIUM_DELAY_SECONDS
        ))

        # Pro: 2 min delay (config)
        asyncio.create_task(self._send_delayed(
            sig_dict, "pro", config.DISCORD_PRO_DELAY_SECONDS
        ))

        # Free: 30 min delay (config)
        asyncio.create_task(self._send_delayed(
            sig_dict, "free", config.DISCORD_FREE_DELAY_SECONDS
        ))

    async def _send_delayed(self, sig_dict: dict, tier: str, delay: int):
        if delay > 0:
            await asyncio.sleep(delay)
        
        try:
            await self._discord.send_signal(sig_dict, tier=tier)
        except Exception as e:
            logger.error(f"Failed to send {tier} alert for {sig_dict['symbol']}: {e}")
