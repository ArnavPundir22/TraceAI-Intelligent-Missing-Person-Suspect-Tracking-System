"""
TraceAI — Camera Management API
CRUD + stream control + detection feed + heatmap data
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta

from app.models.database import get_db, Camera, Detection, HeatmapData
from app.models.database import CameraStatus
from app.models.schemas import (
    CameraCreate, CameraUpdate, CameraResponse,
    DetectionResponse, HeatmapPoint
)
from app.services.stream_processor import stream_manager

router = APIRouter(prefix="/cameras", tags=["Cameras"])


@router.get("/", response_model=List[CameraResponse])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).order_by(Camera.id))
    return result.scalars().all()


@router.post("/", response_model=CameraResponse, status_code=201)
async def add_camera(camera: CameraCreate, db: AsyncSession = Depends(get_db)):
    db_cam = Camera(**camera.model_dump())
    db.add(db_cam)
    await db.commit()
    await db.refresh(db_cam)
    return db_cam


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@router.put("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int, update_data: CameraUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    for k, v in update_data.model_dump(exclude_unset=True).items():
        setattr(cam, k, v)
    await db.commit()
    await db.refresh(cam)
    return cam


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    await stream_manager.stop_stream(camera_id)
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    await db.delete(cam)
    await db.commit()


# ---------------------------------------------------------------------------
# Stream Control
# ---------------------------------------------------------------------------
@router.post("/{camera_id}/start", response_model=dict)
async def start_stream(camera_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    if not cam.stream_url:
        raise HTTPException(400, "Camera has no stream URL configured")

    await stream_manager.start_stream(camera_id, cam.stream_url, cam.zone or "")
    return {"success": True, "camera_id": camera_id, "message": f"Stream {cam.name} started"}


@router.post("/{camera_id}/stop", response_model=dict)
async def stop_stream(camera_id: int):
    await stream_manager.stop_stream(camera_id)
    return {"success": True, "camera_id": camera_id, "message": "Stream stopped"}


@router.get("/{camera_id}/stats", response_model=dict)
async def stream_stats(camera_id: int):
    stats = stream_manager.get_stats(camera_id)
    return stats if stats else {"camera_id": camera_id, "running": False}


# ---------------------------------------------------------------------------
# Detection Feed
# ---------------------------------------------------------------------------
@router.get("/{camera_id}/detections", response_model=List[DetectionResponse])
async def get_detections(
    camera_id: int,
    hours: int = Query(24, le=168),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(Detection)
        .where(and_(Detection.camera_id == camera_id,
                    Detection.timestamp >= since))
        .order_by(Detection.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------
@router.get("/{camera_id}/heatmap", response_model=List[HeatmapPoint])
async def get_heatmap(
    camera_id: int,
    date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(HeatmapData).where(HeatmapData.camera_id == camera_id)
    if date:
        q = q.where(HeatmapData.date_bucket == date)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [HeatmapPoint(x=r.grid_x, y=r.grid_y, count=r.count) for r in rows]


@router.post("/{camera_id}/heatmap/update", response_model=dict)
async def update_heatmap(
    camera_id: int,
    points: List[HeatmapPoint],
    db: AsyncSession = Depends(get_db),
):
    """Ingest batch heatmap data from stream processor."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    hour = datetime.utcnow().hour
    for p in points:
        existing = await db.execute(
            select(HeatmapData).where(
                and_(HeatmapData.camera_id == camera_id,
                     HeatmapData.grid_x == p.x,
                     HeatmapData.grid_y == p.y,
                     HeatmapData.date_bucket == date_str)
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.count += p.count
        else:
            db.add(HeatmapData(
                camera_id=camera_id,
                grid_x=p.x, grid_y=p.y,
                count=p.count,
                hour_bucket=hour,
                date_bucket=date_str,
            ))
    await db.commit()
    return {"success": True, "points_updated": len(points)}
