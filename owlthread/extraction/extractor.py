"""LLM Memory Extractor for OwlThread Phase 2 extraction pipeline."""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from owlthread.primer.llm import LLMClient

logger = logging.getLogger(__name__)

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

EXTRACTION_SYSTEM_PROMPT = """You are OwlThread — an ambient memory engine for builders.

You receive raw captured text from diverse sources: AI coding chats (Cursor, Copilot, ChatGPT), terminal output, browser pages, handwritten notes, and team communications.

Your job: extract ONLY durable, reusable knowledge that will be valuable weeks or months later.
Skip: greetings, filler, debugging noise, transient errors, and anything not worth remembering.

Classify each extracted fact into exactly ONE quadrant:
• technical_architecture — how things are built: stack choices, data models, API designs, infrastructure, file structures, deployment setups.
• business_rules — product/company logic: pricing, positioning, policies, constraints, market decisions, user segments, compliance requirements.
• settled_decisions — explicit decisions that were finalized, with reasoning if stated. These are commitments the team made.
• open_questions — unresolved items flagged for future decision. Things marked "TBD", "decide later", or debated without resolution.

Output format: strict JSON array of objects, each with:
  {"quadrant": "<one_of_four>", "summary": "<≤20 words>", "source_snippet": "<relevant excerpt>"}

Rules:
- Never force an entry. Return [] if nothing qualifies.
- Summaries must be actionable and specific, not vague.
- One fact per entry. Don't merge unrelated facts.
- Prefer precision over recall — missing a fact is better than hallucinating one."""


def clean_summary_word_count(summary: str, max_words: int = 20) -> str:
    """Ensure summary is under max_words words."""
    words = summary.strip().split()
    if len(words) > max_words:
        return " ".join(words[:max_words])
    return " ".join(words)


class MemoryExtractor:
    """
    Extracts durable, categorized knowledge items from raw capture text using LLM.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
        self.custom_system_prompt: Optional[str] = None

    @property
    def active_system_prompt(self) -> str:
        """Return custom prompt if set, otherwise the default."""
        return self.custom_system_prompt or EXTRACTION_SYSTEM_PROMPT

    def extract(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        Extract structured knowledge items from raw text.
        
        Returns:
            List of dicts: [{"quadrant": str, "summary": str, "source_snippet": str}, ...]
        """
        if not raw_text or not raw_text.strip():
            return []

        cleaned = raw_text.strip()

        if self.llm_client.is_available():
            try:
                response = self.llm_client.chat_complete(
                    system_prompt=self.active_system_prompt,
                    user_prompt=cleaned,
                    temperature=0.1,
                    max_tokens=1500,
                )
                items = self._parse_json_response(response)
                if items is not None:
                    return self._validate_and_normalize(items, cleaned)
            except Exception as e:
                logger.warning("LLM extraction failed: %s. Using heuristic fallback.", e)

        return self.heuristic_extract(cleaned)

    def _parse_json_response(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """Extract and parse JSON array from model output."""
        if not text:
            return None

        clean_text = text.strip()
        # Strip markdown code fences if present
        if "```" in clean_text:
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", clean_text, re.DOTALL)
            if match:
                clean_text = match.group(1)
            else:
                # Try finding brackets directly
                start = clean_text.find("[")
                end = clean_text.rfind("]")
                if start != -1 and end != -1:
                    clean_text = clean_text[start:end + 1]

        try:
            data = json.loads(clean_text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
        except Exception:
            # Try finding substring between '[' and ']'
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(text[start:end + 1])
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass

        return None

    def _validate_and_normalize(
        self,
        items: List[Dict[str, Any]],
        full_text: str
    ) -> List[Dict[str, Any]]:
        """Validate and normalize extracted entries."""
        valid_items = []
        for it in items:
            if not isinstance(it, dict):
                continue

            raw_quad = str(it.get("quadrant", "")).strip().lower()
            summary = str(it.get("summary", "")).strip()
            snippet = str(it.get("source_snippet", "")).strip()

            if not summary:
                continue

            # Normalize quadrant
            quad = self._normalize_quadrant(raw_quad)
            if not quad:
                continue

            clean_sum = clean_summary_word_count(summary, 20)
            if not snippet:
                snippet = full_text[:300]

            valid_items.append({
                "quadrant": quad,
                "summary": clean_sum,
                "source_snippet": snippet
            })

        return valid_items

    def _normalize_quadrant(self, quad_str: str) -> Optional[str]:
        """Map text or aliases to valid 4 quadrants."""
        q = quad_str.lower().replace("-", "_").replace(" ", "_")
        if q in VALID_QUADRANTS:
            return q
        if "tech" in q or "arch" in q or "stack" in q or "api" in q:
            return QUAD_TECHNICAL_ARCHITECTURE
        if "business" in q or "rule" in q or "pricing" in q or "market" in q:
            return QUAD_BUSINESS_RULES
        if "decision" in q or "settled" in q:
            return QUAD_SETTLED_DECISIONS
        if "question" in q or "open" in q or "todo" in q or "decide_later" in q:
            return QUAD_OPEN_QUESTIONS
        return None

    def heuristic_extract(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        Deterministic rule-based knowledge extractor fallback for offline execution.
        """
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        if not lines:
            return []

        # Skip obvious generic greetings or noise
        noise_lines = {"hi", "hello", "hey", "thanks", "ok", "okay", "test", "sure", "bye"}
        if len(lines) == 1 and lines[0].lower() in noise_lines:
            return []

        extracted = []

        # Patterns for quadrants
        for line in lines:
            lower = line.lower()

            # 1. Settled decisions
            if any(k in lower for k in ["decided to", "decision:", "settled on", "we chose", "standardized on", "agreed to", "will use"]):
                prefix = "" if lower.startswith("decision:") else "Decision: "
                summary = clean_summary_word_count(f"{prefix}{line}", 18)
                extracted.append({
                    "quadrant": QUAD_SETTLED_DECISIONS,
                    "summary": summary,
                    "source_snippet": line
                })

            # 2. Business rules
            elif any(k in lower for k in ["pricing", "tier", "$", "usd", "per month", "subscription", "customer policy", "refund", "terms", "business rule"]):
                prefix = "" if lower.startswith("business rule:") else "Business Rule: "
                summary = clean_summary_word_count(f"{prefix}{line}", 18)
                extracted.append({
                    "quadrant": QUAD_BUSINESS_RULES,
                    "summary": summary,
                    "source_snippet": line
                })

            # 3. Open questions
            elif any(k in lower for k in ["decide later", "todo:", "open question:", "should we", "need to decide", "unresolved", "tbd"]):
                prefix = "" if lower.startswith("open question:") else "Open Question: "
                summary = clean_summary_word_count(f"{prefix}{line}", 18)
                extracted.append({
                    "quadrant": QUAD_OPEN_QUESTIONS,
                    "summary": summary,
                    "source_snippet": line
                })

            # 4. Technical architecture
            elif any(k in lower for k in ["schema", "sqlite", "fastapi", "database", "api", "endpoint", "architecture", "stack", "model", "pipeline", "port", "table"]):
                prefix = "" if lower.startswith("architecture:") else "Architecture: "
                summary = clean_summary_word_count(f"{prefix}{line}", 18)
                extracted.append({
                    "quadrant": QUAD_TECHNICAL_ARCHITECTURE,
                    "summary": summary,
                    "source_snippet": line
                })

        # If no specific keyword triggered, create a clean high-level entry
        if not extracted and raw_text.strip():
            first_sentence = raw_text.splitlines()[0].split(".")[0].strip()
            summary = clean_summary_word_count(first_sentence or raw_text[:50], 16)
            extracted.append({
                "quadrant": QUAD_TECHNICAL_ARCHITECTURE,
                "summary": summary,
                "source_snippet": raw_text[:400]
            })

        return extracted

    def quick_classify(self, raw_text: str) -> tuple[str, str]:
        """
        Produce an immediate (quadrant, summary) pair for incoming captures.
        Guarantees that no entry has NULL quadrant or summary in the feed.
        """
        if not raw_text or not raw_text.strip():
            return (QUAD_TECHNICAL_ARCHITECTURE, "Empty capture")

        text = raw_text.strip()

        # If LLM is available, try a fast classification
        if self.llm_client.is_available():
            try:
                prompt = (
                    "Classify this text into exactly one category: "
                    "[technical_architecture, business_rules, settled_decisions, open_questions]. "
                    "Also provide a concise 6-12 word title summary.\n"
                    "Output format: CATEGORY | SUMMARY\n\n"
                    f"Text: {text[:600]}"
                )
                resp = self.llm_client.chat_complete(
                    system_prompt="You are a real-time memory classifier. Reply ONLY with: CATEGORY | SUMMARY",
                    user_prompt=prompt,
                    temperature=0.1,
                    max_tokens=60,
                )
                if "|" in resp:
                    cat_part, sum_part = resp.split("|", 1)
                    quad = self._normalize_quadrant(cat_part.strip())
                    sum_clean = clean_summary_word_count(sum_part.strip(), 16)
                    if quad and sum_clean:
                        return (quad, sum_clean)
            except Exception as e:
                logger.debug("Fast LLM classify fallback: %s", e)

        # Heuristic fast classify
        extracted = self.heuristic_extract(text)
        if extracted:
            first = extracted[0]
            return (first["quadrant"], first["summary"])

        # Smart fallback from content
        lower = text.lower()
        if any(k in lower for k in ["decided", "decision", "settled", "choice", "selected", "fixed"]):
            quad = QUAD_SETTLED_DECISIONS
        elif any(k in lower for k in ["price", "cost", "billing", "usd", "tier", "subscription", "refund", "client", "policy"]):
            quad = QUAD_BUSINESS_RULES
        elif any(k in lower for k in ["?", "why", "how", "todo", "issue", "bug", "question", "decide later"]):
            quad = QUAD_OPEN_QUESTIONS
        else:
            quad = QUAD_TECHNICAL_ARCHITECTURE

        first_line = text.splitlines()[0].strip()
        first_sentence = first_line.split(".")[0].strip()
        summary = clean_summary_word_count(first_sentence or text[:50], 14)
        return (quad, summary)
