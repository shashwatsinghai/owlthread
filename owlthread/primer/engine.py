"""Primer Engine coordinating intent classification, memory search, primer generation, and done signal handling."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from owlthread.db.database import Database
from owlthread.primer.classifier import IntentClassifier
from owlthread.primer.generator import PrimerGenerator
from owlthread.primer.llm import LLMClient
from owlthread.primer.search import MemorySearcher

logger = logging.getLogger(__name__)


from owlthread.clipboard_io import copy_to_clipboard


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
    diagnostics: Dict[str, Any] = field(default_factory=dict)

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
            "diagnostics": self.diagnostics,
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
    ) -> None:
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

    def _copy(self, text: str) -> bool:
        """Register the output before copying so the watcher cannot recapture it."""
        try:
            self.db.set_setting("last_primer_clipboard_hash", hashlib.sha256(text.encode("utf-8")).hexdigest())
        except Exception:
            logger.warning("Could not persist clipboard suppression hash")
        return copy_to_clipboard(text)

    def generate_primer(
        self,
        user_request: str,
        intent_override: Optional[str] = None,
        search_limit: int = 12,
        auto_copy: bool = True,
        include_history: bool = False,
        project_id: Optional[int] = None,
        context_char_budget: int = 12000,
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
        if project_id is None:
            project_id = self.db.get_or_create_project(self.db.get_setting("active_project", "General"))
        elif type(project_id) is not int or not self.db.get_project_by_id(project_id):
            raise ValueError("Project does not exist")
        self.llm_client.reload_from_db(self.db)
        self.generator.custom_system_prompt = self.db.get_setting("primer_prompt") or None
        if intent_override and intent_override not in {"dev_task", "external_comms", "status_query", "other"}:
            raise ValueError("Invalid intent")
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
            elif not flush_res.get("errors"):
                msg += "Capture buffers were empty or captured text contained no qualifying durable knowledge."
            if flush_res.get("errors"):
                msg += f"\n\n{len(flush_res['errors'])} captures could not be processed. They remain saved for retry; run done again after resolving the storage error."

            copied = self._copy(msg) if auto_copy else False
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

        logger.debug("Classified request as %s", intent)

        # 2. Local retrieval. Normal tasks fan out across every quadrant and the
        # durable raw capture index, then pack evidence to a strict character cap.
        context: Dict[str, Any] | None = None
        if intent == "status_query":
            from owlthread.config import QUADRANT_COLORS
            # Include every quadrant even when recent architecture dominates the feed.
            matched_entries = []
            for quadrant in QUADRANT_COLORS:
                matched_entries.extend(self.searcher.search("",limit=max(1,search_limit//4),
                    project_id=project_id,quadrant=quadrant,include_history=include_history))
        else:
            context = self.searcher.search_context(cleaned_query,project_id=project_id,
                per_quadrant_limit=max(1,min(200,search_limit)),capture_limit=max(1,min(200,search_limit)),
                char_budget=context_char_budget,include_history=include_history)
            matched_entries = context["items"]

        logger.info("Found %d matching memory entries for primer context", len(matched_entries))

        # 3. Persistent exact-result cache. The key changes with the query,
        # project, configured model/prompt, or any matched evidence revision.
        revisions=[]
        for entry in matched_entries:
            if entry.get("context_kind")=="capture":
                revisions.append(["C",entry["id"],entry.get("captured_at"),entry.get("processed_chars"),
                                  entry.get("extraction_status")])
            else:
                revisions.append(["M",entry["id"],entry.get("updated_at") or entry.get("created_at"),entry.get("status")])
        model_key=f"{self.llm_client.provider or 'fallback'}:{self.llm_client.model or ''}"
        matched_revision=hashlib.sha256(json.dumps(revisions,sort_keys=True,default=str).encode()).hexdigest()
        cache_material={"query":cleaned_query.casefold(),"project_id":project_id,"model":model_key,
                        "generation_options":self.llm_client.memory_generation_options(1500),
                        "matched_revision":matched_revision,"intent":intent,"history":include_history,
                        "prompt":hashlib.sha256(self.generator.active_system_prompt.encode()).hexdigest(),
                        "context":hashlib.sha256((context or {}).get("context_text","").encode()).hexdigest()}
        cache_key=hashlib.sha256(json.dumps(cache_material,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        cached=self.db.get_primer_cache(cache_key)
        cache_hit=bool(cached and isinstance(cached.get("primer_text"),str))
        if cache_hit:
            primer_text=cached["primer_text"]
        else:
            primer_text = self.generator.generate(
                user_request=cleaned_query,
                intent_tag=intent,
                matched_entries=matched_entries,
                context_text=context["context_text"] if context is not None else None
            )
            self.db.set_primer_cache(cache_key,project_id,cleaned_query,model_key,matched_revision,
                                     {"primer_text":primer_text})
        if intent == "status_query":
            where = "status='active'" + (" AND project_id=?" if project_id is not None else "")
            totals = {row["quadrant"]:row["n"] for row in self.db.execute_read(
                "SELECT quadrant,COUNT(*) AS n FROM memory_entries WHERE "+where+" GROUP BY quadrant",
                (project_id,) if project_id is not None else ())}
            from owlthread.config import QUADRANT_COLORS
            primer_text += "\n\n## Active Memory Totals\n" + "\n".join(
                f"- {quadrant.replace('_',' ').title()}: {totals.get(quadrant,0)}" for quadrant in QUADRANT_COLORS)

        # 4. Auto-copy to clipboard
        copied = False
        if auto_copy and primer_text:
            copied = self._copy(primer_text)

        elapsed = time.time() - start_time

        return PrimerResult(
            query=cleaned_query,
            intent=intent,
            primer_text=primer_text,
            matched_entries=matched_entries,
            copied_to_clipboard=copied,
            elapsed_sec=elapsed,
            diagnostics={"context_char_budget":context["char_budget"] if context else 0,
                         "context_chars_used":context["chars_used"] if context else 0,
                         "context_truncated":context["truncated"] if context else False,
                         "context_candidates":context["candidates_considered"] if context else len(matched_entries),
                         "memory_matches":context["memory_count"] if context else len(matched_entries),
                         "capture_matches":context["capture_count"] if context else 0,
                         "cache_hit":cache_hit,"cache_key":cache_key[:16],"cache_capacity":200}
        )
