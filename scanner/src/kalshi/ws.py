"""
Kalshi WebSocket client — real-time market data streaming.

Derived from https://github.com/ryanfrigo/kalshi-ai-trading-bot (MIT).
Adapted for kalshi-ev-scanner: removed TradingLoggerMixin and EventBus
dependencies; callbacks are the sole dispatch mechanism.
"""

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

import websockets
import websockets.exceptions
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import structlog

from src.config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WS_PATH = "/trade-api/ws/v2"

CHANNEL_ORDERBOOK_DELTA = "orderbook_delta"
CHANNEL_TICKER = "ticker"
CHANNEL_TRADE = "trade"
CHANNEL_FILL = "fill"
ALL_CHANNELS = {CHANNEL_ORDERBOOK_DELTA, CHANNEL_TICKER, CHANNEL_TRADE, CHANNEL_FILL}

_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 60.0
_BACKOFF_MULTIPLIER = 2.0
_PING_INTERVAL_S = 10.0


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSING = "closing"


MessageCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class _SubscriptionState:
    tickers: Set[str] = field(default_factory=set)
    channels: Set[str] = field(default_factory=set)


class KalshiWebSocket:
    """
    Authenticated WebSocket client for Kalshi real-time market data.

    Features:
        * RSA PSS authentication matching the REST client.
        * Subscribe / unsubscribe to orderbook_delta, ticker, trade, fill.
        * Per-channel callback registration (on_ticker, on_orderbook, etc.).
        * Automatic reconnection with exponential backoff.
        * Periodic ping/pong keepalive (every 10 s).
        * Graceful shutdown via close().

    Example::

        ws = KalshiWebSocket()

        @ws.on_ticker
        async def handle_ticker(msg):
            print(msg)

        await ws.connect()
        await ws.subscribe(["AAPL-24"], [CHANNEL_TICKER])
        await ws.run()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
    ) -> None:
        self.api_key: str = api_key or settings.kalshi_key_id
        self.private_key_path: str = (
            private_key_path
            or os.environ.get("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem")
        )

        self._private_key: Any = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._should_run: bool = False
        self._msg_id_counter: int = 0
        self._sub_state = _SubscriptionState()

        self._callbacks: Dict[str, List[MessageCallback]] = {
            CHANNEL_TICKER: [],
            CHANNEL_ORDERBOOK_DELTA: [],
            CHANNEL_TRADE: [],
            CHANNEL_FILL: [],
        }

        self._load_private_key()

        log.info(
            "KalshiWebSocket initialized",
            api_key_length=len(self.api_key) if self.api_key else 0,
        )

    # ------------------------------------------------------------------
    # Key loading + signing
    # ------------------------------------------------------------------

    def _load_private_key(self) -> None:
        """Load RSA private key from file or inline PEM (settings.kalshi_private_key)."""
        inline_pem = getattr(settings, "kalshi_private_key", "")
        if inline_pem and inline_pem.strip():
            try:
                pem_bytes = inline_pem.encode() if isinstance(inline_pem, str) else inline_pem
                self._private_key = serialization.load_pem_private_key(pem_bytes, password=None)
                log.info("Private key loaded from settings for WebSocket auth")
                return
            except Exception as e:
                log.warning("Failed to load inline PEM, falling back to file", error=str(e))

        key_path = Path(self.private_key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"Private key file not found: {self.private_key_path}")
        with open(key_path, "rb") as f:
            self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        log.info("Private key loaded from file for WebSocket auth", path=str(key_path))

    def _sign(self, timestamp: str, method: str, path: str) -> str:
        message = (timestamp + method.upper() + path).encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _build_auth_headers(self) -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(timestamp, "GET", WS_PATH)
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    def _next_msg_id(self) -> int:
        self._msg_id_counter += 1
        return self._msg_id_counter

    async def connect(self) -> None:
        if self._state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            log.warning("connect() called but already connected/connecting")
            return

        self._state = ConnectionState.CONNECTING

        from urllib.parse import urlparse
        parsed = urlparse(settings.kalshi_api_base)
        host = f"{parsed.scheme}://{parsed.netloc}"
        ws_url = host.replace("https://", "wss://").replace("http://", "ws://") + WS_PATH
        headers = self._build_auth_headers()

        log.info("Connecting to Kalshi WebSocket", url=ws_url)
        try:
            self._ws = await websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=5,
            )
            self._state = ConnectionState.CONNECTED
            log.info("WebSocket connected")
        except Exception as exc:
            self._state = ConnectionState.DISCONNECTED
            log.error("WebSocket connection failed", error=str(exc))
            raise

    async def _reconnect(self) -> None:
        backoff = _INITIAL_BACKOFF_S
        self._state = ConnectionState.RECONNECTING

        while self._should_run:
            log.info("Attempting reconnect", backoff_s=backoff)
            try:
                await self.connect()
                if self._sub_state.tickers and self._sub_state.channels:
                    await self.subscribe(
                        list(self._sub_state.tickers),
                        list(self._sub_state.channels),
                    )
                log.info("Reconnected and resubscribed")
                return
            except Exception as exc:
                log.warning(
                    "Reconnect attempt failed",
                    error=str(exc),
                    next_backoff_s=min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S),
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)

        log.info("Reconnect loop exited (should_run=False)")

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        tickers: List[str],
        channels: Optional[List[str]] = None,
    ) -> None:
        if not self.is_connected:
            raise RuntimeError("Cannot subscribe: WebSocket is not connected")

        channels = channels or [CHANNEL_ORDERBOOK_DELTA, CHANNEL_TICKER]
        invalid = set(channels) - ALL_CHANNELS
        if invalid:
            raise ValueError(f"Invalid channels: {invalid}. Must be one of {ALL_CHANNELS}")

        msg = {
            "id": self._next_msg_id(),
            "cmd": "subscribe",
            "params": {
                "channels": channels,
                "market_tickers": tickers,
            },
        }
        await self._ws.send(json.dumps(msg))

        self._sub_state.tickers.update(tickers)
        self._sub_state.channels.update(channels)

        log.info("Subscribed", tickers=tickers, channels=channels)

    async def unsubscribe(self, tickers: List[str]) -> None:
        if not self.is_connected:
            log.warning("Cannot unsubscribe: not connected")
            return

        msg = {
            "id": self._next_msg_id(),
            "cmd": "unsubscribe",
            "params": {
                "channels": list(self._sub_state.channels),
                "market_tickers": tickers,
            },
        }
        await self._ws.send(json.dumps(msg))
        self._sub_state.tickers.difference_update(tickers)
        log.info("Unsubscribed", tickers=tickers)

    # ------------------------------------------------------------------
    # Callback registration (decorator-friendly)
    # ------------------------------------------------------------------

    def on_ticker(self, callback: MessageCallback) -> MessageCallback:
        self._callbacks[CHANNEL_TICKER].append(callback)
        return callback

    def on_orderbook(self, callback: MessageCallback) -> MessageCallback:
        self._callbacks[CHANNEL_ORDERBOOK_DELTA].append(callback)
        return callback

    def on_trade(self, callback: MessageCallback) -> MessageCallback:
        self._callbacks[CHANNEL_TRADE].append(callback)
        return callback

    def on_fill(self, callback: MessageCallback) -> MessageCallback:
        self._callbacks[CHANNEL_FILL].append(callback)
        return callback

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, raw: str) -> None:
        try:
            msg: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Received non-JSON message", raw=raw[:200])
            return

        msg_type = msg.get("type", "")

        channel_map: Dict[str, str] = {
            "ticker": CHANNEL_TICKER,
            "orderbook_delta": CHANNEL_ORDERBOOK_DELTA,
            "orderbook_snapshot": CHANNEL_ORDERBOOK_DELTA,
            "trade": CHANNEL_TRADE,
            "fill": CHANNEL_FILL,
        }

        channel = channel_map.get(msg_type)
        if channel is None:
            log.debug("Unhandled message type", msg_type=msg_type)
            return

        for cb in self._callbacks.get(channel, []):
            try:
                await cb(msg)
            except Exception:
                log.error("User callback error", channel=channel, exc_info=True)

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Block until close() is called; reconnects on unexpected drops."""
        if not self.is_connected:
            raise RuntimeError("Must call connect() before run()")

        self._should_run = True
        log.info("WebSocket event loop started")

        ping_task = asyncio.create_task(self._keepalive_loop())

        try:
            while self._should_run:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                    await self._dispatch(raw)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as exc:
                    if not self._should_run:
                        break
                    log.warning(
                        "WebSocket connection closed unexpectedly",
                        code=exc.code,
                        reason=exc.reason,
                    )
                    self._state = ConnectionState.DISCONNECTED
                    await self._reconnect()
                except Exception as exc:
                    if not self._should_run:
                        break
                    log.error("Unexpected error in event loop", error=str(exc), exc_info=True)
                    self._state = ConnectionState.DISCONNECTED
                    await self._reconnect()
        finally:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
            log.info("WebSocket event loop stopped")

    async def _keepalive_loop(self) -> None:
        while self._should_run:
            try:
                await asyncio.sleep(_PING_INTERVAL_S)
                if self._ws and self.is_connected:
                    await self._ws.ping()
                    log.debug("Keepalive ping sent")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Keepalive ping failed", error=str(exc))

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        log.info("Closing WebSocket connection")
        self._should_run = False
        self._state = ConnectionState.CLOSING

        if self._ws:
            try:
                await self._ws.close()
            except Exception as exc:
                log.warning("Error closing WebSocket", error=str(exc))

        self._state = ConnectionState.DISCONNECTED
        log.info("WebSocket connection closed")

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "KalshiWebSocket":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
