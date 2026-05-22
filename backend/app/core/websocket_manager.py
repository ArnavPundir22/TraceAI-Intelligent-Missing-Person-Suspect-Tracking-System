"""
TraceAI — WebSocket Connection Manager
Manages real-time bidirectional communication with the dashboard.
"""
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set, Dict, Any
from loguru import logger
import json
from datetime import datetime


class ConnectionManager:
    """
    Manages a pool of active WebSocket connections.
    Supports both broadcast and targeted messaging.
    """

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info(f"WS connected | total={len(self._connections)}")
        # Send welcome message
        await self._send_to(websocket, {
            "type": "connected",
            "message": "TraceAI WebSocket connection established",
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)
        logger.info(f"WS disconnected | total={len(self._connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Send message to all connected clients."""
        if not self._connections:
            return
        payload = json.dumps(message, default=str)
        dead = set()
        for ws in list(self._connections):
            try:
                await ws.se/nd_text(payload)
            except Exception:
                dead.add(ws)
        async with self._lock:
            self._connections -= dead

    async def _send_to(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.debug(f"WS send error: {e}")

    @property
    def connection_count(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()
