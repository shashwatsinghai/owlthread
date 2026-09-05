"""Primer Engine coordinating intent classification, memory search, primer generation, and done signal handling."""

import ctypes
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from owlthread.db.database import Database
from owlthread.primer.classifier import IntentClassifier
from owlthread.primer.generator import PrimerGenerator
from owlthread.primer.llm import LLMClient
from owlthread.primer.search import MemorySearcher

logger = logging.getLogger(__name__)


def copy_to_clipboard(text: str) -> bool:
    """
    Copy plain text to system clipboard across platforms with robust fallbacks.
    """
    if not text:
        return False

    # Method 1: Windows ctypes native clipboard API
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            GMEM_MOVEABLE = 0x0002
            CF_UNICODETEXT = 13

            if not user32.OpenClipboard(0):
                time.sleep(0.05)
                if not user32.OpenClipboard(0):
                    raise RuntimeError("Could not open clipboard")

            try:
                user32.EmptyClipboard()
                text_bytes = text.encode("utf-16le") + b"\x00\x00"
                h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
                if h_mem:
                    p_mem = kernel32.GlobalLock(h_mem)
                    if p_mem:
                        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
                        kernel32.GlobalUnlock(h_mem)
                        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                        return True
            finally:
                user32.CloseClipboard()
        except Exception as e:
            logger.debug("ctypes clipboard copy failed: %s, falling back to clip.exe", e)

        # Method 2: Windows clip command fallback
        try:
            proc = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
                close_fds=True,
                shell=False
            )
            proc.communicate(input=text.encode("utf-16le"))
            if proc.returncode == 0:
                return True
        except Exception as e:
            logger.debug("clip.exe copy failed: %s", e)

    # Method 3: Try tkinter clipboard
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception as e:
        logger.debug("tkinter clipboard copy failed: %s", e)

    return False


@dataclass
class PrimerResult:
    """Encapsulates the complete result of a query primer generation."""
    query: str
    intent: str
    primer_text: str
    matched_entries: List[Dict[str, Any]] = field(default_factory=list)
    copied_to_clipboard: bool = False
    elapsed_sec: float = 0.0
    is_flush_signal: bool = False
    flush_summary: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to serializable dictionary."""
        return {
            "query": self.query,
            "intent": self.intent,
            "primer_text": self.primer_text,
            "matched_entries_count": len(self.matched_entries),
            "matched_entries": self.matched_entries,
            "copied_to_clipboard": self.copied_to_clipboard,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "is_flush_signal": self.is_flush_signal,
            "flush_summary": self.flush_summary,
        }


class PrimerEngine:
    """
    Main coordinator for OwlThread's Query & Primer Engine.
    Executes intent classification -> memory search -> primer generation -> clipboard copy,
    and handles explicit 'done' / 'shipped' capture buffer flush signals.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        llm_client: Optional[LLMClient] = None,
        extraction_pipeline: Optional[Any] = None,
    ):
        self.db = db or Database()
        self.llm_client = llm_client or LLMClient()
        self.classifier = IntentClassifier(self.llm_client)
        self.searcher = MemorySearcher(self.db)
        self.generator = PrimerGenerator(self.llm_client)
        
        if extraction_pipeline is not None:
            self.pipeline = extraction_pipeline
        else:
            from owlthread.extraction.pipeline import ExtractionPipeline
            self.pipeline = ExtractionPipeline(db=self.db, llm_client=self.llm_client)

    def generate_primer(
        self,
        user_request: str,
        intent_override: Optional[str] = None,
        search_limit: int = 12,
        auto_copy: bool = True,
        include_history: bool = False,
        project_id: Optional[int] = None,
    ) -> PrimerResult:
        """
        Execute full pipeline:
        1. Check for explicit 'done' / 'shipped' signal (triggers buffer flush).
        2. Classify intent (or use override).
        3. Search relevant memory entries with keyword + recency scoring on active entries.
        4. Compile context primer using LLM system prompt.
        5. Copy compiled primer to system clipboard.
        """
        start_time = time.time()
        cleaned_query = (user_request or "").strip()
        if not cleaned_query:
            return PrimerResult(
                query="",
                intent="other",
                primer_text="No request provided.",
                matched_entries=[],
                copied_to_clipboard=False,
                elapsed_sec=0.0
            )

        # Check for explicit 'task done' / 'shipped' signal
        lower_query = cleaned_query.lower()
        if lower_query in ("done", "shipped", "task done", "ship it", "finished"):
            flush_res = self.pipeline.handle_done_signal()
            msg = (
                f"🏁 **Task Done / Shipped Signal Processed**\n\n"
                f"- Flushed Buffers: `{flush_res['batches_flushed']}`\n"
                f"- Extracted Knowledge Items: `{flush_res['total_extracted']}`\n"
                f"- Superseded Items: `{flush_res['total_superseded']}`\n\n"
            )
            if flush_res["extracted_entries"]:
                msg += "### Extracted Knowledge Records:\n"
                for item in flush_res["extracted_entries"]:
                    msg += f"- **[#{item['entry_id']}] ({item['quadrant']})**: {item['summary']}\n"
                    if item.get("superseded_id"):
                        msg += f"  *(Superseded previous record #{item['superseded_id']})*\n"
            else:
                msg += "Capture buffers were empty or captured text contained no qualifying durable knowledge."

            copied = copy_to_clipboard(msg) if auto_copy else False
            return PrimerResult(
                query=cleaned_query,
                intent="status_query",
                primer_text=msg,
                matched_entries=[],
                copied_to_clipboard=copied,
                elapsed_sec=time.time() - start_time,
                is_flush_signal=True,
                flush_summary=flush_res
            )

        # 1. Intent Classification
        if intent_override:
            intent = intent_override
        else:
            intent = self.classifier.classify(cleaned_query)

        logger.info("Classified query '%s' -> intent: %s", cleaned_query, intent)

        # 2. Relevance Search (Keyword + Recency with active status filtering)
        matched_entries = self.searcher.search(
            query=cleaned_query,
            limit=search_limit,
            include_history=include_history,
            project_id=project_id,
        )

        logger.info("Found %d matching memory entries for primer context", len(matched_entries))

        # 3. Primer Generation
        primer_text = self.generator.generate(
            user_request=cleaned_query,
            intent_tag=intent,
            matched_entries=matched_entries
        )

        # 4. Auto-copy to clipboard
        copied = False
        if auto_copy and primer_text:
            copied = copy_to_clipboard(primer_text)

        elapsed = time.time() - start_time

        return PrimerResult(
            query=cleaned_query,
            intent=intent,
            primer_text=primer_text,
            matched_entries=matched_entries,
            copied_to_clipboard=copied,
            elapsed_sec=elapsed
        )
