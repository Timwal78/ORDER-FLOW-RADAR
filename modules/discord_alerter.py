"""
Discord Alerter — 3-Tier Webhook System (FREE / PRO / PREMIUM)
Order-Flow-Radar™ | ScriptMasterLabs™

Routes signals to the correct Discord channels based on tier:
  - PREMIUM: Full trade card + options recommendations (real-time)
  - PRO:     Full trade card (real-time)
  - FREE:    Simplified signal, delayed 5 minutes

CRITICAL: This is for paying customers. Every signal MUST reach
the correct channel. Failures are retried with exponential backoff.
"""
import asyncio
import aiohttp
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("discord")


class DiscordAlerter:
    def __init__(self, legacy_url: str = ""):
        # Tiered webhook URLs — read directly from env for reliability
        self.webhook_free = os.getenv("DISCORD_WEBHOOK_FREE", "")
        self.webhook_pro = os.getenv("DISCORD_WEBHOOK_PRO", "")
        self.webhook_premium = os.getenv("DISCORD_WEBHOOK_PREMIUM", "")

        # Legacy fallback (used for status messages and heartbeats)
        self.webhook_url = legacy_url or self.webhook_pro

        self._session: aiohttp.ClientSession | None = None
        self._max_retries = 5
        self._rate_limit_window = 60
        self._rate_limit_max = 25  # Discord allows 30/min per webhook; stay under
        self._message_timestamps: list[datetime] = []

        # Delayed queue for free-tier (5-min delay)
        self.free_delay_queue: list[dict] = []

        # Delivery ledger for audit
        self.delivery_log: list[dict] = []

        # Log config state on init
        tiers_status = (
            f"FREE={'✅' if self.webhook_free else '❌'} | "
            f"PRO={'✅' if self.webhook_pro else '❌'} | "
            f"PREMIUM={'✅' if self.webhook_premium else '❌'}"
        )
        logger.info(f"DiscordAlerter INITIALIZED — {tiers_status}")
        if not any([self.webhook_free, self.webhook_pro, self.webhook_premium]):
            logger.error("CRITICAL: NO DISCORD WEBHOOKS CONFIGURED — customers will NOT receive signals!")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _check_rate_limit(self) -> bool:
        """Returns True if we can send, False if we should wait."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self._rate_limit_window)
        self._message_timestamps = [
            ts for ts in self._message_timestamps if ts > cutoff
        ]
        if len(self._message_timestamps) >= self._rate_limit_max:
            return False
        self._message_timestamps.append(now)
        return True

    # ─── Core POST with retries ─────────────────────────────────────────

    async def _post_webhook(
        self, webhook_url: str, payload: dict, tier: str = "unknown"
    ) -> bool:
        """
        Post to a Discord webhook with exponential backoff retries.
        Returns True on success, False on permanent failure.
        """
        if not webhook_url:
            return False

        session = await self._get_session()

        for attempt in range(self._max_retries):
            try:
                # Pre-flight rate check
                if not self._check_rate_limit():
                    wait = 2.0
                    logger.warning(f"[{tier}] Self-rate-limited, waiting {wait}s...")
                    await asyncio.sleep(wait)

                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status in (200, 204):
                        self._log_delivery(tier, True, resp.status)
                        return True

                    elif resp.status == 429:
                        # Discord rate limit — respect Retry-After header
                        try:
                            error_data = await resp.json()
                            wait_time = float(error_data.get("retry_after", 1.0))
                        except Exception:
                            wait_time = 2.0 * (attempt + 1)
                        logger.warning(
                            f"[{tier}] Discord 429 rate-limited. "
                            f"Retry {attempt+1}/{self._max_retries} after {wait_time:.1f}s"
                        )
                        await asyncio.sleep(wait_time + 0.2)
                        continue

                    else:
                        body = await resp.text()
                        logger.error(
                            f"[{tier}] Discord error {resp.status}: {body[:300]}"
                        )
                        self._log_delivery(tier, False, resp.status, body[:200])
                        # Retry on 5xx (server errors), give up on 4xx (client errors except 429)
                        if resp.status >= 500:
                            await asyncio.sleep(2 ** (attempt + 1))
                            continue
                        return False

            except asyncio.TimeoutError:
                logger.warning(
                    f"[{tier}] Timeout on attempt {attempt+1}/{self._max_retries}"
                )
                await asyncio.sleep(2 ** (attempt + 1))
            except aiohttp.ClientError as e:
                logger.error(f"[{tier}] Connection error: {e}")
                await asyncio.sleep(2 ** (attempt + 1))
            except Exception as e:
                logger.error(f"[{tier}] Unexpected error: {e}")
                self._log_delivery(tier, False, 0, str(e))
                return False

        logger.error(f"[{tier}] FAILED after {self._max_retries} retries — SIGNAL LOST")
        self._log_delivery(tier, False, 0, "max retries exceeded")
        return False

    def _log_delivery(self, tier: str, success: bool, status: int,
                      error: str = ""):
        self.delivery_log.append({
            "tier": tier,
            "success": success,
            "status": status,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 200 entries
        if len(self.delivery_log) > 200:
            self.delivery_log = self.delivery_log[-200:]

    # ─── Build Embeds ───────────────────────────────────────────────────

    def _build_full_embed(self, signal: dict) -> dict:
        """Build a rich embed for PRO/PREMIUM tiers."""
        symbol = signal.get("symbol", "?")
        direction = signal.get("direction", "?")
        action = signal.get("action", "?")
        score = signal.get("score", 0)
        confidence = signal.get("confidence", "?")
        reasons = signal.get("reasons", [])
        options = signal.get("options", [])
        flow = signal.get("flow", {}).get("metrics", {})

        color = 0x00FF00 if direction == "bullish" else 0xFF0000
        conf_emoji = {
            "HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🟠", "SPECULATIVE": "🔴"
        }.get(confidence, "⚪")

        embed = {
            "title": f"{'🟢' if direction == 'bullish' else '🔴'} {symbol} — {action}",
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
                f"**Net Buy:** {flow.get('buy_vol', 0):,.0f}\n"
                f"**Net Sell:** {flow.get('sell_vol', 0):,.0f}\n"
                f"**Buy %:** {flow.get('buy_pct', 0):.0f}% | "
                f"**CVD:** {flow.get('cvd', 0):,.0f}"
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

        # OPTIONS — PREMIUM VALUE
        if options:
            for i, opt in enumerate(options[:3]):
                emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
                try:
                    embed["fields"].append({
                        "name": (
                            f"{emoji} {opt.get('direction', '?')} — "
                            f"${opt.get('strike', 0):.2f} — "
                            f"{opt.get('expiration', 'N/A')}"
                        ),
                        "value": (
                            f"**DTE:** {opt.get('dte', '?')}d | "
                            f"**Delta:** {opt.get('delta', 0):.2f}\n"
                            f"**Bid/Ask:** ${opt.get('bid', 0):.2f}/"
                            f"${opt.get('ask', 0):.2f} "
                            f"(mid ${opt.get('mid', 0):.2f})\n"
                            f"**Vol:** {opt.get('volume', 0):,} | "
                            f"**OI:** {opt.get('open_interest', 0):,}\n"
                            f"**IV:** {opt.get('iv', 0):.0%} | "
                            f"**Spread:** {opt.get('spread_pct', 0):.1f}%\n"
                            f"**Grade:** {opt.get('score', 0):.0f}/100 "
                            f"({opt.get('confidence', '?')})"
                        ),
                        "inline": False,
                    })
                except (KeyError, TypeError, ValueError) as e:
                    logger.debug(f"Options format error: {e}")
        else:
            embed["fields"].append({
                "name": "⚠️ Options",
                "value": "No liquid contracts in target DTE/delta range",
                "inline": False,
            })

        return embed

    def _build_free_embed(self, signal: dict) -> dict:
        """Build a simplified embed for FREE tier (no entries/options)."""
        symbol = signal.get("symbol", "?")
        direction = signal.get("direction", "?")
        score = signal.get("score", 0)
        confidence = signal.get("confidence", "?")
        reasons = signal.get("reasons", [])

        color = 0x00FF00 if direction == "bullish" else 0xFF0000

        embed = {
            "title": (
                f"{'🟢' if direction == 'bullish' else '🔴'} "
                f"{symbol} Signal Detected"
            ),
            "description": f"A {'bullish' if direction == 'bullish' else 'bearish'} signal has been detected",
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": "Order Flow Radar — Free Tier | Upgrade at scriptmasterlabs.com"
            },
            "fields": [
                {"name": "Direction", "value": direction.upper(), "inline": True},
                {"name": "Score", "value": f"{score:.0f}/100", "inline": True},
                {"name": "Confidence", "value": confidence, "inline": True},
            ],
        }

        if reasons:
            embed["fields"].append({
                "name": "Confluences",
                "value": f"{len(reasons)} factors aligned",
                "inline": True,
            })

        embed["fields"].append({
            "name": "🔓 Upgrade",
            "value": (
                "Get exact entries, stops, targets & options picks\n"
                "→ **scriptmasterlabs.com**"
            ),
            "inline": False,
        })

        return embed

    # ─── Public API ─────────────────────────────────────────────────────

    async def send_signal(self, signal: dict):
        """
        Route a signal to ALL appropriate tier channels.
        This is the main method called from signal_eval_loop in main.py.
        
        Routing:
          - PREMIUM: real-time full card + options (if options exist)
          - PRO:     real-time full card
          - FREE:    simplified card, queued for 5-min delay
        """
        symbol = signal.get("symbol", "?")
        has_options = bool(signal.get("options"))

        full_embed = self._build_full_embed(signal)
        free_embed = self._build_free_embed(signal)

        results = {}

        # ── PREMIUM (real-time, with options) ──
        if self.webhook_premium:
            premium_payload = {"embeds": [full_embed]}
            # Add a premium header if options are present
            if has_options:
                premium_payload["content"] = f"🏆 **PREMIUM SIGNAL** — {symbol}"
            ok = await self._post_webhook(
                self.webhook_premium, premium_payload, "PREMIUM"
            )
            results["premium"] = ok
            await asyncio.sleep(0.4)  # Micro-delay between channels

        # ── PRO (real-time, full card, no options section) ──
        if self.webhook_pro:
            # For PRO, send the full embed but strip options fields
            pro_embed = dict(full_embed)
            pro_embed["fields"] = [
                f for f in full_embed["fields"]
                if not (f.get("name", "").startswith("🥇") or
                       f.get("name", "").startswith("🥈") or
                       f.get("name", "").startswith("🥉"))
            ]
            # Replace options warning with upgrade CTA
            pro_embed["fields"] = [
                f for f in pro_embed["fields"]
                if f.get("name") != "⚠️ Options"
            ]
            pro_embed["fields"].append({
                "name": "🔒 Options Picks",
                "value": "Upgrade to **Premium** for exact options recommendations",
                "inline": False,
            })
            pro_payload = {"embeds": [pro_embed]}
            ok = await self._post_webhook(self.webhook_pro, pro_payload, "PRO")
            results["pro"] = ok
            await asyncio.sleep(0.4)

        # ── FREE (simplified, delayed 5 min) ──
        if self.webhook_free:
            self.free_delay_queue.append({
                "embed": free_embed,
                "send_at": datetime.now(timezone.utc) + timedelta(minutes=5),
                "symbol": symbol,
            })
            results["free"] = "queued"

        logger.info(
            f"Signal routed: {symbol} → "
            f"PREMIUM={'✅' if results.get('premium') else '—'} | "
            f"PRO={'✅' if results.get('pro') else '—'} | "
            f"FREE={'queued' if results.get('free') == 'queued' else '—'}"
        )

    async def process_free_queue(self):
        """
        Process delayed free-tier queue. Must be called periodically
        from main.py's free_queue_loop.
        """
        now = datetime.now(timezone.utc)
        to_send = [item for item in self.free_delay_queue if item["send_at"] <= now]

        for item in to_send:
            payload = {"embeds": [item["embed"]]}
            ok = await self._post_webhook(self.webhook_free, payload, "FREE")
            if ok:
                logger.info(f"Free-tier delayed signal sent: {item.get('symbol', '?')}")
            self.free_delay_queue.remove(item)
            await asyncio.sleep(0.5)

    async def send_status(self, message: str):
        """Send a plain status message to ALL tier channels and legacy."""
        payload = {"content": message}

        # Send to all configured webhooks
        webhooks = [
            (self.webhook_free, "FREE"),
            (self.webhook_pro, "PRO"),
            (self.webhook_premium, "PREMIUM"),
        ]

        for url, tier in webhooks:
            if url:
                await self._post_webhook(url, payload, tier)
                await asyncio.sleep(0.3)

    async def send_to_tier(self, tier: str, payload: dict) -> bool:
        """Send directly to a specific tier channel."""
        urls = {
            "free": self.webhook_free,
            "pro": self.webhook_pro,
            "premium": self.webhook_premium,
        }
        url = urls.get(tier.lower(), "")
        if not url:
            logger.warning(f"No webhook for tier: {tier}")
            return False
        return await self._post_webhook(url, payload, tier.upper())

    def get_delivery_stats(self) -> dict:
        """Get delivery success/failure stats for monitoring."""
        total = len(self.delivery_log)
        if total == 0:
            return {"total": 0, "success_rate": 0, "by_tier": {}}

        successes = sum(1 for d in self.delivery_log if d["success"])
        by_tier = {}
        for entry in self.delivery_log:
            tier = entry["tier"]
            if tier not in by_tier:
                by_tier[tier] = {"sent": 0, "failed": 0}
            if entry["success"]:
                by_tier[tier]["sent"] += 1
            else:
                by_tier[tier]["failed"] += 1

        return {
            "total": total,
            "success_rate": (successes / total * 100) if total > 0 else 0,
            "by_tier": by_tier,
            "queue_depth": len(self.free_delay_queue),
        }
