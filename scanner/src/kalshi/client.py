"""
Kalshi REST API client — authentication, market data, order execution.

Derived from https://github.com/ryanfrigo/kalshi-ai-trading-bot (MIT).
Adapted for kalshi-ev-scanner: removed TradingLoggerMixin/EventBus,
wired to our flat Settings schema, added structlog.
"""

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import structlog

from src.config import settings

log = structlog.get_logger(__name__)


class KalshiAPIError(Exception):
    """Raised when the Kalshi API returns an error or retries are exhausted."""


class KalshiClient:
    """
    Async Kalshi REST client with RSA PSS authentication and retry logic.

    Uses ``settings.kalshi_key_id`` and ``settings.kalshi_private_key`` (PEM
    string) or ``KALSHI_PRIVATE_KEY_PATH`` env var for auth.
    Base URL comes from ``settings.kalshi_api_base`` but we strip the path
    portion so we can control the full endpoint path ourselves.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        max_retries: int = 5,
        backoff_factor: float = 0.5,
    ) -> None:
        self.api_key = api_key or settings.kalshi_key_id
        # Derive base URL (scheme + host only, e.g. "https://demo-api.kalshi.co")
        raw_base = settings.kalshi_api_base
        # Strip any path after the host so we can build full endpoint paths
        from urllib.parse import urlparse
        parsed = urlparse(raw_base)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"

        self.private_key_path = (
            private_key_path
            or os.environ.get("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem")
        )
        self.private_key = None
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self._load_private_key()

        self.client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )

        log.info("Kalshi client initialized", api_key_length=len(self.api_key) if self.api_key else 0)

    # ------------------------------------------------------------------
    # Key loading + signing
    # ------------------------------------------------------------------

    def _load_private_key(self) -> None:
        """Load RSA private key from file or inline PEM (settings.kalshi_private_key)."""
        # Prefer inline PEM from settings if populated
        inline_pem = getattr(settings, "kalshi_private_key", "")
        if inline_pem and inline_pem.strip():
            try:
                pem_bytes = inline_pem.encode() if isinstance(inline_pem, str) else inline_pem
                self.private_key = serialization.load_pem_private_key(pem_bytes, password=None)
                log.info("Private key loaded from settings")
                return
            except Exception as e:
                log.warning("Failed to load inline PEM, falling back to file", error=str(e))

        key_path = Path(self.private_key_path)
        if not key_path.exists():
            raise KalshiAPIError(f"Private key file not found: {self.private_key_path}")
        try:
            with open(key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(f.read(), password=None)
            log.info("Private key loaded from file", path=str(key_path))
        except Exception as e:
            log.error("Failed to load private key", error=str(e))
            raise KalshiAPIError(f"Failed to load private key: {e}")

    def _sign_request(self, timestamp: str, method: str, path: str) -> str:
        """Return base64-encoded RSA PSS signature for the given request components."""
        message = (timestamp + method.upper() + path).encode("utf-8")
        try:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )
            return base64.b64encode(signature).decode("utf-8")
        except Exception as e:
            log.error("Failed to sign request", error=str(e))
            raise KalshiAPIError(f"Failed to sign request: {e}")

    # ------------------------------------------------------------------
    # Core request method
    # ------------------------------------------------------------------

    async def _make_authenticated_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        require_auth: bool = True,
    ) -> Dict[str, Any]:
        """
        Make an authenticated HTTP request with exponential-backoff retry.

        ``endpoint`` must start with '/' and be the full API path, e.g.
        ``/trade-api/v2/markets``.
        """
        url = f"{self.base_url}{endpoint}"
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if require_auth:
            timestamp = str(int(time.time() * 1000))
            signature = self._sign_request(timestamp, method, endpoint)
            headers.update(
                {
                    "KALSHI-ACCESS-KEY": self.api_key,
                    "KALSHI-ACCESS-TIMESTAMP": timestamp,
                    "KALSHI-ACCESS-SIGNATURE": signature,
                }
            )

        body = json.dumps(json_data, separators=(",", ":")) if json_data else None

        if params:
            url = f"{url}?{urlencode(params)}"

        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                log.debug(
                    "API request",
                    method=method,
                    endpoint=endpoint,
                    attempt=attempt + 1,
                )
                # 200 ms delay → ~5 req/s, avoids 429s
                await asyncio.sleep(0.2)

                response = await self.client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body,
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code == 429 or e.response.status_code >= 500:
                    sleep_time = self.backoff_factor * (2**attempt)
                    log.warning(
                        "Retryable API error",
                        status=e.response.status_code,
                        endpoint=endpoint,
                        attempt=attempt + 1,
                        retry_in=sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
                    log.error("Non-retryable API error", error=error_msg, endpoint=endpoint)
                    raise KalshiAPIError(error_msg)

            except Exception as e:
                last_exception = e
                sleep_time = self.backoff_factor * (2**attempt)
                log.warning("Request exception, retrying", error=str(e), endpoint=endpoint)
                await asyncio.sleep(sleep_time)

        raise KalshiAPIError(
            f"API request failed after {self.max_retries} retries: {last_exception}"
        )

    # ------------------------------------------------------------------
    # Portfolio endpoints
    # ------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, Any]:
        return await self._make_authenticated_request("GET", "/trade-api/v2/portfolio/balance")

    async def get_positions(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        params: Dict = {}
        if ticker:
            params["ticker"] = ticker
        return await self._make_authenticated_request(
            "GET", "/trade-api/v2/portfolio/positions", params=params
        )

    async def get_fills(self, ticker: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        params: Dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return await self._make_authenticated_request(
            "GET", "/trade-api/v2/portfolio/fills", params=params
        )

    async def get_orders(
        self, ticker: Optional[str] = None, status: Optional[str] = None
    ) -> Dict[str, Any]:
        params: Dict = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        return await self._make_authenticated_request(
            "GET", "/trade-api/v2/portfolio/orders", params=params
        )

    async def get_trades(
        self,
        ticker: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        return await self._make_authenticated_request(
            "GET", "/trade-api/v2/portfolio/trades", params=params
        )

    # ------------------------------------------------------------------
    # Market endpoints
    # ------------------------------------------------------------------

    async def get_markets(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        status: Optional[str] = None,
        tickers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        params: Dict = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            params["status"] = status
        if tickers:
            params["tickers"] = ",".join(tickers)
        return await self._make_authenticated_request(
            "GET", "/trade-api/v2/markets", params=params, require_auth=True
        )

    async def get_market(self, ticker: str) -> Dict[str, Any]:
        return await self._make_authenticated_request(
            "GET", f"/trade-api/v2/markets/{ticker}", require_auth=False
        )

    async def get_orderbook(self, ticker: str, depth: int = 100) -> Dict[str, Any]:
        return await self._make_authenticated_request(
            "GET",
            f"/trade-api/v2/markets/{ticker}/orderbook",
            params={"depth": depth},
            require_auth=False,
        )

    async def get_market_history(
        self,
        ticker: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        params: Dict = {"limit": limit}
        if start_ts:
            params["start_ts"] = start_ts
        if end_ts:
            params["end_ts"] = end_ts
        return await self._make_authenticated_request(
            "GET", f"/trade-api/v2/markets/{ticker}/history", params=params, require_auth=False
        )

    # ------------------------------------------------------------------
    # Order endpoints (Plan 3 will wire auto-bet; kept for completeness)
    # ------------------------------------------------------------------

    async def place_order(
        self,
        ticker: str,
        client_order_id: str,
        side: str,
        action: str,
        count: int,
        type_: str = "market",
        yes_price: Optional[int] = None,
        no_price: Optional[int] = None,
        expiration_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        order_data: Dict = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": side,
            "action": action,
            "count": count,
            "type": type_,
        }
        if yes_price is not None:
            order_data["yes_price"] = yes_price
        if no_price is not None:
            order_data["no_price"] = no_price
        if expiration_ts:
            order_data["expiration_ts"] = expiration_ts
        return await self._make_authenticated_request(
            "POST", "/trade-api/v2/portfolio/orders", json_data=order_data
        )

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return await self._make_authenticated_request(
            "DELETE", f"/trade-api/v2/portfolio/orders/{order_id}"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self.client.aclose()
        log.info("Kalshi client closed")

    async def __aenter__(self) -> "KalshiClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
