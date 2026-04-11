"""
SML X.com Signal Bot — Auto-posts delayed sweep signals to X (Twitter).
Posts B/C grade signals with 15-minute delay for marketing.
S/A grade signals are mentioned but redacted with upgrade CTA.

Uses X API v2 (OAuth 2.0) via tweepy.
Requires: TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN,
          TWITTER_ACCESS_SECRET in .env
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger("xbot")

# Queue of signals waiting for their 15-minute delay
_signal_queue: deque = deque(maxlen=100)


class XSignalBot:
    """Auto-posts sweep signals to X.com with a 15-min delay."""

    def __init__(self):
        self.api_key = os.getenv("TWITTER_API_KEY", "")
        self.api_secret = os.getenv("TWITTER_API_SECRET", "")
        self.access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
        self.access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")
        self.enabled = all([self.api_key, self.api_secret,
                           self.access_token, self.access_secret])
        self._client = None
        self._post_count = 0

        if self.enabled:
            logger.info("X.com Signal Bot: credentials loaded")
        else:
            logger.info("X.com Signal Bot: disabled (no credentials)")

    def _get_client(self):
        """Lazy init tweepy client."""
        if self._client:
            return self._client
        try:
            import tweepy
            self._client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_secret,
            )
            return self._client
        except ImportError:
            logger.warning("tweepy not installed — X.com bot disabled")
            self.enabled = False
            return None
        except Exception as e:
            logger.warning(f"X.com client init error: {e}")
            return None

    def queue_signal(self, signal: dict):
        """Queue a signal for delayed posting."""
        _signal_queue.append({
            "signal": signal,
            "queued_at": datetime.now(),
            "post_after": datetime.now() + timedelta(minutes=15),
            "posted": False,
        })
        logger.debug(f"X.com: queued {signal['ticker']} for delayed post")

    async def process_queue(self):
        """Check queue and post signals that have passed the 15-min delay."""
        if not self.enabled:
            return

        now = datetime.now()
        for item in list(_signal_queue):
            if item["posted"]:
                continue
            if now < item["post_after"]:
                continue

            signal = item["signal"]

            # Build tweet based on grade
            if signal["grade"] in ("S", "A"):
                # Redacted — shows the signal exists but not the details
                tweet = self._build_redacted_tweet(signal)
            else:
                # Full signal for B/C grade (free content)
                tweet = self._build_full_tweet(signal)

            success = await self._post_tweet(tweet)
            if success:
                item["posted"] = True
                self._post_count += 1
                logger.info(f"X.com: posted {signal['ticker']} [{signal['grade']}] (#{self._post_count})")

            # Rate limit: max 1 per 3 minutes
            await asyncio.sleep(180)

    def _build_full_tweet(self, sig):
        """Full tweet for B/C grade signals — free marketing content."""
        emoji = {"B": "++", "C": ">"}.get(sig["grade"], ">")
        direction = "CALLS" if "CALL" in sig["action"] else "PUTS" if "PUT" in sig["action"] else sig["direction"].upper()

        tweet = (
            f"{emoji} ${sig['ticker']} Institutional Sweep Detected\n\n"
            f"{sig['action']} | Score: {sig['score']}/12 [{sig['grade']}]\n"
            f"Combined Premium: ${sig['combined']:,.0f}\n"
            f"Direction: {direction}\n\n"
            f"Entry: ${sig['entry']:.2f} | Stop: ${sig['stop']:.2f}\n"
            f"TP1: ${sig['tp1']:.2f} | TP2: ${sig['tp2']:.2f}\n\n"
            f"#OptionsFlow #SweepAlert #{sig['ticker']} "
            f"#SmartMoney #InstitutionalFlow\n\n"
            f"Real-time S/A-grade alerts at ScriptMasterLabs.com"
        )
        return tweet[:280]  # X character limit

    def _build_redacted_tweet(self, sig):
        """Redacted tweet for S/A grade — teaser with upgrade CTA."""
        emoji = {"S": "[S-TIER]", "A": "[A-TIER]"}.get(sig["grade"], "")

        tweet = (
            f"{emoji} ${sig['ticker']} — Whale Alert Detected\n\n"
            f"${sig['combined']:,.0f} in institutional sweep flow\n"
            f"Score: {sig['score']}/12\n\n"
            f"Strike, expiration, entry/stop/TP?\n"
            f"PRO & ELITE subscribers got this 15 min ago.\n\n"
            f"#OptionsFlow #SweepAlert #{sig['ticker']} "
            f"#WhaleMoves #SmartMoney\n\n"
            f"Get real-time signals: ScriptMasterLabs.com"
        )
        return tweet[:280]

    async def _post_tweet(self, text):
        """Post a tweet via X API v2."""
        client = self._get_client()
        if not client:
            return False

        try:
            # tweepy v2 create_tweet
            response = client.create_tweet(text=text)
            if response and response.data:
                tweet_id = response.data.get("id", "")
                logger.info(f"X.com: tweet posted (id: {tweet_id})")
                return True
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "Too Many" in error_str:
                logger.warning("X.com: rate limited, will retry next cycle")
            elif "403" in error_str or "Forbidden" in error_str:
                logger.warning("X.com: forbidden — check API permissions")
                self.enabled = False
            else:
                logger.warning(f"X.com post error: {e}")
        return False

    async def post_daily_recap(self, journal_stats: dict):
        """Post daily recap tweet with win rate."""
        if not self.enabled:
            return
        if journal_stats.get("total_signals", 0) < 1:
            return

        tweet = (
            f"SML Sweep Scanner -- Daily Recap\n\n"
            f"Signals: {journal_stats['total_signals']}\n"
            f"Win Rate: {journal_stats['win_rate']}%\n"
            f"Record: {journal_stats['wins']}W / {journal_stats['losses']}L\n\n"
            f"S-Tier Win Rate: {journal_stats.get('by_grade', {}).get('S', {}).get('win_rate', 0):.0f}%\n\n"
            f"#OptionsTrading #SweepAlert #TradingAlerts\n"
            f"Real-time: ScriptMasterLabs.com"
        )
        await self._post_tweet(tweet[:280])
