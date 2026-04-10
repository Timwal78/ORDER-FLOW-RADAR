"""
Alpaca Crypto WebSocket Handler
Maintains real-time orderbook and trade data for crypto symbols via async WebSocket.
"""

import asyncio
import json
import logging
from collections import defaultdict, deque
from typing import Callable, Dict, List, Optional, Set

import websockets
from websockets.exceptions import WebSocketException

import config

logger = logging.getLogger(__name__)


class AlpacaCryptoHandler:
    """
    Async WebSocket handler for Alpaca crypto data streams.
    Maintains in-memory orderbook and trade deque for each symbol.
    """

    def __init__(self):
        self.api_key = config.ALPACA_API_KEY
        self.secret_key = config.ALPACA_SECRET_KEY
        self.ws_url = config.ALPACA_CRYPTO_WS
        self.symbols = config.CRYPTO_SYMBOLS

        # In-memory data storage
        self.orderbooks: Dict[str, Dict] = defaultdict(
            lambda: {"bids": {}, "asks": {}}
        )
        self.trades: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=5000)
        )
        self.midpoints: Dict[str, Optional[float]] = defaultdict(lambda: None)
        self.spreads_bps: Dict[str, Optional[float]] = defaultdict(lambda: None)

        # Websocket and connection management
        self.ws = None
        self.connected = False
        self.callbacks: List[Callable] = []
        self.backoff_seconds = 5
        self.max_backoff_seconds = 60

    def add_callback(self, callback: Callable) -> None:
        """Register a callback to fire on every data update."""
        self.callbacks.append(callback)

    async def start(self) -> None:
        """Start the WebSocket connection with exponential backoff on failure."""
        while True:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error(
                    f"Alpaca crypto connection error: {e}. "
                    f"Reconnecting in {self.backoff_seconds}s..."
                )
                await asyncio.sleep(self.backoff_seconds)
                # Exponential backoff: cap at max_backoff_seconds
                self.backoff_seconds = min(
                    self.backoff_seconds * 2, self.max_backoff_seconds
                )

    async def _connect_and_listen(self) -> None:
        """Connect to WebSocket and listen for messages."""
        async with websockets.connect(self.ws_url) as ws:
            self.ws = ws
            logger.info("Connected to Alpaca crypto stream")
            self.connected = True
            self.backoff_seconds = 5  # Reset backoff on successful connect

            # Send authentication
            auth_msg = {
                "action": "auth",
                "key": self.api_key,
                "secret": self.secret_key,
            }
            await ws.send(json.dumps(auth_msg))
            logger.debug("Sent auth message to Alpaca")

            # Subscribe to orderbook and trade channels
            for symbol in self.symbols:
                await self._subscribe(symbol)

            # Listen for messages
            async for message in ws:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse message: {e}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

    async def _subscribe(self, symbol: str) -> None:
        """Subscribe to orderbook and trade channels for a symbol."""
        channels = [f"orderbook.{symbol}", f"trades.{symbol}"]
        for channel in channels:
            sub_msg = {"action": "subscribe", "channels": [channel]}
            await self.ws.send(json.dumps(sub_msg))
            logger.debug(f"Subscribed to {channel}")
            await asyncio.sleep(0.1)  # Small delay between subscriptions

    async def _process_message(self, data: dict) -> None:
        """Process incoming WebSocket message (orderbook or trade)."""
        if "stream" not in data:
            return

        stream = data["stream"]

        if stream.startswith("orderbook."):
            symbol = stream.replace("orderbook.", "")
            await self._update_orderbook(symbol, data.get("data", {}))
        elif stream.startswith("trades."):
            symbol = stream.replace("trades.", "")
            await self._process_trade(symbol, data.get("data", {}))

        # Fire callbacks for subscribers
        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(stream)
                else:
                    callback(stream)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def _update_orderbook(self, symbol: str, orderbook_data: dict) -> None:
        """Update in-memory orderbook from Alpaca message."""
        try:
            bids = {
                float(price): float(size)
                for price, size in orderbook_data.get("bids", [])
            }
            asks = {
                float(price): float(size)
                for price, size in orderbook_data.get("asks", [])
            }

            self.orderbooks[symbol]["bids"] = bids
            self.orderbooks[symbol]["asks"] = asks

            # Update midpoint and spread
            if bids and asks:
                best_bid = max(bids.keys())
                best_ask = min(asks.keys())
                mid = (best_bid + best_ask) / 2
                self.midpoints[symbol] = mid

                spread_bps = ((best_ask - best_bid) / mid) * 10000
                self.spreads_bps[symbol] = spread_bps

        except Exception as e:
            logger.error(f"Error updating orderbook for {symbol}: {e}")

    async def _process_trade(self, symbol: str, trade_data: dict) -> None:
        """Process trade data and infer aggressor side."""
        try:
            price = float(trade_data.get("price", 0))
            size = float(trade_data.get("size", 0))
            timestamp = trade_data.get("timestamp", None)

            # Infer aggressor side by comparing to midpoint
            midpoint = self.midpoints.get(symbol)
            if midpoint is None:
                # Fall back to simple heuristic if no midpoint
                side = "buy" if price > 0 else "sell"
            else:
                side = "buy" if price > midpoint else "sell"

            trade_record = {
                "price": price,
                "size": size,
                "side": side,
                "timestamp": timestamp,
            }
            self.trades[symbol].append(trade_record)

        except Exception as e:
            logger.error(f"Error processing trade for {symbol}: {e}")

    def get_book(self, symbol: str) -> Dict:
        """Return current orderbook snapshot for symbol."""
        return self.orderbooks.get(symbol, {"bids": {}, "asks": {}})

    def get_trades(self, symbol: str, n: int = 100) -> List[Dict]:
        """Return last n trades for symbol."""
        trades = self.trades.get(symbol, deque())
        return list(trades)[-n:] if trades else []

    def get_spread_bps(self, symbol: str) -> Optional[float]:
        """Return bid-ask spread in basis points."""
        return self.spreads_bps.get(symbol)

    def get_mid(self, symbol: str) -> Optional[float]:
        """Return midpoint price (bid + ask) / 2."""
        return self.midpoints.get(symbol)

    def is_connected(self) -> bool:
        """Return whether WebSocket is currently connected."""
        return self.connected
