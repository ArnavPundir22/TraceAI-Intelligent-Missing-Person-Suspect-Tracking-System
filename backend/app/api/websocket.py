"""
TraceAI — WebSocket API Endpoint
Real-time bidirectional communication for dashboard updates.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.websocket_manager import ws_manager

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time event streaming.
    
    Messages sent from server:
    - type: "frame"      → Annotated camera frame thumbnail (base64 JPEG)
    - type: "alert"      → Watchlist match / security alert
    - type: "detection"  → New person detection event
    - type: "stats"      → Periodic stats update
    - type: "connected"  → Connection confirmation
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; receive client pings or commands
            data = await websocket.receive_text()
            # Echo back as acknowledgment (or handle client commands here)
            await websocket.send_text(f'{{"type":"ack","payload":{data}}}')
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
