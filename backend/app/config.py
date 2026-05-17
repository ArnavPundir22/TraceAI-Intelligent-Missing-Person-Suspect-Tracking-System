"""
TraceAI Configuration Management
Centralized settings using pydantic-settings
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "TraceAI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    SECRET_KEY: str = "traceai-super-secret-key-change-in-production"

    # --- Database ---
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR}/data/db/traceai.db"
    SYNC_DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/db/traceai.db"

    # --- Paths ---
    UPLOAD_DIR: Path = BASE_DIR / "data" / "uploads"
    EMBEDDINGS_DIR: Path = BASE_DIR / "data" / "embeddings"
    SNAPSHOTS_DIR: Path = BASE_DIR / "data" / "snapshots"
    MODELS_DIR: Path = BASE_DIR / "data" / "models"

    # --- AI Models ---
    YOLO_MODEL: str = "yolov8n.pt"
    FACE_DETECTION_BACKEND: str = "retinaface"
    FACE_RECOGNITION_MODEL: str = "ArcFace"
    EMBEDDING_DIM: int = 512

    # --- Recognition Thresholds ---
    FACE_SIMILARITY_THRESHOLD: float = 0.6
    REID_THRESHOLD: float = 0.65
    CONFIDENCE_THRESHOLD: float = 0.5

    # --- Stream ---
    FRAME_SKIP: int = 3           # Process every Nth frame
    MAX_STREAMS: int = 16

    # --- Security ---
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ALGORITHM: str = "HS256"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["*"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# Ensure dirs exist
for d in [settings.UPLOAD_DIR, settings.EMBEDDINGS_DIR,
          settings.SNAPSHOTS_DIR, settings.MODELS_DIR,
          BASE_DIR / "data" / "db"]:
    d.mkdir(parents=True, exist_ok=True)
