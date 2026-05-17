"""
TraceAI — Main FastAPI Application
Entry point with all routers, middleware, lifespan, and static file serving.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
import sys

from app.config import settings
from app.models.database import init_db
from app.services.detection_service import detection_service
from app.services.embedding_service import embedding_service

# API Routers
from app.api.persons import router as persons_router
from app.api.cameras import router as cameras_router
from app.api.analytics import router as analytics_router
from app.api.video_upload import router as upload_router
from app.api.websocket import router as ws_router

# Configure loguru
logger.remove()
logger.add(sys.stderr, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
logger.add("data/logs/traceai.log", rotation="10 MB", retention="7 days", level="DEBUG")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info(f"  TraceAI v{settings.APP_VERSION} starting up...")
    logger.info("=" * 60)

    # Initialize DB
    await init_db()
    logger.info("✓ Database initialized")

    # Pre-load AI models
    await detection_service.initialize()
    await embedding_service.initialize()
    logger.info("✓ AI models ready")

    # Seed demo data if DB is empty
    await _seed_demo_data()
    logger.info("✓ Demo data seeded")

    logger.info("🚀 TraceAI is live → http://localhost:8000")
    yield

    # Shutdown
    from app.services.stream_processor import stream_manager
    await stream_manager.stop_all()
    logger.info("TraceAI shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TraceAI",
    description="Intelligent Missing Person & Suspect Tracking System",
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.utcnow()
    response = await call_next(request)
    elapsed = (datetime.utcnow() - start).total_seconds() * 1000
    if not request.url.path.startswith("/static"):
        logger.debug(f"{request.method} {request.url.path} → {response.status_code} [{elapsed:.1f}ms]")
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
API_PREFIX = "/api/v1"

app.include_router(persons_router, prefix=API_PREFIX)
app.include_router(cameras_router, prefix=API_PREFIX)
app.include_router(analytics_router, prefix=API_PREFIX)
app.include_router(upload_router, prefix=API_PREFIX)
app.include_router(ws_router)  # WebSocket at /ws


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Static Files (Frontend)
# ---------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "src")), name="static")
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str):
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"message": "TraceAI API Running"})

    @app.get("/", include_in_schema=False)
    async def serve_root():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"message": "TraceAI API Running. Frontend not found."})


# ---------------------------------------------------------------------------
# Demo Data Seed
# ---------------------------------------------------------------------------
async def _seed_demo_data():
    """Populate DB with realistic demo records for dashboard demonstration."""
    from app.models.database import AsyncSessionLocal, Person, Camera, Detection, Alert, TimelineEvent
    from app.models.database import WatchlistStatus, CameraStatus, AlertSeverity
    from sqlalchemy import select, func
    import random

    async with AsyncSessionLocal() as db:
        # Check if already seeded
        count = (await db.execute(select(func.count()).select_from(Person))).scalar()
        if count and count > 0:
            return

        logger.info("Seeding demo data...")

        # --- Cameras ---
        cameras_data = [
            {"name": "North Gate", "location": "Main Entrance North", "zone": "Entry Points",
             "latitude": 28.6139, "longitude": 77.2090, "status": CameraStatus.ACTIVE},
            {"name": "Parking Zone A", "location": "Underground Parking Level 1", "zone": "Parking",
             "latitude": 28.6141, "longitude": 77.2092, "status": CameraStatus.ACTIVE},
            {"name": "Main Corridor", "location": "Central Hallway Floor 1", "zone": "Interior",
             "latitude": 28.6140, "longitude": 77.2091, "status": CameraStatus.ACTIVE},
            {"name": "Food Court", "location": "Level 2 Food Court", "zone": "Interior",
             "latitude": 28.6142, "longitude": 77.2093, "status": CameraStatus.ACTIVE},
            {"name": "East Exit", "location": "Emergency Exit East Wing", "zone": "Exit Points",
             "latitude": 28.6138, "longitude": 77.2095, "status": CameraStatus.ACTIVE},
            {"name": "West Wing Stairs", "location": "Stairwell W-2", "zone": "Interior",
             "latitude": 28.6137, "longitude": 77.2088, "status": CameraStatus.ACTIVE},
            {"name": "Server Room Corridor", "location": "Basement Level B1", "zone": "Restricted",
             "latitude": 28.6136, "longitude": 77.2089, "status": CameraStatus.ACTIVE},
            {"name": "South Gate", "location": "Main Entrance South", "zone": "Entry Points",
             "latitude": 28.6135, "longitude": 77.2091, "status": CameraStatus.INACTIVE},
        ]

        cameras = []
        for c in cameras_data:
            cam = Camera(**c)
            db.add(cam)
            cameras.append(cam)
        await db.flush()

        # --- Persons ---
        persons_data = [
            {"name": "Arjun Sharma", "age": 34, "alias": "AJ",
             "description": "6'1\", athletic build, short dark hair",
             "watchlist_status": WatchlistStatus.SUSPECT},
            {"name": "Priya Mehta", "age": 28, "alias": None,
             "description": "5'4\", long black hair, usually wears blue",
             "watchlist_status": WatchlistStatus.MISSING},
            {"name": "Rohit Kumar", "age": 45, "alias": "RK",
             "description": "5'9\", heavy build, bald",
             "watchlist_status": WatchlistStatus.PERSON_OF_INTEREST},
            {"name": "Ananya Singh", "age": 22, "alias": None,
             "description": "5'2\", college student, backpack",
             "watchlist_status": WatchlistStatus.NONE},
            {"name": "Vikram Nair", "age": 38, "alias": "Viktor",
             "description": "6'0\", beard, usually in black hoodie",
             "watchlist_status": WatchlistStatus.SUSPECT},
            {"name": "Deepa Iyer", "age": 31, "alias": None,
             "description": "5'6\", professional attire, glasses",
             "watchlist_status": WatchlistStatus.MISSING},
            {"name": "Rajesh Patel", "age": 52, "alias": None,
             "description": "5'8\", grey hair, suit",
             "watchlist_status": WatchlistStatus.NONE},
            {"name": "Kavya Reddy", "age": 19, "alias": None,
             "description": "5'3\", hijab, pink bag",
             "watchlist_status": WatchlistStatus.NONE},
        ]

        persons = []
        for p in persons_data:
            person = Person(**p)
            db.add(person)
            persons.append(person)
        await db.flush()

        # --- Detections (realistic timeline) ---
        base_time = datetime.utcnow().replace(hour=7, minute=0, second=0)
        for person in persons:
            for cam_idx, cam in enumerate(random.sample(cameras, k=random.randint(2, 6))):
                offset_minutes = cam_idx * random.randint(6, 18)
                ts = base_time.replace(minute=offset_minutes % 60,
                                       hour=7 + offset_minutes // 60)
                det = Detection(
                    person_id=person.id,
                    camera_id=cam.id,
                    track_id=random.randint(1, 999),
                    timestamp=ts,
                    bbox_x1=random.uniform(100, 400),
                    bbox_y1=random.uniform(50, 200),
                    bbox_x2=random.uniform(500, 900),
                    bbox_y2=random.uniform(400, 700),
                    face_confidence=random.uniform(0.75, 0.99),
                    reid_confidence=random.uniform(0.70, 0.97),
                    is_watchlist_hit=(person.watchlist_status != WatchlistStatus.NONE),
                )
                db.add(det)

                tl = TimelineEvent(
                    person_id=person.id,
                    camera_id=cam.id,
                    entered_at=ts,
                    exited_at=ts.replace(minute=(ts.minute + random.randint(2, 15)) % 60),
                    duration_seconds=random.uniform(30, 900),
                    confidence=random.uniform(0.75, 0.99),
                )
                db.add(tl)

        # --- Alerts ---
        alert_data = [
            {
                "person_id": persons[0].id,
                "camera_id": cameras[0].id,
                "severity": AlertSeverity.CRITICAL,
                "title": f"⚠ WATCHLIST MATCH: {persons[0].name}",
                "message": f"Suspect {persons[0].name} detected at {cameras[0].name}. Immediate attention required.",
                "triggered_at": datetime.utcnow(),
            },
            {
                "person_id": persons[1].id,
                "camera_id": cameras[2].id,
                "severity": AlertSeverity.HIGH,
                "title": f"🔍 MISSING PERSON: {persons[1].name}",
                "message": f"Missing person {persons[1].name} detected at {cameras[2].name}.",
                "triggered_at": datetime.utcnow(),
            },
            {
                "person_id": persons[4].id,
                "camera_id": cameras[6].id,
                "severity": AlertSeverity.HIGH,
                "title": f"Restricted Zone Access: {persons[4].name}",
                "message": f"Suspect {persons[4].name} entered {cameras[6].name} (Restricted Zone).",
                "triggered_at": datetime.utcnow(),
            },
        ]
        for a in alert_data:
            db.add(Alert(**a))

        await db.commit()
        logger.info(f"Demo data seeded: {len(persons)} persons, {len(cameras)} cameras, 3 alerts")
