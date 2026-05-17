"""
TraceAI — Video Stream Processor
Asynchronous frame ingestion pipeline:
  Frame Extraction → Detection → Face Embedding → Identity Matching → DB Recording
"""
import asyncio
import cv2
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime
from pathlib import Path
from loguru import logger
import uuid
import base64

from app.config import settings
from app.models.database import AsyncSessionLocal, Detection, TimelineEvent, Alert, Camera
from app.models.database import AlertSeverity, CameraStatus, WatchlistStatus
from app.services.detection_service import detection_service, DetectionBox
from app.services.embedding_service import embedding_service
from app.services.tracker_service import get_tracker
from app.core.websocket_manager import ws_manager
from sqlalchemy import select, update


class StreamProcessor:
    """
    Manages video stream ingestion for a single camera.
    Runs continuously in an asyncio task.
    """

    def __init__(self, camera_id: int, stream_url: str, zone: str = "Unknown"):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.zone = zone
        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self._task: Optional[asyncio.Task] = None
        self._embeddings_cache: List = []  # [(person_id, embedding), ...]
        self._last_embed_refresh = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info(f"[CAM-{self.camera_id}] Stream started → {self.stream_url}")
        await self._set_camera_status(CameraStatus.ACTIVE)

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"[CAM-{self.camera_id}] Stream stopped")
        await self._set_camera_status(CameraStatus.INACTIVE)

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------
    async def _process_loop(self):
        cap = cv2.VideoCapture(self.stream_url)
        if not cap.isOpened():
            logger.error(f"[CAM-{self.camera_id}] Cannot open stream: {self.stream_url}")
            await self._set_camera_status(CameraStatus.ERROR)
            return

        tracker = get_tracker(self.camera_id)
        frame_idx = 0
        t_prev = asyncio.get_event_loop().time()

        while self.running:
            ret, frame = await asyncio.get_event_loop().run_in_executor(
                None, cap.read
            )
            if not ret:
                logger.warning(f"[CAM-{self.camera_id}] Stream ended — retrying")
                await asyncio.sleep(2.0)
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop video file
                continue

            frame_idx += 1
            self.frame_count += 1

            # Adaptive frame skipping
            if frame_idx % settings.FRAME_SKIP != 0:
                await asyncio.sleep(0)
                continue

            # FPS calculation
            now = asyncio.get_event_loop().time()
            self.fps = settings.FRAME_SKIP / max(now - t_prev, 1e-6)
            t_prev = now

            # ---------- Pipeline ----------
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detections = await detection_service.detect_persons(frame_rgb)
            tracks = tracker.update(detections)

            await self._refresh_embeddings()

            det_records = []
            for track in tracks:
                det_record = await self._process_track(frame_rgb, track)
                if det_record:
                    det_records.append(det_record)

            # Send frame preview via WebSocket (JPEG thumbnail)
            await self._send_frame_preview(frame_rgb, tracks, det_records)

        cap.release()

    # ------------------------------------------------------------------
    # Track Processing
    # ------------------------------------------------------------------
    async def _process_track(self, frame: np.ndarray, track) -> Optional[dict]:
        """Crop, embed, match, and record a single track."""
        bbox = track.bbox
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]

        # Generate embedding
        embedding = await embedding_service.get_embedding(crop)
        if embedding is None:
            return None

        # Identity matching
        person_id = None
        reid_score = 0.0
        is_watchlist_hit = False

        if self._embeddings_cache:
            match = embedding_service.find_best_match(embedding, self._embeddings_cache)
            if match:
                person_id, reid_score = match
                # Check watchlist
                is_watchlist_hit = await self._is_watchlist(person_id)

        # Save snapshot
        snapshot_path = await self._save_snapshot(crop, person_id)

        # Record detection
        async with AsyncSessionLocal() as db:
            det = Detection(
                person_id=person_id,
                camera_id=self.camera_id,
                track_id=track.track_id,
                timestamp=datetime.utcnow(),
                bbox_x1=float(x1), bbox_y1=float(y1),
                bbox_x2=float(x2), bbox_y2=float(y2),
                face_confidence=float(track.confidence),
                reid_confidence=float(reid_score),
                face_embedding=embedding.tolist(),
                snapshot_path=str(snapshot_path) if snapshot_path else None,
                is_watchlist_hit=is_watchlist_hit,
            )
            db.add(det)
            await db.commit()

        # Fire alert for watchlist hit
        if is_watchlist_hit and person_id:
            await self._fire_watchlist_alert(person_id, snapshot_path)

        return {
            "track_id": track.track_id,
            "person_id": person_id,
            "bbox": [x1, y1, x2, y2],
            "reid_score": reid_score,
            "is_watchlist_hit": is_watchlist_hit,
            "snapshot": str(snapshot_path) if snapshot_path else None,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _refresh_embeddings(self):
        """Refresh in-memory embedding cache every 30s."""
        now = asyncio.get_event_loop().time()
        if now - self._last_embed_refresh > 30.0:
            self._embeddings_cache = await asyncio.get_event_loop().run_in_executor(
                None, embedding_service.load_all_embeddings
            )
            self._last_embed_refresh = now

    async def _is_watchlist(self, person_id: int) -> bool:
        async with AsyncSessionLocal() as db:
            from app.models.database import Person
            result = await db.execute(
                select(Person.watchlist_status).where(Person.id == person_id)
            )
            row = result.scalar_one_or_none()
            return row is not None and row != WatchlistStatus.NONE

    async def _save_snapshot(self, crop: np.ndarray, person_id: Optional[int]) -> Optional[Path]:
        try:
            fname = f"cam{self.camera_id}_{uuid.uuid4().hex[:8]}.jpg"
            path = settings.SNAPSHOTS_DIR / fname
            bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
            await asyncio.get_event_loop().run_in_executor(
                None, cv2.imwrite, str(path), bgr
            )
            return path
        except Exception as e:
            logger.error(f"Snapshot save error: {e}")
            return None

    async def _fire_watchlist_alert(self, person_id: int, snapshot_path: Optional[Path]):
        async with AsyncSessionLocal() as db:
            from app.models.database import Person
            result = await db.execute(select(Person).where(Person.id == person_id))
            person = result.scalar_one_or_none()
            if not person:
                return
            alert = Alert(
                person_id=person_id,
                camera_id=self.camera_id,
                severity=AlertSeverity.HIGH,
                title=f"Watchlist Match: {person.name}",
                message=(
                    f"{person.watchlist_status.value.upper()} — "
                    f"{person.name} detected at Camera {self.camera_id} ({self.zone})"
                ),
                snapshot_path=str(snapshot_path) if snapshot_path else None,
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)

        # Broadcast via WebSocket
        await ws_manager.broadcast({
            "type": "alert",
            "data": {
                "alert_id": alert.id,
                "person_id": person_id,
                "person_name": person.name,
                "camera_id": self.camera_id,
                "severity": "high",
                "message": alert.message,
            }
        })

    async def _send_frame_preview(self, frame: np.ndarray, tracks, records):
        """Send annotated frame thumbnail via WebSocket."""
        try:
            thumb = cv2.resize(frame, (640, 360))
            bgr = cv2.cvtColor(thumb, cv2.COLOR_RGB2BGR)
            # Draw boxes
            for track in tracks:
                bbox = track.bbox
                color = (0, 255, 80)
                cv2.rectangle(bgr,
                              (int(bbox[0] * 640 / frame.shape[1]),
                               int(bbox[1] * 360 / frame.shape[0])),
                              (int(bbox[2] * 640 / frame.shape[1]),
                               int(bbox[3] * 360 / frame.shape[0])),
                              color, 2)
            _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
            b64 = base64.b64encode(buf.tobytes()).decode()
            await ws_manager.broadcast({
                "type": "frame",
                "camera_id": self.camera_id,
                "fps": round(self.fps, 1),
                "detections": len(tracks),
                "frame_b64": b64,
            })
        except Exception as e:
            logger.debug(f"Frame preview error: {e}")

    async def _set_camera_status(self, status: CameraStatus):
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Camera).where(Camera.id == self.camera_id).values(status=status)
            )
            await db.commit()


# ---------------------------------------------------------------------------
# Stream Manager (multi-camera registry)
# ---------------------------------------------------------------------------
class StreamManager:
    def __init__(self):
        self._processors: Dict[int, StreamProcessor] = {}

    async def start_stream(self, camera_id: int, stream_url: str, zone: str = ""):
        if camera_id in self._processors:
            logger.warning(f"Stream {camera_id} already running")
            return
        proc = StreamProcessor(camera_id, stream_url, zone)
        self._processors[camera_id] = proc
        await proc.start()

    async def stop_stream(self, camera_id: int):
        if camera_id in self._processors:
            await self._processors[camera_id].stop()
            del self._processors[camera_id]

    async def stop_all(self):
        for camera_id in list(self._processors.keys()):
            await self.stop_stream(camera_id)

    def get_active_cameras(self) -> List[int]:
        return list(self._processors.keys())

    def get_stats(self, camera_id: int) -> dict:
        if camera_id in self._processors:
            p = self._processors[camera_id]
            return {"camera_id": camera_id, "fps": p.fps,
                    "frame_count": p.frame_count, "running": p.running}
        return {}


stream_manager = StreamManager()
