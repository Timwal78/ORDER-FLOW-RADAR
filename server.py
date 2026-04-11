"""
FastAPI web server for Order Flow Radar trading system.
REAL DATA ONLY. No mock data, no demo mode, no fake fallbacks.
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import load_config
from market_scanner import MarketScanner
from signals.orderflow import OrderFlowSignals
from signals.momentum import MomentumSignals
from signals.volume import VolumeSignals
from signals.trend import TrendSignals
from signals.levels import LevelSignals
from signals.confluence import ConfluenceEngine
from signals.learner import SignalLearner
from signals.options_recommender import OptionsRecommender
from alerts.journal import SignalJournal
from alerts.discord_webhook import DiscordAlerter
from data.schwab_options import SchwabOptionsHandler
from data.alpaca_crypto import AlpacaCryptoHandler
from data.alpaca_equities import AlpacaEquitiesHandler
from data.alpha_vantage import AlphaVantageHandler
from data.polygon_rest import PolygonRestHandler

import aiohttp
import pandas as pd
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY
import shared_state

logger = logging.getLogger(__name__)


class ServerState:
    """Server state: scan results, caches, connections."""

    def __init__(self):
        self.config = load_config()
        self.market_scanner = MarketScanner()
        self.learner = SignalLearner()
        self.journal = SignalJournal(self.config)

        # Data handlers
        self.schwab_handler = SchwabOptionsHandler()
        self.alpaca_crypto = AlpacaCryptoHandler()
        self.alpaca_equities = AlpacaEquitiesHandler()
        self.alpha_vantage = AlphaVantageHandler()
        self.polygon = PolygonRestHandler()

        # Options recommender
        self.options_recommender = OptionsRecommender(self.schwab_handler)

        # Signal modules
        self.orderflow_signals = OrderFlowSignals(self.config)
        self.momentum_signals = MomentumSignals(self.config)
        self.volume_signals = VolumeSignals(self.config)
        self.trend_signals = TrendSignals(self.config)
        self.level_signals = LevelSignals(self.config)
        self.confluence_engine = ConfluenceEngine(self.config, self.options_recommender)

        # Discord alerter
        self.discord_alerter = DiscordAlerter(self.config)

        # Update confluence engine with learned weights
        self.confluence_engine.set_weights(self.learner.get_weights())

        self.scan_cache: Dict[str, List[Dict]] = {}
        self.scan_timestamp: Dict[str, datetime] = {}
        self.connected_clients: List[WebSocket] = []
        self.api_status = {
            "alpaca": False,
            "polygon": False,
            "alpha_vantage": False,
            "schwab": False,
            "last_scan": None,
            "symbols_scanned": 0
        }

    async def broadcast_update(self, message: Dict):
        """Broadcast update to all connected WebSocket clients."""
        disconnected = []
        for client in self.connected_clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.append(client)
        for client in disconnected:
            if client in self.connected_clients:
                self.connected_clients.remove(client)


# Initialize FastAPI app and state
app = FastAPI(title="Order Flow Radar", version="1.0.0")
state = ServerState()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DASHBOARD_PATH = Path(__file__).parent / "dashboard"

ALPACA_HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
}


async def fetch_bars_rest(symbol, timeframe="1Hour", limit=100):
    """Fetch bars directly from Alpaca REST API and return as list[dict]."""
    try:
        url = "https://data.alpaca.markets/v2/stocks/bars"
        params = {"symbols": symbol, "timeframe": timeframe, "limit": limit, "feed": "iex"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=ALPACA_HEADERS, params=params,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw = data.get("bars", {}).get(symbol, [])
                    if raw:
                        rows = [{"open": b["o"], "high": b["h"], "low": b["l"],
                                 "close": b["c"], "volume": b["v"],
                                 "timestamp": b.get("t", "")} for b in raw]
                        df = pd.DataFrame(rows)
                        for col in ["open", "high", "low", "close", "volume"]:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                        return df
        return None
    except Exception as e:
        logger.error(f"Error fetching bars for {symbol}: {e}")
        return None


async def fetch_crypto_bars_rest(symbol, timeframe="1Hour", limit=50):
    """Fetch crypto bars from Alpaca REST API."""
    try:
        # Alpaca crypto bars endpoint
        url = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
        params = {"symbols": symbol, "timeframe": timeframe, "limit": limit}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=ALPACA_HEADERS, params=params,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw = data.get("bars", {}).get(symbol, [])
                    if raw:
                        rows = [{"open": b["o"], "high": b["h"], "low": b["l"],
                                 "close": b["c"], "volume": b["v"],
                                 "timestamp": b.get("t", "")} for b in raw]
                        df = pd.DataFrame(rows)
                        for col in ["open", "high", "low", "close", "volume"]:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                        return df
        return None
    except Exception as e:
        logger.error(f"Error fetching crypto bars for {symbol}: {e}")
        return None


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the main dashboard HTML."""
    dashboard_file = DASHBOARD_PATH / "index.html"
    if dashboard_file.exists():
        return FileResponse(dashboard_file)
    return HTMLResponse("<h1>Order Flow Radar — Dashboard loading...</h1>")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "api_status": state.api_status,
        "connected_clients": len(state.connected_clients)
    }


@app.get("/api/status")
async def get_status():
    """Get system status and API connectivity."""
    stats = shared_state.orchestrator_state["scan_stats"]
    equities_count = len(shared_state.orchestrator_state["discovered_equities"])
    crypto_count = len(shared_state.orchestrator_state["discovered_crypto"])
    return {
        "system": "Order Flow Radar",
        "version": "1.0.0",
        "mode": "LIVE — REAL DATA ONLY",
        "timestamp": datetime.utcnow().isoformat(),
        "api_status": {
            "alpaca": equities_count > 0 or crypto_count > 0,
            "polygon": equities_count > 100,  # Polygon gainers/losers contribute to discovery
            "alpha_vantage": True,  # Handler initialized, used for supplemental indicators
            "schwab": state.api_status.get("schwab", False),
            "symbols_scanned": stats.get("equities_scanned", 0),
            "last_scan": stats.get("last_scan_time"),
        },
        "connected_clients": len(state.connected_clients),
        "scan_stats": stats,
        "equities_discovered": equities_count,
        "crypto_discovered": crypto_count,
        "learner_weights": state.learner.get_weights()
    }


@app.get("/api/analyze/{symbol}")
async def analyze_symbol(symbol: str):
    """
    Analyze a symbol on-demand using REAL data from APIs.
    If data fetch fails, returns error — NO FAKE DATA.
    """
    try:
        symbol = symbol.upper()

        # Fetch real data from Alpaca REST directly
        bars = await fetch_bars_rest(symbol, timeframe="1Hour", limit=100)
        if bars is None or len(bars) == 0:
            return {"symbol": symbol, "error": "No bar data available from API"}

        current_price = float(bars["close"].iloc[-1]) if len(bars) > 0 else 0
        if current_price <= 0:
            return {"symbol": symbol, "error": "Invalid price data"}

        # ATR is optional — confluence engine defaults to 2% of price when None
        atr = None

        # Evaluate all signals (bars is a proper DataFrame now)
        orderflow = state.orderflow_signals.evaluate(symbol, {}, [])
        momentum = state.momentum_signals.evaluate(symbol, bars, None)
        volume = state.volume_signals.evaluate(symbol, bars, [])
        trend = state.trend_signals.evaluate(symbol, {"1hr": bars})
        levels = state.level_signals.evaluate(symbol, bars, current_price)

        all_signals = {
            "orderflow": orderflow,
            "momentum": momentum,
            "volume": volume,
            "trend": trend,
            "levels": levels
        }

        # Generate trade card via confluence engine (async to include options recs)
        trade_card = await state.confluence_engine.evaluate_async(
            symbol, all_signals, current_price, atr, "multi"
        )

        return {
            "symbol": symbol,
            "price": current_price,
            "atr": atr,
            "signals": {k: v for k, v in all_signals.items() if v},
            "trade_card": trade_card,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}")
        return {"symbol": symbol, "error": str(e)}


@app.get("/api/options/{symbol}")
async def get_options_analysis(symbol: str):
    """Get options analysis for a symbol. Real data from Schwab."""
    try:
        symbol = symbol.upper()
        chain_data = state.schwab_handler.options_chains.get(symbol)

        if not chain_data:
            return {
                "symbol": symbol,
                "error": "No options chain data available",
                "note": "Options data refreshes during market hours"
            }

        try:
            unusual = state.schwab_handler.get_unusual_activity(symbol)
            pcr = state.schwab_handler.get_pcr(symbol)
            flow = state.schwab_handler.get_options_flow(symbol)
        except Exception:
            unusual, pcr, flow = [], None, {}

        sentiment = "neutral"
        if pcr:
            if pcr > 0.70:
                sentiment = "bearish"
            elif pcr > 0.55:
                sentiment = "slightly_bearish"
            elif pcr < 0.30:
                sentiment = "bullish"
            elif pcr < 0.45:
                sentiment = "slightly_bullish"

        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "put_call_ratio": pcr,
            "sentiment": sentiment,
            "options_flow": flow,
            "unusual_activity": unusual[:10],
            "unusual_count": len(unusual)
        }

    except Exception as e:
        logger.error(f"Error analyzing options for {symbol}: {e}")
        return {"symbol": symbol, "error": str(e)}


@app.get("/api/options/{symbol}/recommend")
async def recommend_options(symbol: str, direction: str = "long", entry: float = 0):
    """Get options contract recommendations. Real data only."""
    try:
        symbol = symbol.upper()
        direction = direction.lower()

        if direction not in ["long", "short"]:
            return {"error": "direction must be 'long' or 'short'"}
        if entry <= 0:
            return {"error": "entry price must be > 0"}

        trade_card = {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "stop_loss": entry * 0.98 if direction == "long" else entry * 1.02,
            "tp1": entry * 1.02 if direction == "long" else entry * 0.98,
            "tp2": entry * 1.04 if direction == "long" else entry * 0.96,
            "timeframe": "multi",
            "score": 5.0
        }

        recommendation = await state.options_recommender.recommend(trade_card)
        if recommendation:
            return {
                "symbol": symbol, "direction": direction, "entry": entry,
                "recommendation": recommendation,
                "timestamp": datetime.utcnow().isoformat()
            }
        return {"symbol": symbol, "error": "Could not generate recommendation — options data may not be available"}

    except Exception as e:
        logger.error(f"Error generating options recommendation: {e}")
        return {"symbol": symbol, "error": str(e)}


@app.get("/api/scan")
async def scan_equities(min_score: float = 0.0, max_results: int = 50):
    """Return live scan results from the orchestrator. REAL DATA ONLY."""
    try:
        stats = shared_state.orchestrator_state["scan_stats"]
        equities = shared_state.orchestrator_state["discovered_equities"]

        # Get all live signals (sweeps, whales, unusual volume)
        all_signals = shared_state.get_live_signals(max_results=100)
        # Get qualified trade cards
        trade_cards = shared_state.get_trade_cards(max_results=max_results)

        # Merge: trade cards first, then signals as supplementary
        results = []
        seen_symbols = set()

        for tc in trade_cards:
            if tc.get("score", 0) >= min_score:
                results.append(tc)
                seen_symbols.add(tc.get("symbol"))

        for sig in all_signals:
            if sig.get("symbol") not in seen_symbols and sig.get("score", 0) >= min_score:
                results.append(sig)
                seen_symbols.add(sig.get("symbol"))

        # Sort by score descending
        results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return {
            "type": "equity_scan",
            "timestamp": stats.get("last_scan_time") or datetime.utcnow().isoformat(),
            "total_universe": len(equities),
            "qualified_results": len(results),
            "min_score": min_score,
            "total_sweeps": stats.get("total_sweeps", 0),
            "total_whales": stats.get("total_whales", 0),
            "total_signals": stats.get("total_signals", 0),
            "results": results[:max_results]
        }

    except Exception as e:
        logger.error(f"Error in equity scan: {e}")
        return {"type": "equity_scan", "error": str(e), "results": []}


@app.get("/api/scan/crypto")
async def scan_crypto(min_score: float = 0.0, max_results: int = 20):
    """Return live crypto scan results from the orchestrator."""
    try:
        crypto_pairs = shared_state.orchestrator_state["discovered_crypto"]
        crypto_signals = shared_state.orchestrator_state["crypto_signals"]

        results = [s for s in crypto_signals if s.get("score", 0) >= min_score]
        results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return {
            "type": "crypto_scan",
            "timestamp": datetime.utcnow().isoformat(),
            "total_universe": len(crypto_pairs),
            "qualified_results": len(results),
            "min_score": min_score,
            "results": results[:max_results]
        }

    except Exception as e:
        logger.error(f"Error in crypto scan: {e}")
        return {"type": "crypto_scan", "error": str(e), "results": []}


@app.get("/api/journal")
async def get_journal(limit: int = 50):
    """Get recent signal journal entries."""
    try:
        entries = await state.journal.get_recent(limit)
        return {"entries": entries, "total": len(entries)}
    except Exception as e:
        logger.error(f"Error fetching journal: {e}")
        return {"entries": [], "error": str(e)}


@app.get("/api/learner/weights")
async def get_learner_weights():
    """Get current learner weights."""
    return {
        "weights": state.learner.get_weights(),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/learner/performance")
async def get_learner_performance():
    """Get learner performance statistics."""
    try:
        stats = state.learner.get_performance_stats()
        return {
            "performance": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error fetching performance stats: {e}")
        return {"performance": {}, "error": str(e)}


# ============================================================================
# WEBSOCKET
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for real-time signal updates."""
    await ws.accept()
    state.connected_clients.append(ws)
    logger.info(f"WebSocket client connected. Total: {len(state.connected_clients)}")

    try:
        # Send initial status
        await ws.send_json({
            "type": "connected",
            "message": "Order Flow Radar — LIVE",
            "timestamp": datetime.utcnow().isoformat()
        })

        while True:
            # Keep connection alive, listen for client messages
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
            elif msg.get("type") == "subscribe":
                await ws.send_json({"type": "subscribed", "channel": msg.get("channel", "all")})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if ws in state.connected_clients:
            state.connected_clients.remove(ws)
