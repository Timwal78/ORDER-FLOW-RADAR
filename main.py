"""
TradingSignalOrchestrator: Main orchestrator for the trading system.
Drives market discovery, scanning, signal evaluation, outcome tracking, and learning.

Architecture:
1. Market Discovery: Refresh every hour
2. Continuous Scanning Loop: Scan all discovered symbols
3. Outcome Checker: Check if signals hit TP/SL every 5 minutes
4. Learner Retraining: Every 24 hours or every 50 completed signals
5. FastAPI Server: REST API + WebSocket for live signals
"""

import asyncio
import logging
import signal
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# Signal modules
from signals.orderflow import OrderFlowSignals
from signals.momentum import MomentumSignals
from signals.volume import VolumeSignals
from signals.trend import TrendSignals
from signals.levels import LevelSignals
from signals.confluence import ConfluenceEngine
from signals.learner import SignalLearner

# Alert modules
from alerts.formatter import format_discord_embed
from alerts.discord_webhook import DiscordAlerter
from alerts.journal import SignalJournal

# Data and discovery
from market_scanner import MarketScanner

# Configuration
from config import load_config

# Web server
import uvicorn

logger = logging.getLogger(__name__)


class TradingSignalOrchestrator:
    """Main orchestrator for the trading signal system."""

    def __init__(self, config: Dict):
        self.config = config
        self.running = True

        # Signal modules
        self.orderflow_signals = OrderFlowSignals(config)
        self.momentum_signals = MomentumSignals(config)
        self.volume_signals = VolumeSignals(config)
        self.trend_signals = TrendSignals(config)
        self.level_signals = LevelSignals(config)
        self.confluence_engine = ConfluenceEngine(config)

        # Alert modules
        self.discord_alerter = DiscordAlerter(config)
        self.journal = SignalJournal(config)

        # Learning
        self.learner = SignalLearner()
        self.confluence_engine.set_weights(self.learner.get_weights())

        # Market discovery
        self.market_scanner = MarketScanner()

        # Data storage
        self.crypto_data = {}
        self.equity_data = {}

        # Stats
        self.signals_generated_today = 0
        self.last_retraining = datetime.utcnow()

        logger.info("TradingSignalOrchestrator initialized")

    def is_market_hours(self) -> bool:
        """Check if current time is during US market hours (9:30-16:00 ET, Mon-Fri)."""
        now = datetime.now(ZoneInfo("US/Eastern"))
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute

        # Monday=0, Friday=4
        if weekday >= 5:
            return False

        market_open = hour * 60 + minute >= 9 * 60 + 30
        market_close = hour * 60 + minute <= 16 * 60

        return market_open and market_close

    async def evaluate_symbol(self, symbol: str, data: Dict, is_crypto: bool = False) -> Optional[Dict]:
        """
        Evaluate all signals for a symbol.
        Returns trade card if confluence meets threshold.
        REAL DATA ONLY - if data is missing/invalid, return None (skip symbol).
        """
        try:
            current_price = data.get("price", 0)
            if current_price <= 0:
                return None

            book_data = data.get("book", {})
            trades = data.get("trades", [])
            bars_dict = data.get("bars", {})
            atr = data.get("atr")

            # Evaluate all signal types
            orderflow = self.orderflow_signals.evaluate(symbol, book_data, trades)
            momentum = self.momentum_signals.evaluate(symbol, bars_dict.get("1hr"), data.get("vwap"))
            volume = self.volume_signals.evaluate(symbol, bars_dict.get("1hr"), trades)
            trend = self.trend_signals.evaluate(symbol, bars_dict)
            levels = self.level_signals.evaluate(symbol, bars_dict.get("1hr"), current_price)

            # Aggregate all signals
            all_signals = {
                "orderflow": orderflow,
                "momentum": momentum,
                "volume": volume,
                "trend": trend,
                "levels": levels
            }

            # Get confluences and generate trade card
            timeframe = "24/7" if is_crypto else "9:30-16:00 ET"
            trade_card = self.confluence_engine.evaluate(
                symbol,
                all_signals,
                current_price,
                atr,
                timeframe
            )

            if trade_card:
                logger.info(f"Signal generated: {symbol} {trade_card['direction']} @ {current_price}")
                return trade_card

            return None

        except Exception as e:
            logger.error(f"Error evaluating signals for {symbol}: {e}")
            return None

    async def process_trade_card(self, trade_card: Dict):
        """Process generated trade card: format and send alerts, log to journal."""
        try:
            # Format Discord embed
            embed = format_discord_embed(trade_card)

            if embed:
                # Send to Discord
                sent = await self.discord_alerter.send_alert(embed)
                if sent:
                    logger.info(f"Discord alert sent for {trade_card['symbol']}")

                # Log to journal
                await self.journal.log_signal(trade_card)

                # Record for learner
                await self.learner.record_signal(trade_card)

                self.signals_generated_today += 1

        except Exception as e:
            logger.error(f"Error processing trade card: {e}")

    async def market_discovery_task(self):
        """
        Refresh market targets every hour.
        Gets fresh symbols from API (most active, gainers, losers).
        """
        logger.info("Market discovery task started")

        while self.running:
            try:
                logger.info("Refreshing market targets...")
                targets = await self.market_scanner.get_scan_targets()
                logger.info(f"Discovery: {len(targets['equities'])} equities, {len(targets['crypto'])} crypto")
                await asyncio.sleep(3600)  # 1 hour

            except Exception as e:
                logger.error(f"Error in market discovery: {e}")
                await asyncio.sleep(300)  # retry in 5 min

    async def continuous_scan_task(self):
        """
        Continuously scan discovered symbols for qualified signals.
        Equities: every 60 seconds during market hours
        Crypto: every 30 seconds 24/7
        """
        logger.info("Continuous scan task started")

        while self.running:
            try:
                # Get current scan targets
                targets = await self.market_scanner.get_scan_targets()

                # Scan equities during market hours
                if self.is_market_hours():
                    equity_symbols = targets.get("equities", [])
                    logger.debug(f"Scanning {len(equity_symbols)} equities...")

                    for symbol in equity_symbols:
                        if symbol not in self.equity_data:
                            continue

                        data = self.equity_data[symbol]
                        trade_card = await self.evaluate_symbol(symbol, data, is_crypto=False)

                        if trade_card:
                            await self.process_trade_card(trade_card)

                # Scan crypto 24/7 (more frequently)
                crypto_symbols = targets.get("crypto", [])
                logger.debug(f"Scanning {len(crypto_symbols)} crypto...")

                for symbol in crypto_symbols:
                    if symbol not in self.crypto_data:
                        continue

                    data = self.crypto_data[symbol]
                    trade_card = await self.evaluate_symbol(symbol, data, is_crypto=True)

                    if trade_card:
                        await self.process_trade_card(trade_card)

                # Sleep based on asset type
                await asyncio.sleep(30)  # crypto frequency

            except Exception as e:
                logger.error(f"Error in continuous scan: {e}")
                await asyncio.sleep(5)

    async def outcome_check_task(self):
        """
        Check if open signals have hit TP or SL.
        Runs every 5 minutes to update learner with outcomes.
        """
        logger.info("Outcome check task started")

        while self.running:
            try:
                # Collect all current prices
                current_prices = {}
                for symbol, data in self.equity_data.items():
                    if "price" in data:
                        current_prices[symbol] = data["price"]
                for symbol, data in self.crypto_data.items():
                    if "price" in data:
                        current_prices[symbol] = data["price"]

                # Check outcomes
                if current_prices:
                    await self.learner.check_outcomes(current_prices)

                await asyncio.sleep(300)  # 5 minutes

            except Exception as e:
                logger.error(f"Error in outcome check: {e}")
                await asyncio.sleep(60)

    async def learner_retrain_task(self):
        """
        Retrain learner periodically.
        Runs every 24 hours or after 50 new signals.
        """
        logger.info("Learner retrain task started")

        while self.running:
            try:
                await asyncio.sleep(86400)  # 24 hours

                logger.info("Starting learner retraining...")
                await self.learner.retrain()

                # Update confluence engine with new weights
                self.confluence_engine.set_weights(self.learner.get_weights())

                self.last_retraining = datetime.utcnow()
                logger.info("Learner retraining complete")

            except Exception as e:
                logger.error(f"Error in learner retrain: {e}")
                await asyncio.sleep(3600)

    async def run(self):
        """
        Main orchestration: start all async tasks.
        """
        logger.info("Starting TradingSignalOrchestrator")

        tasks = [
            self.market_discovery_task(),
            self.continuous_scan_task(),
            self.outcome_check_task(),
            self.learner_retrain_task(),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Orchestrator tasks cancelled")
        except Exception as e:
            logger.error(f"Error in orchestrator: {e}")
        finally:
            self.running = False

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down orchestrator")
        self.running = False


def run_api_server():
    """Run FastAPI server in a separate thread."""
    try:
        from server import app
        logger.info("Starting FastAPI web server on 0.0.0.0:8080")
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
    except Exception as e:
        logger.error(f"Error running API server: {e}")


async def main():
    """Main entry point."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("Starting Order Flow Radar Trading Signal System")
    logger.info("Mode: REAL DATA ONLY - No mock data, no demo mode")

    # Load configuration
    config = load_config()

    # Initialize orchestrator
    orchestrator = TradingSignalOrchestrator(config)

    # Start FastAPI server in a background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    logger.info("API server thread started")

    # Setup signal handlers for graceful shutdown
    def handle_shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        orchestrator.shutdown()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Run orchestrator
    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        orchestrator.shutdown()
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        orchestrator.shutdown()

    logger.info("Order Flow Radar trading signal system stopped")


if __name__ == "__main__":
    asyncio.run(main())
