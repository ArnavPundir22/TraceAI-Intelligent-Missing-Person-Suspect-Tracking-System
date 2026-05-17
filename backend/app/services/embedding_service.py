"""
TraceAI — Face Embedding Service
Generates 512-d ArcFace embeddings using DeepFace / InsightFace
"""
import numpy as np
import cv2
from pathlib import Path
from typing import Optional, List, Tuple
from loguru import logger
import asyncio
from app.config import settings

try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except ImportError:
    DEEPFACE_AVAILABLE = False
    logger.warning("DeepFace not available — using mock embeddings for demo")


class EmbeddingService:
    """
    Generates and compares face embeddings.
    Falls back to deterministic mock vectors when DeepFace is unavailable.
    """

    def __init__(self):
        self.model_name = settings.FACE_RECOGNITION_MODEL   # "ArcFace"
        self.detector = settings.FACE_DETECTION_BACKEND     # "retinaface"
        self.dim = settings.EMBEDDING_DIM
        self._initialized = False
        logger.info(f"EmbeddingService init | model={self.model_name}")

    async def initialize(self):
        if self._initialized:
            return
        if DEEPFACE_AVAILABLE:
            # Warm-up model (runs in thread pool to avoid blocking)
            await asyncio.get_event_loop().run_in_executor(
                None, self._warmup
            )
        self._initialized = True
        logger.info("EmbeddingService ready")

    def _warmup(self):
        """Pre-load model weights."""
        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        try:
            DeepFace.represent(dummy, model_name=self.model_name,
                               enforce_detection=False)
        except Exception as e:
            logger.warning(f"Warmup exception (expected on first run): {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_embedding(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract a 512-d face embedding from an image (BGR numpy array).
        Returns None if no face is detected.
        """
        try:
            if DEEPFACE_AVAILABLE:
                loop = asyncio.get_event_loop()
                embedding = await loop.run_in_executor(
                    None, self._extract_embedding, image
                )
                return embedding
            else:
                return self._mock_embedding(image)
        except Exception as e:
            logger.error(f"Embedding extraction error: {e}")
            return None

    def _extract_embedding(self, image: np.ndarray) -> Optional[np.ndarray]:
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

    def _mock_embedding(self, image: np.ndarray) -> np.ndarray:
        """
        Deterministic mock embedding based on image hash (for demo/testing).
        """
        np.random.seed(hash(image.tobytes()) % (2**32))
        vec = np.random.randn(self.dim).astype(np.float32)
        return vec / (np.linalg.norm(vec) + 1e-10)

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
