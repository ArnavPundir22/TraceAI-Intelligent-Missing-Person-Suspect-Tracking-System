"""
TraceAI — Person Detection Service
YOLOv8 person detection with fallback mock detector
"""
import numpy as np
import cv2
from typing import List, Dict, Optional
from dataclasses import dataclass
from loguru import logger
import asyncio
from app.config import settings

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logger.warning("Ultralytics YOLO not available — using mock detector")


@dataclass
class DetectionBox:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_name: str = "person"

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self):
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_dict(self) -> dict:
        return {
            "bbox": [self.x1, self.y1, self.x2, self.y2],
            "confidence": self.confidence,
            "class": self.class_name,
        }

    def crop_from(self, image: np.ndarray, padding: int = 10) -> np.ndarray:
        """Extract crop from image with optional padding."""
        h, w = image.shape[:2]
        x1 = max(0, int(self.x1) - padding)
        y1 = max(0, int(self.y1) - padding)
        x2 = min(w, int(self.x2) + padding)
        y2 = min(h, int(self.y2) + padding)
        return image[y1:y2, x1:x2]


class DetectionService:
    """
    YOLOv8-based person detector.
    Detects 'person' class objects in video frames.
    """

    def __init__(self):
        self.model = None
        self.conf_threshold = settings.CONFIDENCE_THRESHOLD
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        if YOLO_AVAILABLE:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._load_model)
        self._initialized = True
        logger.info(f"DetectionService ready | YOLO={YOLO_AVAILABLE}")

    def _load_model(self):
        try:
            self.model = YOLO(settings.YOLO_MODEL)
            logger.info(f"Loaded YOLOv8 model: {settings.YOLO_MODEL}")
        except Exception as e:
            logger.error(f"YOLO load failed: {e}")
            self.model = None

    # ------------------------------------------------------------------
    # Detect
    # ------------------------------------------------------------------
    async def detect_persons(self, frame: np.ndarray) -> List[DetectionBox]:
        """
        Run person detection on a single frame.
        Returns list of DetectionBox (filtered to 'person' class only).
        """
        if not self._initialized:
            await self.initialize()

        try:
            loop = asyncio.get_event_loop()
            boxes = await loop.run_in_executor(None, self._run_detection, frame)
            return boxes
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return []

    def _run_detection(self, frame: np.ndarray) -> List[DetectionBox]:
        if self.model is None:
            return self._mock_detections(frame)

        results = self.model(frame, conf=self.conf_threshold, classes=[0], verbose=False)
        boxes = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                boxes.append(DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=conf))
        return boxes

    def _mock_detections(self, frame: np.ndarray) -> List[DetectionBox]:
        """Generate realistic mock detections for demo."""
        h, w = frame.shape[:2]
        np.random.seed(42)
        mock = []
        for _ in range(np.random.randint(1, 4)):
            x1 = np.random.uniform(0.1, 0.6) * w
            y1 = np.random.uniform(0.1, 0.5) * h
            bw = np.random.uniform(0.1, 0.2) * w
            bh = np.random.uniform(0.3, 0.5) * h
            mock.append(DetectionBox(
                x1=x1, y1=y1, x2=min(x1 + bw, w), y2=min(y1 + bh, h),
                confidence=np.random.uniform(0.7, 0.99)
            ))
        return mock

    # ------------------------------------------------------------------
    # Annotate
    # ------------------------------------------------------------------
    @staticmethod
    def draw_detections(frame: np.ndarray, boxes: List[DetectionBox],
                        labels: Optional[List[str]] = None,
                        colors: Optional[List[tuple]] = None) -> np.ndarray:
        """Draw bounding boxes on frame."""
        annotated = frame.copy()
        for i, box in enumerate(boxes):
            color = colors[i] if colors and i < len(colors) else (0, 255, 80)
            label = labels[i] if labels and i < len(labels) else f"Person ({box.confidence:.2f})"
            cv2.rectangle(annotated,
                          (int(box.x1), int(box.y1)),
                          (int(box.x2), int(box.y2)),
                          color, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(annotated,
                          (int(box.x1), int(box.y1) - th - 10),
                          (int(box.x1) + tw + 4, int(box.y1)),
                          color, -1)
            cv2.putText(annotated, label,
                        (int(box.x1) + 2, int(box.y1) - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        return annotated


# Singleton
detection_service = DetectionService()
