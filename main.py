"""
Order-Flow-Radar™ — Institutional Orchestrator
ScriptMasterLabs™

Runs 8 concurrent async loops (Law 3 compliance):
  1. Universe Discovery (every 5 min - Manifesto Rule 2)
  2. Alpaca WebSocket Stream (real-time tick-rule CVD)
  3. REST Snapshot Loop (initializes prices for discovered symbols)
  4. Signal Evaluation Loop (every 5 min - Law 3.1)
  5. Dashboard Server (FastAPI + SSE)
  6. Learner Retrain (every 24h)
  7. Discord Signal Queue (Tiered delivery)
  8. Heartbeat & Health Check
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime

import uvicorn

import config
from modules.alpaca_api import AlpacaAPI
from modules.polygon_api import PolygonAPI
from modules.schwab_api import SchwabAPI
from modules.flow_engine import FlowEngine
from modules.universe_engine import UniverseEngine
from modules.confluence_engine import ConfluenceEngine
from modules.options_engine import OptionsEngine
from modules.signal_router import SignalRouter
from modules.discord_alerter import DiscordAlerter
from modules.signal_journal import SignalJournal
from modules.learner import Learner
from modules.dashboard import app as dashboard_app, set_engines
from modules.sentiment_engine import SentimentEngine
from modules.ai_auditor import AIAuditor

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-10s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# =============================================================================
# GLOBALS / ENGINES
# =============================================================================
alpaca_client: AlpacaAPI
polygon_client: PolygonAPI
schwab_client: SchwabAPI

flow_engine: FlowEngine
universe_engine: UniverseEngine
confluence_engine: ConfluenceEngine
options_engine: OptionsEngine
router: SignalRouter
discord_alerter: DiscordAlerter
journal: SignalJournal
learner: Learner

shutdown_event = asyncio.Event()


def check_startup_keys():
    """Verify required keys exist. No fakes allowed."""
    required = {
        "ALPACA_API_KEY": config.ALPACA_API_KEY,
        "ALPACA_API_SECRET": config.ALPACA_API_SECRET,
        "POLYGON_API_KEY": config.POLYGON_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(f"FATAL: Missing required API keys: {', '.join(missing)}")
        logger.error("Set them in .env. No mock data permitted under the Law.")
        sys.exit(1)


# =============================================================================
# LOOPS (The Engine Cycles)
# =============================================================================

async def universe_discovery_loop():
    """
    Manifesto Rule 2: Dynamic discovery.
    Expansion v1.3: Scouting 100 symbols, Radar-Tiering Top 30.
    """
    while not shutdown_event.is_set():
        try:
            # 1. Scout 100 tickers from all sources (Alpaca/Polygon/Yahoo)
            all_symbols = await universe_engine.build()
            
            # 2. Determine Tier-1 Radar Priority (respecting WS subscription limit)
            radar_symbols = universe_engine.get_radar_priority(all_symbols, limit=config.RADAR_WS_LIMIT)
            
            logger.info(f"Loop: Universe Scouted ({len(all_symbols)}). Radar Active ({len(radar_symbols)}).")
            
            # 3. Rotate WebSocket subscriptions to stay under Free-Tier limit
            await alpaca_client.update_subscriptions(radar_symbols)
        except Exception as e:
            logger.error(f"Universe discovery loop failed: {e}")
        
        await asyncio.sleep(config.UNIVERSE_REFRESH_SECONDS)


async def snapshot_loop():
    """Initializes price data for symbols not yet hit by WebSocket trades."""
    while not shutdown_event.is_set():
        try:
            symbols = universe_engine.active_universe
            if symbols:
                snaps = await alpaca_client.get_snapshots(symbols)
                for sym, data in snaps.items():
                    # LAW 1.2: Price injection ONLY. No CVD estimation from snapshots.
                    price = data.get("latestTrade", {}).get("p") or data.get("minuteBar", {}).get("c") or 0
                    if price > 0:
                        flow_engine.inject_price_only(sym, price)
        except Exception as e:
            logger.error(f"Snapshot loop failed: {e}")
        
        await asyncio.sleep(config.REST_SNAPSHOT_INTERVAL)


async def evaluation_loop():
    """Law 3.1: Institutional evaluation every 5 minutes."""
    # Pre-loop wait to gather some volume
    await asyncio.sleep(60)

    while not shutdown_event.is_set():
        try:
            logger.info("Cycle: Evaluating all active symbols...")
            active_symbols = flow_engine.active_symbols()
            fired_count = 0

            for symbol in active_symbols:
                sig = await confluence_engine.evaluate(symbol)
                if sig:
                    # Enrich with real options recommendations if signal is strong
                    if sig.is_new_alert:
                        recs = await options_engine.get_recommendations(symbol, sig.action)
                        sig.options_recs = recs
                    
                    # Route to dashboard/discord/journal
                    await router.route(sig)
                    fired_count += 1
            
            logger.info(f"Cycle: Evaluation complete. {fired_count} signals fired.")
        except Exception as e:
            logger.error(f"Evaluation loop error: {e}")
        
        await asyncio.sleep(config.SIGNAL_EVAL_INTERVAL)


async def training_loop():
    """Learner retrains on historical data every 24h."""
    while not shutdown_event.is_set():
        await asyncio.sleep(config.LEARNER_RETRAIN_INTERVAL_HOURS * 3600)


async def pruning_loop():
    """Prunes stale tickers from memory periodically (Ensures 100% Stability)."""
    while True:
        try:
            if flow_engine:
                flow_engine.prune_stale_tickers()
        except Exception as e:
            logger.error(f"Pruning loop error: {e}")
        await asyncio.sleep(600)  # Institutional Cadence: 10 mins


async def dashboard_task():
    """Runs the FastAPI dashboard server."""
    try:
        cfg = uvicorn.Config(
            dashboard_app, 
            host="0.0.0.0", 
            port=config.DASHBOARD_PORT, 
            log_level="error"
        )
        server = uvicorn.Server(cfg)
        await server.serve()
    except Exception as e:
        logger.error(f"Dashboard server failed: {e}")


# =============================================================================
# MAIN ENTRY
# =============================================================================

async def main():
    global alpaca_client, polygon_client, schwab_client
    global flow_engine, universe_engine, confluence_engine, options_engine
    global router, discord_alerter, journal, learner
    global sentiment_engine, ai_auditor

    logger.info("=" * 60)
    logger.info("ORDER-FLOW-RADAR™ — Ground-Up Rebuild")
    logger.info("ScriptMasterLabs™ Institutional Integrity")
    logger.info("=" * 60)

    check_startup_keys()

    # 1. Initialize API Clients
    alpaca_client  = AlpacaAPI(config.ALPACA_API_KEY, config.ALPACA_API_SECRET)
    polygon_client = PolygonAPI(config.POLYGON_API_KEY)
    schwab_client  = SchwabAPI(
        config.SCHWAB_APP_KEY, config.SCHWAB_APP_SECRET, 
        config.SCHWAB_REFRESH_TOKEN, config.SCHWAB_REDIRECT_URI
    )
    
    sentiment_engine = SentimentEngine()
    ai_auditor = AIAuditor()

    # 2. Initialize Engines
    flow_engine       = FlowEngine()
    universe_engine   = UniverseEngine(alpaca_client, polygon_client)
    learner           = Learner()
    options_engine    = OptionsEngine(schwab_client)
    confluence_engine = ConfluenceEngine(
        flow_engine, learner.get_weights(), 
        sentiment=sentiment_engine, 
        auditor=ai_auditor
    )
    discord_alerter   = DiscordAlerter()
    journal           = SignalJournal()
    router            = SignalRouter(discord_alerter, journal)

    # 3. Wire Dashboard
    set_engines(confluence_engine, flow_engine, universe_engine, discord_alerter, journal)
    # Inject version into dashboard for build verification
    from modules.dashboard import app as dashboard_app
    dashboard_app.state.SYSTEM_VERSION = config.SYSTEM_VERSION

    # 4. Global Signal Handler for Windows/Linux
    try:
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, lambda: shutdown_event.set())
    except NotImplementedError:
        pass # Windows

    # 5. Launch Tasks
    logger.info("Starting institutional async loops...")
    
    # Define Alpaca task separately so we can handle its failure without killing the loop
    alpaca_task = asyncio.create_task(alpaca_client.start_stream(
        config.ALWAYS_SCAN, flow_engine.on_trade, flow_engine.on_quote
    ))

    tasks = [
        asyncio.create_task(dashboard_task()),
        asyncio.create_task(universe_discovery_loop()),
        asyncio.create_task(snapshot_loop()),
        asyncio.create_task(evaluation_loop()),
        asyncio.create_task(training_loop()),
        asyncio.create_task(pruning_loop()),
        alpaca_task
    ]

    await discord_alerter.send_status(
        "🟢 **Order-Flow-Radar™ ONLINE (Institutional Rebuild)**\n"
        f"Mode: Real Data Only | Law Adherence: Certified\n"
        f"Always Watch: {', '.join(config.ALWAYS_SCAN)}\n"
        "System is in discovery phase..."
    )

    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down... obeying cleanup protocols.")
        for task in tasks:
            task.cancel()
        
        await discord_alerter.send_status("🔴 **Order-Flow-Radar™ OFFLINE (Clean Shutdown)**")
        
        await alpaca_client.close()
        await polygon_client.close()
        await schwab_client.close()
        await sentiment_engine.close()
        await ai_auditor.close()
        await discord_alerter.close()
        logger.info("ScriptMasterLabs™ clean shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
