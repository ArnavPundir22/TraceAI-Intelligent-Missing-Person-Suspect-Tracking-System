"""
TraceAI Database Models & Session Management
SQLAlchemy async ORM with SQLite
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    Text, JSON, ForeignKey, Enum, func, Index
)
from datetime import datetime
import enum
from app.config import settings


# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class WatchlistStatus(str, enum.Enum):
    NONE = "none"
    MISSING = "missing"
    SUSPECT = "suspect"
    PERSON_OF_INTEREST = "person_of_interest"


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CameraStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    alias = Column(String(200), nullable=True)
    age = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    watchlist_status = Column(
        Enum(WatchlistStatus), default=WatchlistStatus.NONE, nullable=False
    )
    embedding_path = Column(String(500), nullable=True)    # .npy file path
    face_image_path = Column(String(500), nullable=True)   # reference face image
    metadata_json = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    detections = relationship("Detection", back_populates="person", lazy="select")
    timeline_events = relationship("TimelineEvent", back_populates="person", lazy="select")
    alerts = relationship("Alert", back_populates="person", lazy="select")

    def __repr__(self):
        return f"<Person id={self.id} name={self.name} status={self.watchlist_status}>"


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    location = Column(String(300), nullable=True)
    stream_url = Column(String(500), nullable=True)     # RTSP / file / 0 (webcam)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    zone = Column(String(100), nullable=True)           # e.g. "North Gate", "Parking"
    status = Column(Enum(CameraStatus), default=CameraStatus.INACTIVE)
    fps = Column(Float, default=25.0)
    resolution = Column(String(20), default="1920x1080")
    metadata_json = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

    detections = relationship("Detection", back_populates="camera", lazy="select")
    timeline_events = relationship("TimelineEvent", back_populates="camera", lazy="select")
    heatmap_data = relationship("HeatmapData", back_populates="camera", lazy="select")

    def __repr__(self):
        return f"<Camera id={self.id} name={self.name} status={self.status}>"


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    track_id = Column(Integer, nullable=True)           # ByteTrack / DeepSORT ID
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    bbox_x2 = Column(Float)
    bbox_y2 = Column(Float)
    face_confidence = Column(Float, default=0.0)
    reid_confidence = Column(Float, default=0.0)
    face_embedding = Column(JSON, nullable=True)        # stored as list
    snapshot_path = Column(String(500), nullable=True)
    is_watchlist_hit = Column(Boolean, default=False)
    metadata_json = Column(JSON, default={})

    person = relationship("Person", back_populates="detections")
    camera = relationship("Camera", back_populates="detections")

    __table_args__ = (
        Index("ix_detection_timestamp", "timestamp"),
        Index("ix_detection_person_cam", "person_id", "camera_id"),
    )


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    entered_at = Column(DateTime, nullable=False)
    exited_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    confidence = Column(Float, default=0.0)
    snapshot_path = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    person = relationship("Person", back_populates="timeline_events")
    camera = relationship("Camera", back_populates="timeline_events")

    __table_args__ = (
        Index("ix_timeline_person", "person_id"),
        Index("ix_timeline_entered", "entered_at"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.MEDIUM)
    title = Column(String(300), nullable=False)
    message = Column(Text, nullable=False)
    snapshot_path = Column(String(500), nullable=True)
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime, nullable=True)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    metadata_json = Column(JSON, default={})

    person = relationship("Person", back_populates="alerts")

    __table_args__ = (
        Index("ix_alert_triggered", "triggered_at"),
        Index("ix_alert_severity", "severity"),
    )


class HeatmapData(Base):
    __tablename__ = "heatmap_data"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    grid_x = Column(Integer, nullable=False)
    grid_y = Column(Integer, nullable=False)
    count = Column(Integer, default=0)
    hour_bucket = Column(Integer, nullable=True)        # 0-23 for hourly aggregation
    date_bucket = Column(String(10), nullable=True)     # YYYY-MM-DD

    camera = relationship("Camera", back_populates="heatmap_data")

    __table_args__ = (
        Index("ix_heatmap_camera_date", "camera_id", "date_bucket"),
    )


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), default="INFO")
    module = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    metadata_json = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Init DB
# ---------------------------------------------------------------------------
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
