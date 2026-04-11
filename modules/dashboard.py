"""
Web Dashboard — FastAPI server with Server-Sent Events (SSE).
Live streaming: signals, flow metrics, options recs update continuously.
No page refresh needed. Data pushes to browser in real time.

CRITICAL: Dashboard loads IMMEDIATELY with system status.
User NEVER waits for full ticker gathering before seeing data.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("dashboard")

app = FastAPI(title="Order-Flow-Radar™", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# These get set by main.py at startup
_confluence_engine = None
_flow_engine = None
_universe_scanner = None
_discord_alerter = None
_alpaca_api = None
_signal_queue: asyncio.Queue = asyncio.Queue()
_startup_time = time.time()
_api_status = {
    "alpaca_ws": False,
    "schwab": False,
    "polygon": False,
    "discord": False,
}
_system_log: list = []


def set_engines(confluence, flow, universe, discord=None, alpaca=None):
    global _confluence_engine, _flow_engine, _universe_scanner, _discord_alerter, _alpaca_api
    _confluence_engine = confluence
    _flow_engine = flow
    _universe_scanner = universe
    _discord_alerter = discord
    _alpaca_api = alpaca


def set_api_status(key: str, value: bool):
    global _api_status
    _api_status[key] = value


def add_system_log(msg: str):
    """Add a server-side log entry that the dashboard can display."""
    _system_log.append({"ts": datetime.now().strftime("%H:%M:%S"), "msg": msg})
    if len(_system_log) > 200:
        del _system_log[:50]


async def push_signal(signal_data: dict):
    """Called by main loop when a new signal fires."""
    await _signal_queue.put(signal_data)


DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dashboard', 'index.html')

@app.get('/', response_class=HTMLResponse)
async def index():
    if os.path.exists(DASHBOARD_PATH):
        with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
            return HTMLResponse(f.read())
    return HTMLResponse('Dashboard HTML not found.')


@app.get("/api/status")
async def get_status():
    """Full system status — always returns data immediately."""
    uptime = int(time.time() - _startup_time)
    universe_count = 0
    universe_tickers = []
    if _universe_scanner:
        universe_tickers = getattr(_universe_scanner, 'active_universe', [])
        universe_count = len(universe_tickers)

    flow_count = 0
    if _flow_engine:
        flow_count = len(_flow_engine.states)

    signal_count = 0
    if _confluence_engine:
        signal_count = len(_confluence_engine.active_signals)

    return {
        "system": "Order-Flow-Radar™",
        "version": "1.0",
        "mode": "LIVE",
        "uptime_seconds": uptime,
        "uptime_display": f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "api_status": _api_status,
        "universe_count": universe_count,
        "universe_tickers": universe_tickers[:50],
        "flow_active": flow_count,
        "signals_active": signal_count,
        "system_log": _system_log[-30:],
    }


@app.get("/api/signals")
async def get_signals():
    """Current active signals."""
    if _confluence_engine:
        return _confluence_engine.get_active_signals()
    return []


@app.get("/api/history")
async def get_history():
    """Signal history."""
    if _confluence_engine:
        return _confluence_engine.get_history(100)
    return []


@app.get("/api/flow")
async def get_flow():
    """All flow states."""
    if _flow_engine:
        states = {}
        for sym, state in _flow_engine.states.items():
            states[sym] = _flow_engine.get_flow_score(sym)
        return states
    return {}


@app.get("/api/universe")
async def get_universe():
    """Current scan universe."""
    if _universe_scanner:
        return {"tickers": _universe_scanner.active_universe, "count": len(_universe_scanner.active_universe)}
    return {"tickers": [], "count": 0}


@app.get("/api/stream")
async def stream_signals(request: Request):
    """SSE endpoint — browser connects once, signals push continuously.
    Also pushes system status every 15s so dashboard is never stale."""

    async def event_generator():
        # Immediately push current system status on connect
        status = await get_status()
        yield f"event: status\ndata: {json.dumps(status)}\n\n"

        # Push any existing active signals immediately
        if _confluence_engine:
            active = _confluence_engine.get_active_signals()
            if active:
                for sig in active:
                    yield f"event: signal\ndata: {json.dumps(sig)}\n\n"

        status_counter = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                signal = await asyncio.wait_for(_signal_queue.get(), timeout=5.0)
                data = json.dumps(signal)
                yield f"event: signal\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                status_counter += 1
                if status_counter >= 3:  # Every ~15 seconds
                    status = await get_status()
                    yield f"event: status\ndata: {json.dumps(status)}\n\n"
                    status_counter = 0
                else:
                    yield f"event: ping\ndata: {datetime.now().isoformat()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
