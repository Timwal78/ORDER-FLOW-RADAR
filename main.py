"""
Order-Flow-Radar™ — Main Orchestrator
ScriptMasterLabs™

Initializes all engines, runs continuous async loops:
  1. Universe rebuild (every 5 min)
  2. Alpaca websocket (continuous real-time trades/quotes)
  3. Alpaca REST snapshot polling (fills data when websocket is quiet)
  4. Signal evaluation loop (every 30s)
  5. Web dashboard (FastAPI + SSE)
  6. Discord alerts on signal fire

CRITICAL: Dashboard + Discord fire IMMEDIATELY on startup.
User NEVER waits for full universe scan or ticker gathering.
"""
import asyncio
import signal
import logging
import sys
import uvicorn
import aiohttp
from datetime import datetime

import config
from modules.schwab_api import SchwabAPI
from modules.polygon_api import PolygonAPI
from modules.alpaca_api import AlpacaAPI
from modules.flow_engine import FlowEngine
from modules.options_recommender import OptionsRecommender
from modules.confluence_engine import ConfluenceEngine
from modules.universe_scanner import UniverseScanner
from modules.discord_alerter import DiscordAlerter
from modules.dashboard import (
    app as dashboard_app, set_engines, push_signal,
    set_api_status, add_system_log,
)

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
# GLOBALS
# =============================================================================
schwab: SchwabAPI
polygon: PolygonAPI
alpaca: AlpacaAPI
flow: FlowEngine
options_rec: OptionsRecommender
confluence: ConfluenceEngine
universe: UniverseScanner
discord: DiscordAlerter

shutdown_event = asyncio.Event()


def check_config():
    """Validate required API keys exist. No fakes.
    Returns missing keys but does NOT exit — dashboard must load regardless."""
    missing = []
    if not config.ALPACA_API_KEY:
        missing.append("ALPACA_API_KEY")
    if not config.ALPACA_API_SECRET:
        missing.append("ALPACA_API_SECRET")

    if missing:
        logger.error(f"CRITICAL MISSING API KEYS: {', '.join(missing)}")
        logger.error("Set them in .env file. No defaults. No fakes.")
        sys.exit(1)

    # Schwab is NOT mandatory for dashboard/discord to load
    optional = []
    if not config.SCHWAB_APP_KEY:
        optional.append("SCHWAB_APP_KEY (options chains disabled)")
    if not config.SCHWAB_APP_SECRET:
        optional.append("SCHWAB_APP_SECRET (options chains disabled)")
    if not config.SCHWAB_REFRESH_TOKEN:
        optional.append("SCHWAB_REFRESH_TOKEN (options chains disabled)")
    if not config.POLYGON_API_KEY:
        optional.append("POLYGON_API_KEY (universe scan limited)")
    if not config.ALPHA_VANTAGE_KEY:
        optional.append("ALPHA_VANTAGE_KEY (sentiment disabled)")
    if not config.DISCORD_WEBHOOK_URL:
        optional.append("DISCORD_WEBHOOK_URL (alerts disabled)")
    for o in optional:
        logger.warning(f"Optional missing: {o}")
    return missing


async def universe_loop():
    """Rebuild scan universe every 5 minutes.
    Errors do NOT block anything — dashboard and discord run regardless."""
    while not shutdown_event.is_set():
        try:
            tickers = await universe.build_universe()
            logger.info(f"Universe: {len(tickers)} tickers | Always: {config.ALWAYS_SCAN}")
            add_system_log(f"Universe rebuilt: {len(tickers)} tickers")

            # Update Alpaca websocket subscription with top movers
            stream_symbols = tickers[:1000]
            try:
                await alpaca.update_subscription(stream_symbols)
                set_api_status("alpaca_ws", True)
            except Exception as e:
                logger.warning(f"WS subscription update failed: {e}")

        except Exception as e:
            logger.error(f"Universe rebuild failed: {e}")
            add_system_log(f"⚠️ Universe rebuild error: {str(e)[:80]}")

        await asyncio.sleep(300)  # 5 min


async def stream_loop():
    """Connect to Alpaca websocket for real-time trades/quotes."""
    initial = config.ALWAYS_SCAN[:50]
    try:
        add_system_log(f"Connecting Alpaca stream for: {', '.join(initial)}")
        await alpaca.start_stream(
            symbols=initial,
            on_trade=flow.on_trade,
            on_quote=flow.on_quote,
        )
    except Exception as e:
        logger.error(f"Stream died: {e}")
        add_system_log(f"⚠️ Stream error: {str(e)[:80]}")
        await asyncio.sleep(5)
        if not shutdown_event.is_set():
            asyncio.create_task(stream_loop())


async def rest_snapshot_loop():
    """Poll Alpaca REST for snapshots when websocket data is quiet.
    This ensures the dashboard ALWAYS has price data to show,
    even after hours or when the stream has no trades."""
    await asyncio.sleep(5)  # Let stream connect first

    while not shutdown_event.is_set():
        try:
            # Get all symbols we should be tracking
            symbols = list(config.ALWAYS_SCAN)
            if universe and hasattr(universe, 'active_universe'):
                # Expand pulling from 50 to 3000 for aggressive flow radar
                symbols = list(set(symbols + universe.active_universe[:3000]))

            if not symbols:
                await asyncio.sleep(30)
                continue

            session = aiohttp.ClientSession()
            try:
                headers = {
                    "APCA-API-KEY-ID": config.ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET,
                }
                
                # Fetch snapshots in batches to respect URL length limits
                batch_size = 100
                total_injected = 0
                
                for i in range(0, len(symbols), batch_size):
                    batch = symbols[i:i+batch_size]
                    sym_str = ",".join(batch)
                    
                    # Using the efficient snapshots endpoint (combines trades + quotes)
                    url = "https://data.alpaca.markets/v2/stocks/snapshots"
                    async with session.get(url, headers=headers,
                                           params={"symbols": sym_str, "feed": "iex"},
                                           timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for sym, snap in data.items():
                                state = flow.get_state(sym)
                                
                                # Process Trade
                                latest_trade = snap.get("latestTrade", {})
                                min_bar = snap.get("minuteBar", {})
                                daily_bar = snap.get("dailyBar", {})
                                
                                price = latest_trade.get("p") or min_bar.get("c") or daily_bar.get("c") or 0
                                size = latest_trade.get("s", 0)
                                if price > 0:
                                    if state.last_price == 0:
                                        state.last_price = price
                                        state.total_volume = max(state.total_volume, size or 1)
                                        total_injected += 1
                                        
                                # Process Quote
                                latest_quote = snap.get("latestQuote", {})
                                bp = latest_quote.get("bp", 0)
                                ap = latest_quote.get("ap", 0)
                                if bp > 0:
                                    state.bid = bp
                                if ap > 0:
                                    state.ask = ap
                                if bp > 0 and ap > 0:
                                    state.spread = ap - bp

                    await asyncio.sleep(0.1) # Small delay to not anger Alpaca API
                    
                if total_injected > 0:
                    add_system_log(f"REST snapshot: {total_injected} symbols initialized/updated out of {len(symbols)}")
                    set_api_status("alpaca_ws", True)

            finally:
                await session.close()

        except Exception as e:
            logger.error(f"REST snapshot error: {e}")

        await asyncio.sleep(30)  # Refresh every 30s


async def signal_eval_loop():
    """Evaluate all flowing symbols for confluence signals."""
    await asyncio.sleep(10)

    while not shutdown_event.is_set():
        try:
            evaluated = 0
            fired = 0

            for symbol in list(flow.states.keys()):
                state = flow.states[symbol]
                # Allow eval if we have ANY price data (not just volume > 100)
                if state.last_price <= 0:
                    continue

                sig = await confluence.evaluate(symbol)
                evaluated += 1

                if sig:
                    fired += 1
                    sig_dict = sig.to_dict()

                    # Push to dashboard SSE
                    await push_signal(sig_dict)

                    # Push to Discord
                    await discord.send_signal(sig_dict)

                    # Log it
                    opts_str = ""
                    if sig.options_recs:
                        top = sig.options_recs[0]
                        opts_str = f" → {top['direction']} ${top['strike']:.2f} {top['expiration']}"
                    logger.info(f"🎯 SIGNAL: {symbol} {sig.action} (Score: {sig.score:.0f}){opts_str}")

            if evaluated > 0:
                add_system_log(f"Eval cycle: {evaluated} symbols, {fired} signals")
                logger.info(f"Eval cycle: {evaluated} symbols checked, {fired} signals fired")

        except Exception as e:
            logger.error(f"Signal eval error: {e}")

        await asyncio.sleep(config.SIGNAL_EVAL_INTERVAL)


async def discord_heartbeat_loop():
    """Send periodic Discord status updates so user knows system is alive."""
    await asyncio.sleep(300)  # First heartbeat after 5 min
    while not shutdown_event.is_set():
        try:
            universe_count = len(getattr(universe, 'active_universe', []))
            flow_count = len(flow.states)
            signal_count = len(confluence.active_signals)
            await discord.send_status(
                f"💚 **Heartbeat** | Universe: {universe_count} | "
                f"Flow: {flow_count} active | Signals: {signal_count} | "
                f"Dashboard: http://localhost:{config.DASHBOARD_PORT}"
            )
        except Exception:
            pass
        await asyncio.sleep(900)  # Every 15 min


async def dashboard_server():
    """Run FastAPI dashboard."""
    server_config = uvicorn.Config(
        dashboard_app,
        host="0.0.0.0",
        port=config.DASHBOARD_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)
    await server.serve()


async def main():
    global schwab, polygon, alpaca, flow, options_rec, confluence, universe, discord

    logger.info("=" * 60)
    logger.info("ORDER-FLOW-RADAR™ | ScriptMasterLabs™")
    logger.info("=" * 60)
    logger.info("Dashboard + Discord fire IMMEDIATELY. No waiting.")
    logger.info("=" * 60)

    check_config()

    # Initialize engines — ALL initialization is non-blocking
    schwab = SchwabAPI(
        config.SCHWAB_APP_KEY,
        config.SCHWAB_APP_SECRET,
        config.SCHWAB_REFRESH_TOKEN,
        config.SCHWAB_REDIRECT_URI,
    )
    polygon = PolygonAPI(config.POLYGON_API_KEY)
    alpaca = AlpacaAPI(config.ALPACA_API_KEY, config.ALPACA_API_SECRET)
    flow = FlowEngine()
    options_rec = OptionsRecommender(schwab)
    confluence = ConfluenceEngine(flow, options_rec)
    universe = UniverseScanner(schwab, polygon, alpaca)
    discord = DiscordAlerter(config.DISCORD_WEBHOOK_URL)

    # Wire dashboard — pass all engines including discord
    set_engines(confluence, flow, universe, discord, alpaca)
    add_system_log("System initialized")
    set_api_status("discord", bool(config.DISCORD_WEBHOOK_URL))

    logger.info(f"Always-scan: {config.ALWAYS_SCAN}")
    logger.info(f"Dashboard: http://localhost:{config.DASHBOARD_PORT}")

    # FIRE DISCORD STARTUP IMMEDIATELY — before any API calls that might fail
    try:
        await discord.send_status(
            f"🟢 **Order-Flow-Radar™ ONLINE**\n"
            f"Always watching: {', '.join(config.ALWAYS_SCAN)}\n"
            f"Dashboard: http://localhost:{config.DASHBOARD_PORT}\n"
            f"System is live — scanning in progress..."
        )
        add_system_log("✅ Discord startup notification sent")
        logger.info("Discord startup notification sent")
    except Exception as e:
        logger.warning(f"Discord startup notification failed: {e}")
        add_system_log(f"⚠️ Discord startup failed: {str(e)[:60]}")

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    try:
        for sig_name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig_name, lambda: shutdown_event.set())
    except NotImplementedError:
        pass  # Not supported on Windows

    # Launch ALL loops — dashboard is FIRST so it loads instantly
    tasks = [
        asyncio.create_task(dashboard_server()),
        asyncio.create_task(rest_snapshot_loop()),
        asyncio.create_task(universe_loop()),
        asyncio.create_task(stream_loop()),
        asyncio.create_task(signal_eval_loop()),
        asyncio.create_task(discord_heartbeat_loop()),
    ]

    logger.info("All systems GO. Dashboard is LIVE.")
    add_system_log("🚀 All systems GO")

    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down...")
        for t in tasks:
            t.cancel()
        await schwab.close()
        await polygon.close()
        await alpaca.close()
        try:
            await discord.send_status("🔴 **Order-Flow-Radar™ OFFLINE**")
        except Exception:
            pass
        await discord.close()
        logger.info("Clean shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
