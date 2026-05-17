"""
TraceAI — Analytics API
Dashboard stats, heatmaps, movement analytics, system metrics
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from datetime import datetime, timedelta

from app.models.database import (
    get_db, Person, Camera, Detection, Alert, TimelineEvent,
    WatchlistStatus, CameraStatus, AlertSeverity
)
from app.models.schemas import DashboardStats

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Primary dashboard statistics — called on page load."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    last_hour = datetime.utcnow() - timedelta(hours=1)

    total_persons = (await db.execute(
        select(func.count()).select_from(Person).where(Person.is_active == True)
    )).scalar()

    watchlisted = (await db.execute(
        select(func.count()).select_from(Person)
        .where(and_(Person.is_active == True,
                    Person.watchlist_status != WatchlistStatus.NONE))
    )).scalar()

    missing = (await db.execute(
        select(func.count()).select_from(Person)
        .where(and_(Person.is_active == True,
                    Person.watchlist_status == WatchlistStatus.MISSING))
    )).scalar()

    suspects = (await db.execute(
        select(func.count()).select_from(Person)
        .where(and_(Person.is_active == True,
                    Person.watchlist_status == WatchlistStatus.SUSPECT))
    )).scalar()

    active_cams = (await db.execute(
        select(func.count()).select_from(Camera)
        .where(Camera.status == CameraStatus.ACTIVE)
    )).scalar()

    total_cams = (await db.execute(
        select(func.count()).select_from(Camera)
    )).scalar()

    alerts_today = (await db.execute(
        select(func.count()).select_from(Alert)
        .where(Alert.triggered_at >= today)
    )).scalar()

    unack_alerts = (await db.execute(
        select(func.count()).select_from(Alert)
        .where(Alert.is_acknowledged == False)
    )).scalar()

    dets_today = (await db.execute(
        select(func.count()).select_from(Detection)
        .where(Detection.timestamp >= today)
    )).scalar()

    dets_last_hour = (await db.execute(
        select(func.count()).select_from(Detection)
        .where(Detection.timestamp >= last_hour)
    )).scalar()

    return DashboardStats(
        total_persons=total_persons or 0,
        watchlisted_persons=watchlisted or 0,
        missing_persons=missing or 0,
        suspects=suspects or 0,
        active_cameras=active_cams or 0,
        total_cameras=total_cams or 0,
        alerts_today=alerts_today or 0,
        unacknowledged_alerts=unack_alerts or 0,
        detections_today=dets_today or 0,
        detections_last_hour=dets_last_hour or 0,
    )


@router.get("/detections/timeline")
async def detection_timeline(
    hours: int = Query(24, le=168),
    granularity: str = Query("hour", pattern="^(hour|day)$"),
    db: AsyncSession = Depends(get_db),
):
    """Detection count bucketed by hour/day for chart rendering."""
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(Detection.timestamp, Detection.camera_id, Detection.person_id)
        .where(Detection.timestamp >= since)
        .order_by(Detection.timestamp.asc())
    )
    rows = result.fetchall()

    # Bucket by hour
    buckets: dict = {}
    for ts, cam_id, person_id in rows:
        if granularity == "hour":
            key = ts.strftime("%Y-%m-%dT%H:00")
        else:
            key = ts.strftime("%Y-%m-%d")
        buckets[key] = buckets.get(key, 0) + 1

    return [{"time": k, "count": v} for k, v in sorted(buckets.items())]


@router.get("/watchlist/activity")
async def watchlist_activity(
    days: int = Query(7, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Recent detection activity for watchlisted persons."""
    since = datetime.utcnow() - timedelta(days=days)

    # Get watchlisted persons
    wp = await db.execute(
        select(Person).where(
            and_(Person.is_active == True,
                 Person.watchlist_status != WatchlistStatus.NONE)
        )
    )
    watchlisted = wp.scalars().all()

    activity = []
    for person in watchlisted:
        last_det = await db.execute(
            select(Detection)
            .where(and_(Detection.person_id == person.id,
                        Detection.timestamp >= since))
            .order_by(Detection.timestamp.desc())
            .limit(1)
        )
        det = last_det.scalar_one_or_none()

        count_r = await db.execute(
            select(func.count()).select_from(Detection)
            .where(and_(Detection.person_id == person.id,
                        Detection.timestamp >= since))
        )
        count = count_r.scalar() or 0

        cam_name = None
        if det:
            cam_r = await db.execute(
                select(Camera.name).where(Camera.id == det.camera_id)
            )
            cam_name = cam_r.scalar_one_or_none()

        activity.append({
            "person_id": person.id,
            "name": person.name,
            "watchlist_status": person.watchlist_status.value,
            "detection_count": count,
            "last_seen": det.timestamp.isoformat() if det else None,
            "last_camera": cam_name,
        })

    return sorted(activity, key=lambda x: x["detection_count"], reverse=True)


@router.get("/alerts/recent")
async def recent_alerts(
    limit: int = Query(20, le=100),
    severity: Optional[AlertSeverity] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Alert)
    if severity:
        q = q.where(Alert.severity == severity)
    q = q.order_by(Alert.triggered_at.desc()).limit(limit)
    result = await db.execute(q)
    alerts = result.scalars().all()
    output = []
    for alert in alerts:
        d = {
            "id": alert.id,
            "title": alert.title,
            "message": alert.message,
            "severity": alert.severity.value,
            "is_acknowledged": alert.is_acknowledged,
            "triggered_at": alert.triggered_at.isoformat(),
            "person_id": alert.person_id,
            "camera_id": alert.camera_id,
        }
        if alert.person_id:
            pr = await db.execute(select(Person.name).where(Person.id == alert.person_id))
            d["person_name"] = pr.scalar_one_or_none()
        if alert.camera_id:
            cr = await db.execute(select(Camera.name).where(Camera.id == alert.camera_id))
            d["camera_name"] = cr.scalar_one_or_none()
        output.append(d)
    return output


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        return {"error": "Alert not found"}
    alert.is_acknowledged = True
    alert.acknowledged_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "alert_id": alert_id}


@router.get("/cameras/activity-summary")
async def camera_activity_summary(
    hours: int = Query(24, le=168),
    db: AsyncSession = Depends(get_db),
):
    """Detection count per camera for the period."""
    since = datetime.utcnow() - timedelta(hours=hours)
    cams = (await db.execute(select(Camera))).scalars().all()
    summary = []
    for cam in cams:
        count_r = await db.execute(
            select(func.count()).select_from(Detection)
            .where(and_(Detection.camera_id == cam.id,
                        Detection.timestamp >= since))
        )
        count = count_r.scalar() or 0
        watchlist_hits_r = await db.execute(
            select(func.count()).select_from(Detection)
            .where(and_(Detection.camera_id == cam.id,
                        Detection.timestamp >= since,
                        Detection.is_watchlist_hit == True))
        )
        wl_hits = watchlist_hits_r.scalar() or 0
        summary.append({
            "camera_id": cam.id,
            "name": cam.name,
            "location": cam.location,
            "zone": cam.zone,
            "status": cam.status.value,
            "detections": count,
            "watchlist_hits": wl_hits,
        })
    return sorted(summary, key=lambda x: x["detections"], reverse=True)
