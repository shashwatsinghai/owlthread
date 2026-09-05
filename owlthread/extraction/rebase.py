"""Rebase and supersede logic for OwlThread Phase 2 extraction pipeline."""

import json
import logging
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from owlthread.db.database import Database
from owlthread.primer.llm import LLMClient

logger = logging.getLogger(__name__)

# Valid 4-quadrant taxonomy
QUAD_TECHNICAL_ARCHITECTURE = "technical_architecture"
QUAD_BUSINESS_RULES = "business_rules"
QUAD_SETTLED_DECISIONS = "settled_decisions"
QUAD_OPEN_QUESTIONS = "open_questions"

VALID_QUADRANTS: Set[str] = {
    QUAD_TECHNICAL_ARCHITECTURE,
    QUAD_BUSINESS_RULES,
    QUAD_SETTLED_DECISIONS,
    QUAD_OPEN_QUESTIONS,
}

REBASE_SYSTEM_PROMPT = """You are the Epistemological Memory Rebase Engine for OwlThread.
Your responsibility is to maintain an accurate, non-contradictory graph of developer context partitioned across 4 quadrants:
- technical_architecture: Frameworks, protocols, structural patterns, systemic constraints.
- business_rules: Domain specifications, licensing rules, pricing models, operational boundaries.
- settled_decisions: Finalized team agreements, trade-offs, chosen implementation options.
- open_questions: Unresolved spikes, investigations, technical uncertainties.

Evaluate the Candidate Fact against Existing Memories in the quadrant and output strict JSON adhering to:
{
  "action": "ADD" | "UPDATE" | "SUPERSEDE" | "NOOP",
  "target_memory_id": <int id or null>,
  "statement": "<final clear declarative summary>",
  "conflict_rationale": "<clear explanation of contradiction if SUPERSEDE, otherwise null>"
}

Rules:
- ADD: Candidate fact introduces new knowledge that does not duplicate or contradict existing memories.
- UPDATE: Candidate fact refines, clarifies, or appends details to an existing memory without reversing its conclusion. Must supply target_memory_id.
- SUPERSEDE: Candidate fact directly contradicts, invalidates, or reverses an existing memory (e.g. switched technologies, reversed policy, answered a question). Must supply target_memory_id and conflict_rationale.
- NOOP: Candidate fact is already represented by existing memories, or is less detailed/transient noise.

Operation Selection Guidelines (adapted from Mem0 memory management):

1. **ADD**: When the candidate fact contains new architectural, domain, decision, or open question knowledge not present in memory.
- Example:
  Existing Memories:
    [{"id": 1, "statement": "Database uses SQLite with WAL mode"}]
  Candidate Fact: "API endpoints are secured using JWT Bearer tokens."
  Output:
    {
      "action": "ADD",
      "target_memory_id": null,
      "statement": "API endpoints are secured using JWT Bearer tokens.",
      "conflict_rationale": null
    }

2. **UPDATE**: When the candidate fact refers to an existing memory and refines, enriches, or clarifies it without contradicting or reversing its premise. Keep the same ID.
- Example:
  Existing Memories:
    [{"id": 1, "statement": "Database uses SQLite"}]
  Candidate Fact: "Database uses SQLite configured with PRAGMA journal_mode=WAL and busy_timeout=5000."
  Output:
    {
      "action": "UPDATE",
      "target_memory_id": 1,
      "statement": "Database uses SQLite configured with PRAGMA journal_mode=WAL and busy_timeout=5000.",
      "conflict_rationale": null
    }

3. **SUPERSEDE**: When the candidate fact directly contradicts, invalidates, or replaces an existing memory (e.g. switched technologies, reversed a decision, answered an open question).
  Unlike destructive deletion, in our epistemological schema the old memory is marked superseded and preserved in the lineage graph.
- Example (a) - Tech stack migration:
  Existing Memories:
    [{"id": 2, "statement": "Decision: Use PayPal for payments."}]
  Candidate Fact: "Decision: Migrated from PayPal to Stripe Checkout."
  Output:
    {
      "action": "SUPERSEDE",
      "target_memory_id": 2,
      "statement": "Decision: Migrated from PayPal to Stripe Checkout.",
      "conflict_rationale": "Replaced PayPal payment processing with Stripe Checkout."
    }
- Example (b) - Resolving an open question:
  Existing Memories:
    [{"id": 3, "statement": "TBD: Should we use WebSockets or SSE for real-time clipboard sync?"}]
  Candidate Fact: "Resolved: Chose WebSockets over SSE for bidirectional low-latency clipboard sync."
  Output:
    {
      "action": "SUPERSEDE",
      "target_memory_id": 3,
      "statement": "Chose WebSockets over SSE for bidirectional low-latency clipboard sync.",
      "conflict_rationale": "Resolved open question by selecting WebSockets."
    }

4. **NOOP**: When the candidate fact conveys information already captured in existing memories, or is redundant noise.
- Example:
  Existing Memories:
    [{"id": 1, "statement": "Database uses SQLite with WAL mode"}]
  Candidate Fact: "We are running SQLite database."
  Output:
    {
      "action": "NOOP",
      "target_memory_id": 1,
      "statement": "Database uses SQLite with WAL mode",
      "conflict_rationale": null
    }"""


# ---------------------------------------------------------------------------
# Pure Python Candidate Ranking (Zero Vector DB Dependency)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "for", "in", "on", "at",
    "by", "with", "from", "and", "or", "not", "that", "this", "it", "we", "our",
    "you", "your", "be", "as", "of", "do", "will", "can", "has", "have", "had",
    "using", "used", "use", "should", "would", "could", "into"
}

_SUPERSEDE_CUES = [
    "switched from", "migrated from", "replaced", "instead of", "replaces",
    "updated decision", "no longer using", "deprecated", "answered:", "resolved:",
    "chose", "chosen over", "abandoned", "superseded", "swapped"
]


def tokenize_text(text: str) -> Set[str]:
    """Extract normalized alphanumeric tokens, excluding common stopwords."""
    words = re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def rank_candidates_pure_python(
    candidate_fact: str,
    existing_memories: List[Dict[str, Any]],
    max_candidates: int = 20
) -> List[Dict[str, Any]]:
    """
    Pure Python lexical and semantic overlap ranking without external vector DB.
    
    Ranks existing memories within the target (project_id, quadrant) based on:
    1. Keyword intersection and Jaccard similarity.
    2. Supersede cue boost (words appearing near directional replacement terms).
    3. Recency bias (higher ID = more recent context).
    """
    if not existing_memories:
        return []
    if len(existing_memories) <= max_candidates:
        return existing_memories

    cand_tokens = tokenize_text(candidate_fact)
    cand_lower = candidate_fact.lower()
    has_supersede_cue = any(cue in cand_lower for cue in _SUPERSEDE_CUES)

    scored: List[Tuple[float, Dict[str, Any]]] = []
    max_id = max((m.get("id", 0) for m in existing_memories), default=1) or 1

    for mem in existing_memories:
        text = f"{mem.get('summary', '')} {mem.get('raw_text', '')}"
        mem_tokens = tokenize_text(text)

        intersection = cand_tokens.intersection(mem_tokens)
        union = cand_tokens.union(mem_tokens)

        jaccard = len(intersection) / len(union) if union else 0.0
        overlap_count = len(intersection)

        # Recency score normalized between 0.0 and 0.2
        recency_boost = (mem.get("id", 0) / max_id) * 0.2

        # Cue boost if candidate explicitly hints at migration/replacement of shared topic
        cue_boost = 0.5 if (has_supersede_cue and overlap_count >= 1) else 0.0

        total_score = (jaccard * 1.5) + (overlap_count * 0.3) + cue_boost + recency_boost
        scored.append((total_score, mem))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:max_candidates]]


# ---------------------------------------------------------------------------
# Pure Python Ollama Client (Zero LangChain Dependency)
# ---------------------------------------------------------------------------

def call_ollama_chat(
    system_prompt: str,
    user_prompt: str,
    ollama_host: str = "http://localhost:11434",
    model: str = "llama3",
    timeout: float = 30.0,
    temperature: float = 0.0,
) -> Optional[str]:
    """
    Direct HTTP completion against Ollama with native JSON mode.
    
    Zero LangChain or external API dependencies — standard library urllib only.
    Tries native Ollama `/api/chat` (with format="json"), and falls back to
    `/v1/chat/completions` if `/api/chat` is not mounted.
    """
    clean_host = (ollama_host or "http://localhost:11434").strip().rstrip("/")
    api_url = f"{clean_host}/api/chat"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
        },
    }

    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "message" in data and "content" in data["message"]:
                return data["message"]["content"].strip()
            if "response" in data:
                return data["response"].strip()
    except urllib.error.HTTPError as err:
        if err.code == 404:
            # Try OpenAI-compatible endpoint on Ollama
            v1_url = f"{clean_host}/v1/chat/completions"
            v1_payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            v1_req = urllib.request.Request(
                v1_url,
                data=json.dumps(v1_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(v1_req, timeout=timeout) as v1_resp:
                v1_data = json.loads(v1_resp.read().decode("utf-8"))
                return v1_data["choices"][0]["message"]["content"].strip()
        raise

    return None


# ---------------------------------------------------------------------------
# Decision Parser & Normalizer
# ---------------------------------------------------------------------------

def parse_rebase_decision(response_text: str, valid_ids: Set[int]) -> Optional[Dict[str, Any]]:
    """
    Parse structured 4-action decision JSON from model output.
    
    Robustly handles:
    - Standard format: {"action": "ADD|UPDATE|SUPERSEDE|NOOP", "target_memory_id": ...}
    - Mem0 mappings: "DELETE" -> "SUPERSEDE", "NONE" -> "NOOP"
    - Legacy / test format: {"supersedes_id": ..., "reason": ...}
    - Markdown JSON code fences.
    """
    if not response_text:
        return None

    clean = response_text.strip()
    if "```" in clean:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.DOTALL)
        if match:
            clean = match.group(1)

    parsed_obj: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            parsed_obj = data
    except Exception:
        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(clean[start:end + 1])
                if isinstance(data, dict):
                    parsed_obj = data
            except Exception:
                pass

    if parsed_obj is None:
        return None

    # 1. Check for legacy/mock format: {"supersedes_id": 123, "reason": "..."}
    if "supersedes_id" in parsed_obj and "action" not in parsed_obj:
        sid = parsed_obj.get("supersedes_id")
        target_id = int(sid) if sid is not None and str(sid).isdigit() else None
        if target_id is not None and valid_ids and target_id not in valid_ids:
            target_id = None
        action = "SUPERSEDE" if target_id is not None else "ADD"
        return {
            "action": action,
            "target_memory_id": target_id,
            "statement": str(parsed_obj.get("statement") or parsed_obj.get("reason") or "").strip(),
            "conflict_rationale": str(parsed_obj.get("reason") or parsed_obj.get("conflict_rationale") or "").strip() or None,
        }

    # 2. Standard format with Mem0 action compatibility
    raw_action = str(parsed_obj.get("action", "")).upper()
    if raw_action == "DELETE":
        raw_action = "SUPERSEDE"
    elif raw_action in ("NONE", "NO_CHANGE"):
        raw_action = "NOOP"

    if raw_action not in ("ADD", "UPDATE", "SUPERSEDE", "NOOP"):
        return None

    raw_tid = parsed_obj.get("target_memory_id")
    if raw_tid is None:
        raw_tid = parsed_obj.get("target_id") or parsed_obj.get("supersedes_id")

    target_id = int(raw_tid) if raw_tid is not None and str(raw_tid).isdigit() else None
    if target_id is not None and valid_ids and target_id not in valid_ids:
        target_id = None

    statement = str(parsed_obj.get("statement") or "").strip()
    rationale = str(parsed_obj.get("conflict_rationale") or parsed_obj.get("reason") or "").strip() or None

    return {
        "action": raw_action,
        "target_memory_id": target_id,
        "statement": statement,
        "conflict_rationale": rationale,
    }


def heuristic_rebase_action(
    candidate_fact: str,
    existing_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Deterministic rule-based rebase decision for offline fallback.
    """
    cand_lower = candidate_fact.strip().lower()

    # 1. Check for near-identical duplicate -> NOOP
    for exist in existing_items:
        old_sum = (exist.get("summary") or "").strip().lower()
        if old_sum and (old_sum == cand_lower or (len(cand_lower) > 20 and cand_lower in old_sum)):
            return {"action": "NOOP", "target_memory_id": exist["id"], "statement": candidate_fact, "conflict_rationale": None}

    # 2. Check for explicit supersede cues
    cand_tokens = tokenize_text(cand_lower)
    has_cue = any(cue in cand_lower for cue in _SUPERSEDE_CUES)

    for exist in existing_items:
        old_text = f"{exist.get('summary', '')} {exist.get('raw_text', '')}".lower()
        old_tokens = tokenize_text(old_text)
        overlap = cand_tokens.intersection(old_tokens)

        if has_cue and len(overlap) >= 1:
            matched_words = ", ".join(list(overlap)[:3])
            return {
                "action": "SUPERSEDE",
                "target_memory_id": exist["id"],
                "statement": candidate_fact,
                "conflict_rationale": f"Superseded prior entry based on updated decision regarding: {matched_words}"
            }

    # 3. Default to ADD
    return {"action": "ADD", "target_memory_id": None, "statement": candidate_fact, "conflict_rationale": None}


# ---------------------------------------------------------------------------
# Core Pure Python + Ollama Rebase Function
# ---------------------------------------------------------------------------

def rebase_memory(
    db: Union[Database, sqlite3.Connection, str, Path],
    project_id: int,
    quadrant: str,
    candidate_fact: str,
    source_app: str = "ollama_rebase",
    source_snippet: Optional[str] = None,
    ollama_host: str = "http://localhost:11434",
    model: str = "llama3",
    timeout: float = 30.0,
    timestamp: Optional[str] = None,
    fallback_to_heuristic: bool = True,
) -> Dict[str, Any]:
    """
    Pure Python + Ollama rebase function that outputs ADD, UPDATE, SUPERSEDE, or NOOP
    into OwlThread's 4-quadrant SQLite schema.
    
    Architecture:
    - Zero external vector database: Candidate memories are retrieved using SQLite
      partition indexing (project_id + quadrant + status='active') and pure Python
      lexical/BM25 relevance ranking.
    - Zero LangChain dependency: Communicates with local Ollama via native urllib.request
      and strict JSON mode (format="json").
    - Epistemological graph integrity:
      - ADD: Inserts a new active memory row.
      - UPDATE: Enriches an existing active memory in-place, preserving its ID.
      - SUPERSEDE: Inserts the new active memory, marks predecessor as 'superseded'
        with foreign key pointer, and logs a directed edge in memory_lineage with
        conflict rationale.
      - NOOP: Discards duplicate or redundant facts without database mutation.
      
    Returns:
        Dict with keys: action, entry_id, target_memory_id, statement, conflict_rationale, quadrant, project_id.
    """
    if not candidate_fact or not candidate_fact.strip():
        raise ValueError("candidate_fact must not be empty.")

    # 1. Normalize quadrant
    norm_quadrant = quadrant.strip() if quadrant else QUAD_TECHNICAL_ARCHITECTURE
    if norm_quadrant not in VALID_QUADRANTS:
        norm_quadrant = QUAD_TECHNICAL_ARCHITECTURE

    # 2. Resolve Database wrapper
    db_obj: Database
    if isinstance(db, Database):
        db_obj = db
    elif isinstance(db, (str, Path)):
        db_obj = Database(str(db))
    else:
        db_obj = Database()

    raw_text = source_snippet or candidate_fact

    # 3. Retrieve candidates using SQLite partition indexing (No Vector DB)
    all_active = db_obj.get_active_entries_for_rebase(
        project_id=project_id,
        quadrant=norm_quadrant,
        limit=50
    )

    # 4. Pure Python candidate ranking
    candidate_pool = rank_candidates_pure_python(candidate_fact, all_active, max_candidates=20)
    valid_ids = {e["id"] for e in candidate_pool}

    decision: Optional[Dict[str, Any]] = None

    # 5. Call Ollama (if existing items present to compare against)
    if not candidate_pool:
        decision = {
            "action": "ADD",
            "target_memory_id": None,
            "statement": candidate_fact,
            "conflict_rationale": None,
        }
    else:
        payload = {
            "target_quadrant": norm_quadrant,
            "candidate_fact": candidate_fact,
            "existing_memories": [
                {"id": e["id"], "statement": e.get("summary") or e.get("raw_text", "")[:140]}
                for e in candidate_pool
            ],
        }
        user_prompt = json.dumps(payload, ensure_ascii=False)

        try:
            ollama_response = call_ollama_chat(
                system_prompt=REBASE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                ollama_host=ollama_host,
                model=model,
                timeout=timeout,
                temperature=0.0,
            )
            if ollama_response:
                decision = parse_rebase_decision(ollama_response, valid_ids)
        except Exception as e:
            logger.warning("Ollama rebase call failed (%s). Falling back to heuristic.", e)

        # Fallback to deterministic heuristic if Ollama is unreachable or response invalid
        if decision is None and fallback_to_heuristic:
            decision = heuristic_rebase_action(candidate_fact, candidate_pool)

    if decision is None:
        decision = {"action": "ADD", "target_memory_id": None, "statement": candidate_fact, "conflict_rationale": None}

    action = decision.get("action", "ADD")
    target_id = decision.get("target_memory_id")
    statement = decision.get("statement") or candidate_fact
    conflict_rationale = decision.get("conflict_rationale")

    # 6. Execute 4-Action mutation against SQLite Schema
    entry_id: Optional[int] = None

    if action == "NOOP":
        # Case 1: NOOP — Discard redundant fact without database modification
        logger.info("Rebase [NOOP]: Fact already captured in memory #%s (%s)", target_id, statement[:60])
        return {
            "action": "NOOP",
            "entry_id": None,
            "target_memory_id": target_id,
            "statement": statement,
            "conflict_rationale": None,
            "quadrant": norm_quadrant,
            "project_id": project_id,
        }

    elif action == "UPDATE" and target_id is not None:
        # Case 2: UPDATE — In-place statement enrichment preserving memory ID
        db_obj.update_entry_statement(entry_id=target_id, summary=statement, raw_text=raw_text)
        logger.info("Rebase [UPDATE]: Enriched memory #%d in-place: %s", target_id, statement[:60])
        return {
            "action": "UPDATE",
            "entry_id": target_id,
            "target_memory_id": target_id,
            "statement": statement,
            "conflict_rationale": None,
            "quadrant": norm_quadrant,
            "project_id": project_id,
        }

    elif action == "SUPERSEDE" and target_id is not None:
        # Case 3: SUPERSEDE — Invalidate predecessor with lineage DAG link and insert active successor
        entry_id = db_obj.insert_entry(
            raw_text=raw_text,
            source_app=source_app,
            project_id=project_id,
            timestamp=timestamp,
            quadrant=norm_quadrant,
            summary=statement,
            status="active",
            superseded_by=None,
            embedding=None,
        )
        rationale = conflict_rationale or "Superseded by subsequent architectural update."
        db_obj.supersede_entry(old_entry_id=target_id, new_entry_id=entry_id, rationale=rationale)
        logger.info(
            "Rebase [SUPERSEDE]: Successor #%d superseded #%d. Rationale: %s",
            entry_id, target_id, rationale
        )
        return {
            "action": "SUPERSEDE",
            "entry_id": entry_id,
            "target_memory_id": target_id,
            "statement": statement,
            "conflict_rationale": rationale,
            "quadrant": norm_quadrant,
            "project_id": project_id,
        }

    else:
        # Case 4: ADD — Insert new active memory entry
        entry_id = db_obj.insert_entry(
            raw_text=raw_text,
            source_app=source_app,
            project_id=project_id,
            timestamp=timestamp,
            quadrant=norm_quadrant,
            summary=statement,
            status="active",
            superseded_by=None,
            embedding=None,
        )
        logger.info("Rebase [ADD]: Inserted new memory #%d into %s: %s", entry_id, norm_quadrant, statement[:60])
        return {
            "action": "ADD",
            "entry_id": entry_id,
            "target_memory_id": None,
            "statement": statement,
            "conflict_rationale": None,
            "quadrant": norm_quadrant,
            "project_id": project_id,
        }


class RebaseEngine:
    """
    Coordinates semantic updates, lineage tracking, and contradiction invalidation
    across the 4-quadrant epistemological store.
    """

    def __init__(self, db: Database, llm_client: Optional[LLMClient] = None):
        self.db = db
        self.llm_client = llm_client or LLMClient()

    def process_item(
        self,
        project_id: int,
        source_app: str,
        item: Dict[str, Any],
        timestamp: Optional[str] = None
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Process a single extracted item through the 4-action rebase pipeline:
        - NOOP: Discard redundant fact.
        - ADD: Insert new active entry.
        - UPDATE: Refine existing active entry in-place.
        - SUPERSEDE: Mark predecessor as superseded with lineage link, and insert new active entry.
        
        Returns:
            Tuple of (new_or_updated_entry_id, superseded_entry_id or None)
        """
        quadrant = item.get("quadrant") or "technical_architecture"
        summary = item.get("summary", "")
        source_snippet = item.get("source_snippet", "")
        raw_text = source_snippet or summary

        # 1. Fetch active entries in same quadrant
        existing_active = self.db.get_active_entries_for_rebase(
            project_id=project_id,
            quadrant=quadrant,
            limit=20
        )

        decision = self._decide_rebase_action(item, existing_active)
        action = decision.get("action", "ADD")
        target_id = decision.get("target_memory_id")
        final_statement = decision.get("statement") or summary
        rationale = decision.get("conflict_rationale") or "Superseded by subsequent architectural update."

        # Case A: NOOP (Duplicate or redundant)
        if action == "NOOP":
            logger.info("Rebase: Discarded redundant candidate fact (%s)", summary[:60])
            return None, None

        # Case B: UPDATE (In-place refinement)
        if action == "UPDATE" and target_id is not None:
            self.db.update_entry_statement(entry_id=target_id, summary=final_statement, raw_text=raw_text)
            logger.info("Rebase: Updated existing memory #%d in-place: %s", target_id, final_statement[:60])
            return target_id, None

        # Case C: SUPERSEDE (Contradiction / Reversal)
        if action == "SUPERSEDE" and target_id is not None:
            new_entry_id = self.db.insert_entry(
                raw_text=raw_text,
                source_app=source_app,
                project_id=project_id,
                timestamp=timestamp,
                quadrant=quadrant,
                summary=final_statement,
                status="active",
                superseded_by=None,
                embedding=None
            )
            self.db.supersede_entry(old_entry_id=target_id, new_entry_id=new_entry_id, rationale=rationale)
            logger.info(
                "Rebase: New entry #%d (%s) superseded old entry #%d. Rationale: %s",
                new_entry_id, final_statement[:50], target_id, rationale
            )
            return new_entry_id, target_id

        # Case D: ADD (Default insert new fact)
        new_entry_id = self.db.insert_entry(
            raw_text=raw_text,
            source_app=source_app,
            project_id=project_id,
            timestamp=timestamp,
            quadrant=quadrant,
            summary=final_statement,
            status="active",
            superseded_by=None,
            embedding=None
        )
        return new_entry_id, None

    def _decide_rebase_action(
        self,
        new_item: Dict[str, Any],
        existing_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Determine whether candidate fact is ADD, UPDATE, SUPERSEDE, or NOOP."""
        valid_ids = {e["id"] for e in existing_items}
        summary = new_item.get("summary") or ""

        if not existing_items:
            return {"action": "ADD", "target_memory_id": None, "statement": summary}

        if self.llm_client.is_available():
            try:
                payload = {
                    "target_quadrant": new_item.get("quadrant"),
                    "candidate_fact": summary,
                    "existing_memories": [
                        {"id": e["id"], "statement": e.get("summary") or e.get("raw_text", "")[:120]}
                        for e in existing_items
                    ]
                }
                user_prompt = json.dumps(payload, ensure_ascii=False)
                response = self.llm_client.chat_complete(
                    system_prompt=REBASE_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.0,
                    max_tokens=250,
                )
                parsed = self._parse_rebase_decision(response, valid_ids)
                if parsed is not None:
                    return parsed
            except Exception as e:
                logger.warning("LLM rebase check failed: %s. Using heuristic fallback.", e)

        return self._heuristic_rebase_action(new_item, existing_items)

    def rebase(
        self,
        project_id: int,
        quadrant: str,
        candidate_fact: str,
        source_app: str = "ollama_rebase",
        source_snippet: Optional[str] = None,
        ollama_host: str = "http://localhost:11434",
        model: str = "llama3",
    ) -> Dict[str, Any]:
        """Direct programmatic rebase helper using Ollama and SQLite."""
        return rebase_memory(
            db=self.db,
            project_id=project_id,
            quadrant=quadrant,
            candidate_fact=candidate_fact,
            source_app=source_app,
            source_snippet=source_snippet,
            ollama_host=ollama_host,
            model=model,
        )

    def _parse_rebase_decision(
        self,
        response_text: str,
        valid_ids: set
    ) -> Optional[Dict[str, Any]]:
        """Parse structured 4-action decision JSON from LLM response."""
        return parse_rebase_decision(response_text, valid_ids)

    def _heuristic_rebase_action(
        self,
        new_item: Dict[str, Any],
        existing_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Deterministic heuristic rebase action for offline execution."""
        summary = (new_item.get("summary") or "").strip()
        return heuristic_rebase_action(summary, existing_items)
