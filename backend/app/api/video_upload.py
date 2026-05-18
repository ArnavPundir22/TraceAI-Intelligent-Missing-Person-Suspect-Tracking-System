"""
TraceAI — Video Upload & Processing API
Upload recorded videos for batch forensic analysis
"""
import asyncio
import uuid
import cv2
import numpy as np
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import aiofiles

from app.config import settings
from app.models.database import get_db, AsyncSessionLocal, Camera, Detection, TimelineEvent, CameraStatus
from app.services.detection_service import detection_service
from app.services.embedding_service import embedding_service
from app.services.tracker_service import ByteTracker

router = APIRouter(prefix="/upload", tags=["Upload & Processing"])

# Track ongoing jobs
_processing_jobs: dict = {}


@router.post("/video", response_model=dict)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    camera_name: str = Form("Uploaded Video"),
    location: str = Form("Unknown"),
    zone: str = Form("General"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a video file for forensic analysis.
    Processing runs in the background.
    Returns a job_id to poll for status.
    """
    ext = Path(file.filename).suffix or ".mp4"
    job_id = uuid.uuid4().hex[:10]
    save_path = settings.UPLOAD_DIR / f"upload_{job_id}{ext}"

    # Stream to disk
    async with aiofiles.open(save_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            await f.write(chunk)

    # Create a virtual camera record
    cam = Camera(
        name=camera_name,
        location=location,
        zone=zone,
        stream_url=str(save_path),
        status=CameraStatus.INACTIVE,
    )
    db.add(cam)
    await db.commit()
    await db.refresh(cam)

    # Kick off background processing
    _processing_jobs[job_id] = {
        "status": "queued",
        "camera_id": cam.id,
        "progress": 0,
        "total_frames": 0,
        "processed_frames": 0,
        "detections": 0,
        "started_at": datetime.utcnow().isoformat(),
    }
    background_tasks.add_task(
        _process_video_background, job_id, cam.id, str(save_path)
    )

    return {
        "job_id": job_id,
        "camera_id": cam.id,
        "status": "queued",
        "message": f"Video '{file.filename}' uploaded. Processing started.",
    }


@router.get("/jobs/{job_id}", response_model=dict)
async def get_job_status(job_id: str):
    job = _processing_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


@router.get("/jobs", response_model=dict)
async def list_jobs():
    return {"jobs": list(_processing_jobs.values())}


# ---------------------------------------------------------------------------
# Background Processing
# ---------------------------------------------------------------------------
async def _process_video_background(job_id: str, camera_id: int, video_path: str):
    """
    Full forensic video analysis pipeline:
    Detection → Tracking → Embedding → Identity Matching → DB Recording
    """
    job = _processing_jobs[job_id]
    job["status"] = "processing"

    try:
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        job["total_frames"] = total_frames

        tracker = ByteTracker()
        all_embeddings = await asyncio.get_event_loop().run_in_executor(
            None, embedding_service.load_all_embeddings
        )

        frame_idx = 0
        detection_count = 0

        while True:
            ret, frame = await asyncio.get_event_loop().run_in_executor(None, cap.read)
            if not ret:
                break

            frame_idx += 1
            # Sample every FRAME_SKIP frames
            if frame_idx % settings.FRAME_SKIP != 0:
                continue

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detections = await detection_service.detect_persons(frame_rgb)
            tracks = tracker.update(detections)

            for track in tracks:
                bbox = track.bbox
                x1, y1 = max(0, int(bbox[0])), max(0, int(bbox[1]))
                x2, y2 = min(frame_rgb.shape[1], int(bbox[2])), min(frame_rgb.shape[0], int(bbox[3]))
                if x2 <= x1 or y2 <= y1:
                    continue

                crop = frame_rgb[y1:y2, x1:x2]
                embedding = await embedding_service.get_embedding(crop)

                person_id = None
                reid_score = 0.0
                if embedding is not None and all_embeddings:
                    match = embedding_service.find_best_match(embedding, all_embeddings)
                    if match:
                        person_id, reid_score = match

                ts = _frame_to_timestamp(cap, frame_idx)

                async with AsyncSessionLocal() as db:
                    det = Detection(
                        person_id=person_id,
                        camera_id=camera_id,
                        track_id=track.track_id,
                        timestamp=ts,
                        bbox_x1=float(x1), bbox_y1=float(y1),
                        bbox_x2=float(x2), bbox_y2=float(y2),
                        face_confidence=float(track.confidence),
                        reid_confidence=float(reid_score),
                        face_embedding=embedding.tolist() if embedding is not None else None,
                    )
                    db.add(det)
                    await db.commit()

                detection_count += 1

            job["processed_frames"] = frame_idx
            job["progress"] = int((frame_idx / max(total_frames, 1)) * 100)
            job["detections"] = detection_count

            # Yield to event loop
            await asyncio.sleep(0)

        cap.release()
        job["status"] = "completed"
        job["completed_at"] = datetime.utcnow().isoformat()

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)


def _frame_to_timestamp(cap, frame_idx: int) -> datetime:
    """Estimate wall clock time from frame position (relative to now)."""
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    seconds_offset = frame_idx / fps
    from datetime import timedelta
    return datetime.utcnow() - timedelta(seconds=seconds_offset)
