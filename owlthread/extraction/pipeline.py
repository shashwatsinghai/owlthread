"""Extraction Pipeline coordinating capture buffering, LLM extraction, and rebase/supersede logic."""

import logging
from typing import Any, Dict, List, Optional

from owlthread.db.database import Database
from owlthread.extraction.buffer import BufferedBatch, BufferManager
from owlthread.extraction.extractor import MemoryExtractor
from owlthread.extraction.rebase import RebaseEngine
from owlthread.primer.llm import LLMClient

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """
    Coordinates OwlThread's Phase 2 Extraction & Rebase Pipeline:
    1. Buffers captures per (project_id, source_app) with 5,000 word threshold.
    2. Flushes buffers automatically on threshold or upon 'done'/'shipped' signal.
    3. Runs LLM memory extraction (categorizing into technical_architecture, business_rules, settled_decisions, open_questions).
    4. Runs LLM rebase engine to identify and link superseded memories.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        llm_client: Optional[LLMClient] = None,
        word_threshold: int = 5000
    ):
        self.db = db or Database()
        self.llm_client = llm_client or LLMClient()
        self.buffer_manager = BufferManager(word_threshold=word_threshold)
        self.extractor = MemoryExtractor(self.llm_client)
        self.rebase_engine = RebaseEngine(self.db, self.llm_client)

    def ingest_capture(
        self,
        raw_text: str,
        source_app: str,
        project_name: Optional[str] = None,
        root_path: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ingest captured text into rolling buffer. If 5,000 word limit is reached,
        automatically flushes and processes the extraction batch.
        
        Returns:
            List of newly created memory entry records if flushed and extracted, else [].
        """
        if not raw_text or not raw_text.strip():
            return []

        project_id = self.db.get_or_create_project(name=project_name, root_path=root_path)
        batch = self.buffer_manager.add_capture(
            project_id=project_id,
            source_app=source_app,
            raw_text=raw_text
        )

        if batch:
            return self.process_batch(batch)

        return []

    def process_batch(self, batch: BufferedBatch) -> List[Dict[str, Any]]:
        """
        Process a single flushed BufferedBatch through extraction and rebase.
        
        Returns:
            List of dicts describing the newly created memory entries and supersede links.
        """
        logger.info(
            "Extracting knowledge for project #%d (%s) from %d words...",
            batch.project_id, batch.source_app, batch.word_count
        )

        # Step 3: LLM Extraction
        extracted_items = self.extractor.extract(batch.combined_text)
        logger.info("Extracted %d structured knowledge items.", len(extracted_items))

        results: List[Dict[str, Any]] = []

        # Step 4: Rebase (supersede logic) per item
        for item in extracted_items:
            new_id, superseded_id = self.rebase_engine.process_item(
                project_id=batch.project_id,
                source_app=batch.source_app,
                item=item,
                timestamp=batch.flush_timestamp
            )
            results.append({
                "entry_id": new_id,
                "project_id": batch.project_id,
                "quadrant": item.get("quadrant"),
                "summary": item.get("summary"),
                "superseded_by": None,
                "superseded_id": superseded_id,
                "status": "active"
            })

        return results

    def handle_done_signal(self) -> Dict[str, Any]:
        """
        Execute explicit 'task done' / 'shipped' signal:
        Flushes all active buffers and runs extraction + rebase.
        
        Returns:
            Summary dictionary of flushed batches, extracted entries, and superseded items.
        """
        logger.info("Task done / shipped signal received. Flushing all capture buffers...")
        flushed_batches = self.buffer_manager.flush_all()
        
        total_extracted = 0
        total_superseded = 0
        extracted_entries: List[Dict[str, Any]] = []

        for batch in flushed_batches:
            batch_results = self.process_batch(batch)
            extracted_entries.extend(batch_results)
            total_extracted += len(batch_results)
            total_superseded += sum(1 for r in batch_results if r["superseded_id"] is not None)

        return {
            "status": "ok",
            "batches_flushed": len(flushed_batches),
            "total_extracted": total_extracted,
            "total_superseded": total_superseded,
            "extracted_entries": extracted_entries,
        }

    def flush_and_extract_text_immediately(
        self,
        raw_text: str,
        source_app: str = "direct",
        project_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Convenience helper to immediately extract and rebase raw text without buffering.
        """
        project_id = self.db.get_or_create_project(name=project_name)
        batch = BufferedBatch(
            project_id=project_id,
            source_app=source_app,
            combined_text=raw_text.strip(),
            word_count=len(raw_text.split()),
            flush_timestamp=self.db.get_iso_now() if hasattr(self.db, "get_iso_now") else "",
            chunk_count=1
        )
        return self.process_batch(batch)
