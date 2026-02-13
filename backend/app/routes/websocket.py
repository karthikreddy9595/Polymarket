"""WebSocket endpoints for real-time price streaming."""

import asyncio
import json
import logging
from typing import Dict, Set, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..polymarket_client import get_polymarket_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections and price subscriptions."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.subscriptions: Dict[WebSocket, Set[str]] = {}  # ws -> set of token_ids
        self._broadcast_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        self.subscriptions[websocket] = set()
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Handle WebSocket disconnection."""
        self.active_connections.discard(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def subscribe(self, websocket: WebSocket, token_ids: list) -> None:
        """Subscribe a WebSocket to token price updates."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(token_ids)
            logger.debug(f"WebSocket subscribed to {len(token_ids)} tokens")

    async def unsubscribe(self, websocket: WebSocket, token_ids: list) -> None:
        """Unsubscribe a WebSocket from token price updates."""
        if websocket in self.subscriptions:
            for token_id in token_ids:
                self.subscriptions[websocket].discard(token_id)

    async def broadcast_prices(self) -> None:
        """Broadcast LIVE prices to all subscribed connections - NO CACHING."""
        if not self.active_connections:
            return

        client = await get_polymarket_client()

        for websocket in list(self.active_connections):
            try:
                # Get subscribed tokens for this connection
                subscribed = self.subscriptions.get(websocket, set())
                if not subscribed:
                    continue

                # Fetch LIVE prices for subscribed tokens
                prices_to_send = await client.live_prices.get_live_prices_batch(
                    list(subscribed)
                )

                if prices_to_send:
                    await websocket.send_json({
                        "type": "prices",
                        "data": prices_to_send
                    })

            except Exception as e:
                logger.debug(f"Error broadcasting to WebSocket: {e}")
                self.disconnect(websocket)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """
    WebSocket endpoint for real-time price streaming.

    Messages from client:
    - {"action": "subscribe", "token_ids": ["token1", "token2"]}
    - {"action": "unsubscribe", "token_ids": ["token1"]}

    Messages to client:
    - {"type": "prices", "data": {"token_id": price, ...}}
    - {"type": "connected", "message": "Connected to price stream"}
    """
    await manager.connect(websocket)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to price stream"
        })

        # Start background price broadcast for this connection
        broadcast_task = asyncio.create_task(_broadcast_loop(websocket))

        # Handle incoming messages
        while True:
            try:
                data = await websocket.receive_json()
                action = data.get("action")

                if action == "subscribe":
                    token_ids = data.get("token_ids", [])
                    await manager.subscribe(websocket, token_ids)
                    await websocket.send_json({
                        "type": "subscribed",
                        "token_ids": token_ids
                    })

                elif action == "unsubscribe":
                    token_ids = data.get("token_ids", [])
                    await manager.unsubscribe(websocket, token_ids)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "token_ids": token_ids
                    })

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        broadcast_task.cancel()
        manager.disconnect(websocket)


async def _broadcast_loop(websocket: WebSocket) -> None:
    """Continuously broadcast LIVE prices to a specific WebSocket - NO CACHING."""
    client = await get_polymarket_client()

    while True:
        try:
            subscribed = manager.subscriptions.get(websocket, set())
            if subscribed:
                # Fetch LIVE prices for all subscribed tokens
                prices_to_send = await client.live_prices.get_live_prices_batch(
                    list(subscribed)
                )

                if prices_to_send:
                    await websocket.send_json({
                        "type": "prices",
                        "data": prices_to_send
                    })
                    logger.debug(f"[WS] Sent live prices: {prices_to_send}")

            await asyncio.sleep(1.0)  # Fetch live prices every second

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Broadcast loop error: {e}")
            break
