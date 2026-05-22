"""
TraceAI — Person (Profile) API Router
CRUD + face enrollment + image search
"""
import os
import shutil
import uuid
import numpy as np
import cv2
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from datetime import datetime

from app.models.database import get_db, Person, Detection, TimelineEvent, Alert
from app.models.database import WatchlistStatus
from app.models.schemas import (
    PersonCreate, PersonUpdate, PersonResponse,
    SearchResult, MovementTimeline, TimelineEventResponse
)
from app.services.embedding_service import embedding_service
from app.config import settings
from loguru import logger

router = APIRouter(prefix="/persons", tags=["Persons"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("/", response_model=List[PersonResponse])
async def list_persons(
    watchlist: Optional[WatchlistStatus] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = select(Person).where(Person.is_active == True)
    if watchlist:
        q = q.where(Person.watchlist_status == watchlist)
    if search:
        q = q.where(
            or_(Person.name.ilike(f"%{search}%"), Person.alias.ilike(f"%{search}%"))
        )
    q = q.order_by(Person.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=PersonResponse, status_code=201)
async def create_person(
    name: str = Form(...),
    alias: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    watchlist_status: str = Form("none"),
    face_photo: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new person with an optional face photo.
    If a photo is provided, a face embedding is generated and stored
    immediately — enabling identity matching in live streams right away.
    """
    db_person = Person(
        name=name,
        alias=alias or None,
        age=age,
        description=description or None,
        watchlist_status=WatchlistStatus(watchlist_status),
    )
    db.add(db_person)
    await db.commit()
    await db.refresh(db_person)

    # If a face photo was uploaded, generate embedding immediately
    if face_photo and face_photo.filename:
        try:
            ext = Path(face_photo.filename).suffix or ".jpg"
            fname = f"person_{db_person.id}_face{ext}"
            face_path = settings.UPLOAD_DIR / fname
            with open(face_path, "wb") as f:
                shutil.copyfileobj(face_photo.file, f)

            img_data = cv2.imdecode(
                np.frombuffer(open(face_path, "rb").read(), np.uint8),
                cv2.IMREAD_COLOR,
            )
            if img_data is not None:
                embedding = await embedding_service.get_embedding(img_data)
                if embedding is not None:
                    embed_path = embedding_service.save_embedding(db_person.id, embedding)
                    db_person.embedding_path = str(embed_path)
                db_person.face_image_path = str(face_path)
                await db.commit()
                await db.refresh(db_person)
        except Exception as e:
            # Photo processing failed but person was still created
            logger.warning(f"Face enrollment during creation failed for {name}: {e}")

    return db_person


@router.get("/{person_id}", response_model=PersonResponse)
async def get_person(person_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(404, "Person not found")
    return person


@router.put("/{person_id}", response_model=PersonResponse)
async def update_person(
    person_id: int,
    update_data: PersonUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(404, "Person not found")
    for k, v in update_data.model_dump(exclude_unset=True).items():
        setattr(person, k, v)
    person.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(person)
    return person


@router.delete("/{person_id}", status_code=204)
async def delete_person(person_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(404, "Person not found")
    person.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Face Enrollment
# ---------------------------------------------------------------------------
@router.post("/{person_id}/enroll-face", response_model=dict)
async def enroll_face(
    person_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a reference face image to generate and store face embeddings.
    This is the registration step that enables identity matching in streams.
    """
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(404, "Person not found")

    # Save face image
    ext = Path(file.filename).suffix or ".jpg"
    fname = f"person_{person_id}_face{ext}"
    face_path = settings.UPLOAD_DIR / fname
    with open(face_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Generate embedding
    img_data = cv2.imdecode(
        np.frombuffer(open(face_path, "rb").read(), np.uint8),
        cv2.IMREAD_COLOR,
    )
    embedding = await embedding_service.get_embedding(img_data)

    if embedding is None:
        raise HTTPException(422, "No face detected in the uploaded image. Please use a clear frontal photo.")

    # Persist
    embed_path = embedding_service.save_embedding(person_id, embedding)
    person.embedding_path = str(embed_path)
    person.face_image_path = str(face_path)
    person.updated_at = datetime.utcnow()
    await db.commit()

    return {
        "success": True,
        "person_id": person_id,
        "embedding_dim": len(embedding),
        "message": f"Face enrolled for {person.name}",
    }


# ---------------------------------------------------------------------------
# Image Search (Upload → Find matching persons)
# ---------------------------------------------------------------------------
@router.post("/search/by-image", response_model=List[SearchResult])
async def search_by_image(
    file: UploadFile = File(...),
    top_k: int = Query(5, le=20),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an image and find all matching persons in the database.
    Returns ranked results with similarity scores.
    """
    contents = await file.read()
    img_array = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, "Cannot decode image")
    query_embedding = await embedding_service.get_embedding(img)
    if query_embedding is None:
        raise HTTPException(422, "No face detected in query image")

    # Load all stored embeddings
    all_embeddings = embedding_service.load_all_embeddings()
    if not all_embeddings:
        return []

    # Score all
    scored = []
    for pid, emb in all_embeddings:
        sim = embedding_service.cosine_similarity(query_embedding, emb)
        scored.append((pid, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:top_k]

    results = []
    for pid, sim in top:
        person_result = await db.execute(select(Person).where(Person.id == pid))
        person = person_result.scalar_one_or_none()
        if not person:
            continue

        # Last seen
        last_det = await db.execute(
            select(Detection)
            .where(Detection.person_id == pid)
            .order_by(Detection.timestamp.desc())
            .limit(1)
        )
        last_det = last_det.scalar_one_or_none()

        # Camera name
        cam_name = None
        if last_det:
            from app.models.database import Camera
            cam_r = await db.execute(
                select(Camera.name).where(Camera.id == last_det.camera_id)
            )
            cam_name = cam_r.scalar_one_or_none()

        results.append(SearchResult(
            person_id=pid,
            person_name=person.name,
            watchlist_status=person.watchlist_status.value,
            similarity_score=round(sim, 4),
            last_seen_camera=cam_name,
            last_seen_timestamp=last_det.timestamp if last_det else None,
            face_image_path=person.face_image_path,
            snapshot_path=last_det.snapshot_path if last_det else None,
        ))

    return results


# ---------------------------------------------------------------------------
# Movement Timeline
# ---------------------------------------------------------------------------
@router.get("/{person_id}/timeline", response_model=MovementTimeline)
async def get_timeline(person_id: int, db: AsyncSession = Depends(get_db)):
    """Returns the complete movement timeline of a person across all cameras."""
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(404, "Person not found")

    events_result = await db.execute(
        select(TimelineEvent)
        .where(TimelineEvent.person_id == person_id)
        .order_by(TimelineEvent.entered_at.asc())
    )
    events = events_result.scalars().all()

    from app.models.database import Camera
    event_list = []
    unique_cameras = set()
    total_duration = 0.0
    first_seen = None
    last_seen = None

    for ev in events:
        cam_r = await db.execute(select(Camera).where(Camera.id == ev.camera_id))
        cam = cam_r.scalar_one_or_none()
        unique_cameras.add(ev.camera_id)
        total_duration += ev.duration_seconds or 0
        if first_seen is None or ev.entered_at < first_seen:
            first_seen = ev.entered_at
        if last_seen is None or (ev.exited_at or ev.entered_at) > last_seen:
            last_seen = ev.exited_at or ev.entered_at

        event_list.append({
            "event_id": ev.id,
            "camera_id": ev.camera_id,
            "camera_name": cam.name if cam else f"Camera {ev.camera_id}",
            "location": cam.location if cam else "Unknown",
            "zone": cam.zone if cam else "Unknown",
            "entered_at": ev.entered_at.isoformat(),
            "exited_at": ev.exited_at.isoformat() if ev.exited_at else None,
            "duration_seconds": ev.duration_seconds,
            "confidence": ev.confidence,
            "snapshot_path": ev.snapshot_path,
        })

    return MovementTimeline(
        person_id=person_id,
        person_name=person.name,
        watchlist_status=person.watchlist_status.value,
        events=event_list,
        total_cameras=len(unique_cameras),
        total_duration_seconds=total_duration,
        first_seen=first_seen,
        last_seen=last_seen,
    )


# ---------------------------------------------------------------------------
# Face Image Endpoint
# ---------------------------------------------------------------------------
@router.get("/{person_id}/face-image")
async def get_face_image(person_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person or not person.face_image_path:
        raise HTTPException(404, "Face image not found")
    path = Path(person.face_image_path)
    if not path.exists():
        raise HTTPException(404, "Face image file missing")
    return FileResponse(str(path), media_type="image/jpeg")
