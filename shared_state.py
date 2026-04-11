"""
Shared state between orchestrator (main.py) and server (server.py).
Thread-safe via the GIL for simple dict assignments.
"""

from datetime import datetime
from typing import Dict, List, Optional

# Live scan results published by the orchestrator
orchestrator_state = {
    "equity_signals": [],       # List of alert dicts (sweeps, whales, unusual vol)
    "crypto_signals": [],       # List of crypto alert dicts
    "trade_cards": [],          # Qualified confluence trade cards
    "scan_stats": {
        "equities_scanned": 0,
        "crypto_scanned": 0,
        "total_sweeps": 0,
        "total_whales": 0,
        "total_signals": 0,
        "last_scan_time": None,
    },
    "discovered_equities": [],
    "discovered_crypto": [],
}


def publish_scan_result(result_type: str, data: dict):
    """Called by orchestrator to publish a scan result."""
    data["timestamp"] = datetime.utcnow().isoformat()

    if result_type == "sweep":
        orchestrator_state["equity_signals"].append(data)
        orchestrator_state["scan_stats"]["total_sweeps"] += 1
        _trim_list(orchestrator_state["equity_signals"], 100)
    elif result_type == "whale":
        orchestrator_state["equity_signals"].append(data)
        orchestrator_state["scan_stats"]["total_whales"] += 1
        _trim_list(orchestrator_state["equity_signals"], 100)
    elif result_type == "unusual_volume":
        orchestrator_state["equity_signals"].append(data)
        _trim_list(orchestrator_state["equity_signals"], 100)
    elif result_type == "trade_card":
        orchestrator_state["trade_cards"].append(data)
        orchestrator_state["scan_stats"]["total_signals"] += 1
        _trim_list(orchestrator_state["trade_cards"], 50)
    elif result_type == "crypto_signal":
        orchestrator_state["crypto_signals"].append(data)
        _trim_list(orchestrator_state["crypto_signals"], 50)


def publish_scan_stats(equities_count: int, crypto_count: int):
    """Called by orchestrator after each scan cycle."""
    orchestrator_state["scan_stats"]["equities_scanned"] = equities_count
    orchestrator_state["scan_stats"]["crypto_scanned"] = crypto_count
    orchestrator_state["scan_stats"]["last_scan_time"] = datetime.utcnow().isoformat()


def publish_discovery(equities: list, crypto: list):
    """Called by orchestrator after symbol discovery."""
    orchestrator_state["discovered_equities"] = equities
    orchestrator_state["discovered_crypto"] = crypto


def get_live_signals(max_results: int = 50) -> List[Dict]:
    """Get all live signals (sweeps, whales, unusual vol) for dashboard."""
    all_signals = orchestrator_state["equity_signals"] + orchestrator_state["crypto_signals"]
    # Sort by timestamp descending (newest first)
    all_signals.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return all_signals[:max_results]


def get_trade_cards(max_results: int = 20) -> List[Dict]:
    """Get qualified trade cards for dashboard."""
    cards = orchestrator_state["trade_cards"]
    cards.sort(key=lambda x: x.get("score", 0), reverse=True)
    return cards[:max_results]


def _trim_list(lst: list, max_size: int):
    """Keep only the most recent items."""
    if len(lst) > max_size:
        del lst[:-max_size]
