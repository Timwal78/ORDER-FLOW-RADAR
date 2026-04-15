"""
Order Flow Radar™ — Dashboard Server
ScriptMasterLabs™

FastAPI server providing:
  - Real-time signal stream via SSE (Server-Sent Events)
  - REST endpoints for system state and recent history
  - No mock data. Values come directly from FlowEngine and Journal.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from sse_starlette.sse import EventSourceResponse

import config

logger = logging.getLogger("dashboard_server")

app = FastAPI(title="Order Flow Radar™")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from modules.alpaca_api import api_health

# Global instances (wired at startup)
_confluence = None
_flow = None
_universe = None
_discord = None
_journal = None

# SSE Signal Queue
_signal_queue = asyncio.Queue()

@app.get("/api/health")
async def get_health():
    # Return both API connectivity and the current Build Version
    return {
        "api": api_health,
        "version": getattr(app.state, "SYSTEM_VERSION", "v1.1-legacy")
    }


def set_engines(confluence, flow, universe, discord, journal):
    global _confluence, _flow, _universe, _discord, _journal
    _confluence = confluence
    _flow = flow
    _universe = universe
    _discord = discord
    _journal = journal


async def push_signal(sig: dict):
    """Push a signal to the SSE stream."""
    await _signal_queue.put(sig)


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("dashboard/index.html")


@app.get("/api/status")
async def get_status():
    return {
        "status": "ONLINE",
        "time": datetime.utcnow().isoformat(),
        "universe_count": _universe.symbol_count() if _universe else 0,
        "active_symbols": len(_flow.states) if _flow else 0,
    }


@app.get("/api/snapshot")
async def get_snapshot():
    """Real-time snapshot of symbols with active price data."""
    if not _flow:
        return []
    return _flow.snapshot()


@app.get("/api/signals/recent")
async def get_recent_signals():
    """Fetch recent signals from the journal."""
    if not _journal:
        return []
    return await _journal.get_recent_signals(limit=50)


@app.get("/api/stream")
async def signal_stream(request: Request):
    """SSE endpoint for real-time signal updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            
            try:
                sig = await asyncio.wait_for(_signal_queue.get(), timeout=1.0)
                yield {
                    "event": "signal",
                    "id": sig["fired_at"],
                    "data": json.dumps(sig)
                }
            except asyncio.TimeoutError:
                yield {
                    "event": "ping",
                    "data": "keep-alive"
                }

    import json
    return EventSourceResponse(event_generator())
