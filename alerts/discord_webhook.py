"""
Tiered Discord alerter.
Routes signals to #free-signals, #pro-signals, or #premium-signals
based on alert level and whether options recommendations are attached.

Routing logic:
  - ALL signals -> #free-signals (simplified, delayed 5 min)
  - Score >= CONFLUENCE_MIN -> #pro-signals (real-time, full trade card)
  - Score >= CONFLUENCE_MIN + has options rec -> #premium-signals (real-time, trade card + options)

REAL DATA ONLY - never fabricate or guess signal data.
"""

import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
import os

from alerts.formatter import format_discord_embed, format_free_tier_embed

logger = logging.getLogger(__name__)


class DiscordAlerter:
    def __init__(self, config):
        self.config = config

        # Tiered webhook URLs
        self.webhook_free = os.getenv("DISCORD_WEBHOOK_FREE", "")
        self.webhook_pro = os.getenv("DISCORD_WEBHOOK_PRO", "")
        self.webhook_premium = os.getenv("DISCORD_WEBHOOK_PREMIUM", "")

        # Legacy fallback
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL", self.webhook_pro)

        self.max_retries = config.get("DISCORD_MAX_RETRIES", 3)
        self.rate_limit = config.get("DISCORD_RATE_LIMIT", 5)
        self.rate_limit_window = 60

        self.last_messages = []

        # Delayed queue for free-tier (5 min delay)
        self.free_delay_queue = []

        logger.info(f"DiscordAlerter initialized — Free: {'SET' if self.webhook_free else 'MISSING'}, "
                     f"Pro: {'SET' if self.webhook_pro else 'MISSING'}, "
                     f"Premium: {'SET' if self.webhook_premium else 'MISSING'}")

    async def _apply_rate_limit(self) -> bool:
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        self.last_messages = [ts for ts in self.last_messages if ts > cutoff]
        if len(self.last_messages) >= self.rate_limit:
            return False
        self.last_messages.append(now)
        return True

    async def _post_webhook(self, webhook_url: str, embed: dict, retry_count: int = 0) -> bool:
        """Send embed to a specific webhook URL with retries."""
        if not webhook_url:
            logger.warning("No webhook URL provided, skipping")
            return False

        try:
            if not await self._apply_rate_limit():
                logger.warning("Rate limited, queuing message")
                return False

            payload = {"embeds": [embed]}

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 204:
                        logger.info(f"Discord alert sent successfully")
                        return True
                    elif response.status == 429:
                        wait_time = int(response.headers.get("Retry-After", 1))
                        logger.warning(f"Discord rate limited, retrying after {wait_time}s")
                        if retry_count < self.max_retries:
                            await asyncio.sleep(wait_time)
                            return await self._post_webhook(webhook_url, embed, retry_count + 1)
                        return False
                    else:
                        body = await response.text()
                        logger.error(f"Discord API error {response.status}: {body}")
                        if retry_count < self.max_retries:
                            await asyncio.sleep(2 ** (retry_count + 1))
                            return await self._post_webhook(webhook_url, embed, retry_count + 1)
                        return False

        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.error(f"Discord request error: {e}")
            if retry_count < self.max_retries:
                await asyncio.sleep(2 ** (retry_count + 1))
                return await self._post_webhook(webhook_url, embed, retry_count + 1)
            return False
        except Exception as e:
            logger.error(f"Unexpected Discord error: {e}")
            return False

    async def send_alert(self, embed: dict) -> bool:
        """Send alert to pro webhook (legacy single-channel method)."""
        return await self._post_webhook(self.webhook_url, embed)

    async def send_tiered_alert(self, trade_card: dict):
        """
        Route a signal to the correct Discord channels based on tier.
        
        - PREMIUM: full trade card + options recommendations (if available)
        - PRO: full trade card (real-time)
        - FREE: simplified signal (delayed 5 min)
        """
        score = trade_card.get("score", 0)
        has_options = "options_recommendation" in trade_card

        # Build embeds
        full_embed = format_discord_embed(trade_card)
        free_embed = format_free_tier_embed(trade_card)

        if not full_embed:
            logger.error("Failed to format embed, skipping alert")
            return

        results = {}

        # PREMIUM channel: full trade card + options (if score qualifies and options present)
        if has_options and self.webhook_premium:
            results["premium"] = await self._post_webhook(self.webhook_premium, full_embed)

        # PRO channel: full trade card (real-time)
        if self.webhook_pro:
            results["pro"] = await self._post_webhook(self.webhook_pro, full_embed)

        # FREE channel: simplified embed (queued with 5-min delay)
        if free_embed and self.webhook_free:
            self.free_delay_queue.append({
                "embed": free_embed,
                "send_at": datetime.utcnow() + timedelta(minutes=5)
            })

        logger.info(f"Tiered alert results for {trade_card.get('symbol', '?')}: {results}")

    async def process_free_queue(self):
        """Process the delayed free-tier queue. Call this periodically."""
        now = datetime.utcnow()
        to_send = [item for item in self.free_delay_queue if item["send_at"] <= now]

        for item in to_send:
            await self._post_webhook(self.webhook_free, item["embed"])
            self.free_delay_queue.remove(item)
