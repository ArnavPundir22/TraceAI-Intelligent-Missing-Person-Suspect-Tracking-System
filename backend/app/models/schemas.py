"""
TraceAI Pydantic Schemas (Request / Response models)
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any
from datetime import datetime
from app.models.database import WatchlistStatus, AlertSeverity, CameraStatus


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------
class PersonBase(BaseModel):
    name: str
    alias: Optional[str] = None
    age: Optional[int] = None
    description: Optional[str] = None
    watchlist_status: WatchlistStatus = WatchlistStatus.NONE


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    name: Optional[str] = None
    alias: Optional[str] = None
    age: Optional[int] = None
    description: Optional[str] = None
    watchlist_status: Optional[WatchlistStatus] = None


class PersonResponse(PersonBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    face_image_path: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
class CameraBase(BaseModel):
    name: str
    location: Optional[str] = None
    stream_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    zone: Optional[str] = None
    fps: float = 25.0
    resolution: str = "1920x1080"


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    stream_url: Optional[str] = None
    zone: Optional[str] = None
    status: Optional[CameraStatus] = None


class CameraResponse(CameraBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: CameraStatus
    created_at: datetime


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
class DetectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    person_id: Optional[int]
    camera_id: int
    track_id: Optional[int]
    timestamp: datetime
    bbox_x1: float
    bbox_y1: float
    bbox_x2: float
    bbox_y2: float
    face_confidence: float
    reid_confidence: float
    snapshot_path: Optional[str]
    is_watchlist_hit: bool


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    person_id: int
    camera_id: int
    entered_at: datetime
    exited_at: Optional[datetime]
    duration_seconds: Optional[float]
    confidence: float
    snapshot_path: Optional[str]
    notes: Optional[str]


class MovementTimeline(BaseModel):
    person_id: int
    person_name: str
    watchlist_status: str
    events: List[dict]
    total_cameras: int
    total_duration_seconds: float
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------
class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    person_id: Optional[int]
    camera_id: Optional[int]
    severity: AlertSeverity
    title: str
    message: str
    snapshot_path: Optional[str]
    is_acknowledged: bool
    triggered_at: datetime


class AlertAcknowledge(BaseModel):
    acknowledged: bool = True


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class SearchResult(BaseModel):
    person_id: int
    person_name: str
    watchlist_status: str
    similarity_score: float
    last_seen_camera: Optional[str]
    last_seen_timestamp: Optional[datetime]
    face_image_path: Optional[str]
    snapshot_path: Optional[str]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class HeatmapPoint(BaseModel):
    x: int
    y: int
    count: int


class DashboardStats(BaseModel):
    total_persons: int
    watchlisted_persons: int
    missing_persons: int
    suspects: int
    active_cameras: int
    total_cameras: int
    alerts_today: int
    unacknowledged_alerts: int
    detections_today: int
    detections_last_hour: int


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
class WSMessage(BaseModel):
    type: str
    data: Any
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str
