"""Capture buffer manager for chunked, per-project + source_app capture buffering."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BUFFER_WORD_THRESHOLD = 5000


def get_iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BufferedBatch:
    """Represents a flushed capture batch ready for knowledge extraction."""
    project_id: int
    source_app: str
    combined_text: str
    word_count: int
    flush_timestamp: str
    chunk_count: int


class BufferManager:
    """
    Maintains a rolling in-memory word-count buffer keyed by (project_id, source_app).
    Automatically triggers a flush when:
      a) Buffer word count >= 5,000 words, OR
      b) An explicit 'task done' / 'shipped' signal is received.
    """

    def __init__(self, word_threshold: int = BUFFER_WORD_THRESHOLD):
        self.word_threshold = word_threshold
        self._lock = threading.Lock()
        # Key: (project_id, source_app) -> List of text snippets
        self._buffers: Dict[Tuple[int, str], List[str]] = {}
        # Key: (project_id, source_app) -> running word count
        self._word_counts: Dict[Tuple[int, str], int] = {}

    def add_capture(
        self,
        project_id: int,
        source_app: str,
        raw_text: str
    ) -> Optional[BufferedBatch]:
        """
        Append new captured raw_text to the rolling buffer for (project_id, source_app).
        If the buffer crosses word_threshold (5,000 words), automatically flushes that buffer.
        
        Returns:
            BufferedBatch if threshold reached and flushed, otherwise None.
        """
        if not raw_text or not raw_text.strip():
            return None

        clean_text = raw_text.strip()
        words = len(clean_text.split())
        key = (project_id, source_app)

        with self._lock:
            if key not in self._buffers:
                self._buffers[key] = []
                self._word_counts[key] = 0

            self._buffers[key].append(clean_text)
            self._word_counts[key] += words
            current_count = self._word_counts[key]

            logger.debug(
                "Buffer (%d, '%s'): added %d words (total: %d / %d threshold)",
                project_id, source_app, words, current_count, self.word_threshold
            )

            if current_count >= self.word_threshold:
                logger.info(
                    "Buffer (%d, '%s') crossed threshold (%d >= %d words). Flushing batch...",
                    project_id, source_app, current_count, self.word_threshold
                )
                return self._flush_buffer_locked(project_id, source_app)

        return None

    def flush_buffer(self, project_id: int, source_app: str) -> Optional[BufferedBatch]:
        """
        Explicitly flush buffer for a specific (project_id, source_app).
        Clears that buffer and stamps the batch with flush timestamp.
        """
        with self._lock:
            return self._flush_buffer_locked(project_id, source_app)

    def flush_all(self) -> List[BufferedBatch]:
        """
        Explicitly flush all active buffers across all (project_id, source_app) keys.
        Used when receiving 'task done' / 'shipped' signal.
        """
        flushed_batches: List[BufferedBatch] = []
        with self._lock:
            keys = list(self._buffers.keys())
            for project_id, source_app in keys:
                batch = self._flush_buffer_locked(project_id, source_app)
                if batch:
                    flushed_batches.append(batch)
        return flushed_batches

    def get_stats(self) -> Dict[str, Any]:
        """Return summary of all active buffers and word counts."""
        with self._lock:
            stats = {}
            for (pid, src), words in self._word_counts.items():
                if words > 0:
                    stats[f"project_{pid}:{src}"] = {
                        "project_id": pid,
                        "source_app": src,
                        "word_count": words,
                        "chunk_count": len(self._buffers.get((pid, src), []))
                    }
            return stats

    def _flush_buffer_locked(self, project_id: int, source_app: str) -> Optional[BufferedBatch]:
        """Internal helper to flush buffer while lock is held."""
        key = (project_id, source_app)
        chunks = self._buffers.get(key, [])
        word_count = self._word_counts.get(key, 0)

        if not chunks or word_count == 0:
            return None

        combined_text = "\n\n---\n\n".join(chunks)
        batch = BufferedBatch(
            project_id=project_id,
            source_app=source_app,
            combined_text=combined_text,
            word_count=word_count,
            flush_timestamp=get_iso_now(),
            chunk_count=len(chunks),
        )

        # Clear buffer
        self._buffers[key] = []
        self._word_counts[key] = 0
        return batch
