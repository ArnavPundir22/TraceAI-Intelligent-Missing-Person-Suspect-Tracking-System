"""
TraceAI — Face Embedding Service
Generates 512-d ArcFace embeddings using InsightFace (buffalo_l)
Falls back to DeepFace if InsightFace is unavailable.
"""
import numpy as np
import cv2
from pathlib import Path
from typing import Optional, List, Tuple
from loguru import logger
import asyncio
from app.config import settings

# ---------- Engine Detection ----------
INSIGHTFACE_AVAILABLE = False
DEEPFACE_AVAILABLE = False

try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
    logger.info("InsightFace available — will use ArcFace (w600k_r50)")
except ImportError:
    pass

if not INSIGHTFACE_AVAILABLE:
    try:
        from deepface import DeepFace
        DEEPFACE_AVAILABLE = True
        logger.info("DeepFace available — will use as fallback")
    except ImportError:
        pass

if not INSIGHTFACE_AVAILABLE and not DEEPFACE_AVAILABLE:
    logger.warning("No face recognition engine available — face matching will NOT work")


class EmbeddingService:
    """
    Generates and compares face embeddings.
    Priority: InsightFace (ArcFace/buffalo_l) > DeepFace > Mock.
    """

    def __init__(self):
        self.model_name = settings.FACE_RECOGNITION_MODEL   # "ArcFace"
        self.detector = settings.FACE_DETECTION_BACKEND     # "retinaface"
        self.dim = settings.EMBEDDING_DIM
        self._initialized = False
        self._face_app = None  # InsightFace FaceAnalysis instance
        logger.info(f"EmbeddingService init | model={self.model_name}")

    async def initialize(self):
        if self._initialized:
            return
        if INSIGHTFACE_AVAILABLE:
            await asyncio.get_event_loop().run_in_executor(
                None, self._init_insightface
            )
        elif DEEPFACE_AVAILABLE:
            await asyncio.get_event_loop().run_in_executor(
                None, self._warmup_deepface
            )
        self._initialized = True
        engine = "InsightFace" if self._face_app else ("DeepFace" if DEEPFACE_AVAILABLE else "MOCK")
        logger.info(f"EmbeddingService ready | engine={engine}")

    def _init_insightface(self):
        """Load InsightFace buffalo_l model pack (includes ArcFace recognition)."""
        try:
            self._face_app = FaceAnalysis(
                name='buffalo_l',
                providers=['CPUExecutionProvider'],
            )
            self._face_app.prepare(ctx_id=-1, det_size=(640, 640))
            logger.info("InsightFace buffalo_l loaded successfully")
        except Exception as e:
            logger.error(f"InsightFace init failed: {e}")
            self._face_app = None

    def _warmup_deepface(self):
        """Pre-load DeepFace model weights."""
        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        try:
            DeepFace.represent(dummy, model_name=self.model_name,
                               enforce_detection=False)
        except Exception as e:
            logger.warning(f"DeepFace warmup exception (expected on first run): {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_embedding(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract a 512-d face embedding from an image (BGR or RGB numpy array).
        Returns None if no face is detected.
        """
        try:
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None, self._extract_embedding, image
            )
            return embedding
        except Exception as e:
            logger.error(f"Embedding extraction error: {e}")
            return None

    def _extract_embedding(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Synchronous embedding extraction — dispatches to best available engine."""
        if self._face_app:
            return self._extract_insightface(image)
        elif DEEPFACE_AVAILABLE:
            return self._extract_deepface(image)
        else:
            logger.warning("No face engine — returning None (no mock fallback)")
            return None

    def _extract_insightface(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Extract embedding using InsightFace."""
        try:
            # InsightFace expects BGR
            if len(image.shape) == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

            # Ensure the image is large enough for face detection
            h, w = image.shape[:2]
            if h < 50 or w < 50:
                # Upscale very small crops
                scale = max(112 / h, 112 / w, 1.0)
                image = cv2.resize(image, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_LINEAR)

            faces = self._face_app.get(image)
            if not faces:
                logger.debug("InsightFace: no face detected in image")
                return None

            # Use the face with the highest detection score
            best_face = max(faces, key=lambda f: f.det_score)
            embedding = best_face.normed_embedding  # Already L2-normalized, 512-d

            if embedding is None:
                return None

            vec = np.array(embedding, dtype=np.float32)
            # Ensure L2 normalization
            norm = np.linalg.norm(vec)
            if norm > 1e-10:
                vec = vec / norm
            return vec
        except Exception as e:
            logger.debug(f"InsightFace extraction error: {e}")
            return None

    def _extract_deepface(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Synchronous embedding extraction via DeepFace."""
        try:
            result = DeepFace.represent(
                img_path=image,
                model_name=self.model_name,
                detector_backend=self.detector,
                enforce_detection=True,
                align=True,
            )
            if result:
                vec = np.array(result[0]["embedding"], dtype=np.float32)
                return vec / (np.linalg.norm(vec) + 1e-10)  # L2 normalize
        except Exception as e:
            logger.debug(f"DeepFace represent: {e}")
        return None

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------
    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity in [-1, 1], higher = more similar."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def is_same_person(self, emb_a: np.ndarray, emb_b: np.ndarray) -> Tuple[bool, float]:
        """
        Returns (is_match, similarity_score).
        Uses cosine similarity with configured threshold.
        """
        sim = self.cosine_similarity(emb_a, emb_b)
        return sim >= settings.FACE_SIMILARITY_THRESHOLD, sim

    def find_best_match(
        self,
        query_embedding: np.ndarray,
        candidates: List[Tuple[int, np.ndarray]],  # (person_id, embedding)
    ) -> Optional[Tuple[int, float]]:
        """
        Find the best matching person_id from a list of candidates.
        Returns (person_id, similarity) or None if below threshold.
        """
        best_id, best_sim = None, -1.0
        for pid, emb in candidates:
            sim = self.cosine_similarity(query_embedding, emb)
            if sim > best_sim:
                best_sim = sim
                best_id = pid

        if best_id is not None and best_sim >= settings.FACE_SIMILARITY_THRESHOLD:
            return best_id, best_sim
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_embedding(self, person_id: int, embedding: np.ndarray) -> Path:
        path = settings.EMBEDDINGS_DIR / f"person_{person_id}.npy"
        np.save(str(path), embedding)
        logger.info(f"Saved embedding → {path}")
        return path

    def load_embedding(self, person_id: int) -> Optional[np.ndarray]:
        path = settings.EMBEDDINGS_DIR / f"person_{person_id}.npy"
        if path.exists():
            return np.load(str(path)).astype(np.float32)
        return None

    def load_all_embeddings(self) -> List[Tuple[int, np.ndarray]]:
        """Load all stored embeddings into memory for fast search."""
        embeddings = []
        for f in settings.EMBEDDINGS_DIR.glob("person_*.npy"):
            try:
                pid = int(f.stem.split("_")[1])
                emb = np.load(str(f)).astype(np.float32)
                embeddings.append((pid, emb))
            except Exception as e:
                logger.error(f"Failed to load {f}: {e}")
        logger.info(f"Loaded {len(embeddings)} embeddings from disk")
        return embeddings


# Singleton
embedding_service = EmbeddingService()
