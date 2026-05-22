"""
TraceAI — Multi-Object Tracker
Implements a simplified SORT-style tracker (ByteTrack lite)
for maintaining identity continuity across frames.
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger
import time

from app.services.detection_service import DetectionBox


@dataclass
class Track:
    track_id: int
    bbox: List[float]           # [x1, y1, x2, y2]
    age: int = 0                # frames since last detection
    hits: int = 1               # successful detection count
    velocity: List[float] = field(default_factory=lambda: [0.0, 0.0])
    last_seen: float = field(default_factory=time.time)
    person_id: Optional[int] = None
    confidence: float = 0.0
    class_name: str = "person"

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2,
                (self.bbox[1] + self.bbox[3]) / 2)

    @property
    def is_confirmed(self) -> bool:
        return self.hits >= 3

    def predict(self):
        """Simple constant velocity prediction."""
        self.bbox[0] += self.velocity[0]
        self.bbox[1] += self.velocity[1]
        self.bbox[2] += self.velocity[0]
        self.bbox[3] += self.velocity[1]

    def update(self, det: DetectionBox):
        """Update track with new detection."""
        prev_cx, prev_cy = self.center
        self.bbox = [det.x1, det.y1, det.x2, det.y2]
        new_cx, new_cy = self.center
        self.velocity = [new_cx - prev_cx, new_cy - prev_cy]
        self.age = 0
        self.hits += 1
        self.confidence = det.confidence
        self.last_seen = time.time()


class ByteTracker:
    """
    Simplified ByteTrack-style multi-object tracker.
    Associates detections to existing tracks via IoU matching.
    """

    def __init__(
        self,
        max_age: int = 30,          # frames before track is removed
        min_hits: int = 3,          # min detections to confirm track
        iou_threshold: float = 0.3,
    ):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self._tracks: Dict[int, Track] = {}
        self._next_id = 1
        logger.info(f"ByteTracker initialized | max_age={max_age} iou_thresh={iou_threshold}")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self, detections: List[DetectionBox]) -> List[Track]:
        """
        Process new detections and return updated confirmed tracks.
        """
        # Predict positions
        for track in self._tracks.values():
            track.predict()
            track.age += 1

        # Match detections ↔ tracks via IoU
        matched, unmatched_dets, unmatched_tracks = self._associate(detections)

        # Update matched tracks
        for det_idx, track_id in matched:
            self._tracks[track_id].update(detections[det_idx])

        # Create new tracks for unmatched detections
        for det_idx in unmatched_dets:
            det = detections[det_idx]
            t = Track(
                track_id=self._next_id,
                bbox=[det.x1, det.y1, det.x2, det.y2],
                confidence=det.confidence,
            )
            self._tracks[self._next_id] = t
            self._next_id += 1

        # Remove stale tracks
        stale = [tid for tid, t in self._tracks.items() if t.age > self.max_age]
        for tid in stale:
            del self._tracks[tid]

        return [t for t in self._tracks.values() if t.is_confirmed]

    # ------------------------------------------------------------------
    # Association
    # ------------------------------------------------------------------
    def _associate(
        self, detections: List[DetectionBox]
    ) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        """
        Hungarian-style greedy IoU matching.
        Returns (matched_pairs, unmatched_det_indices, unmatched_track_ids)
        """
        if not self._tracks or not detections:
            return [], list(range(len(detections))), list(self._tracks.keys())

        track_ids = list(self._tracks.keys())
        tracks = [self._tracks[tid] for tid in track_ids]

        iou_matrix = np.zeros((len(detections), len(tracks)), dtype=np.float32)
        for d_idx, det in enumerate(detections):
            for t_idx, track in enumerate(tracks):
                iou_matrix[d_idx, t_idx] = self._iou(
                    [det.x1, det.y1, det.x2, det.y2], track.bbox
                )

        # Greedy matching
        matched_pairs = []
        used_dets, used_tracks = set(), set()
        flat_indices = np.argsort(-iou_matrix.ravel())
        for idx in flat_indices:
            d_idx = idx // len(tracks)
            t_idx = idx % len(tracks)
            if iou_matrix[d_idx, t_idx] < self.iou_threshold:
                break
            if d_idx in used_dets or t_idx in used_tracks:
                continue
            matched_pairs.append((d_idx, track_ids[t_idx]))
            used_dets.add(d_idx)
            used_tracks.add(t_idx)

        unmatched_dets = [i for i in range(len(detections)) if i not in used_dets]
        unmatched_tracks = [track_ids[i] for i in range(len(tracks)) if i not in used_tracks]
        return matched_pairs, unmatched_dets, unmatched_tracks

    @staticmethod
    def _iou(boxA: List[float], boxB: List[float]) -> float:
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])
        inter = max(0, xB - xA) * max(0, yB - yA)
        if inter == 0:
            return 0.0
        aA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        aB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        return inter / (aA + aB - inter + 1e-6)

    def reset(self):
        self._tracks.clear()
        self._next_id = 1


# Per-camera tracker registry
_trackers: Dict[int, ByteTracker] = {}


def get_tracker(camera_id: int) -> ByteTracker:
    if camera_id not in _trackers:
        _trackers[camera_id] = ByteTracker()
    return _trackers[camera_id]
