"""Primer Generator compiling context primers from memory entries."""

import json
import logging
from typing import Any, Dict, List, Optional

from owlthread.primer.llm import LLMClient

logger = logging.getLogger(__name__)

PRIMER_SYSTEM_PROMPT = """You are OwlThread's Context Primer — you compile project memory into a focused brief tailored to what the user needs right now.

You receive: the user's request, an intent tag, and relevant memory entries from four quadrants (technical_architecture, business_rules, settled_decisions, open_questions).

Output rules by intent:
• dev_task → Concise technical brief. Lead with architecture and decisions directly relevant to the task. Flag any open questions that might block implementation. Ready to paste into a coding assistant as context.
• external_comms → Narrative summary for a non-technical reader (investor, partner, client). Lead with what the product does and why it matters. Avoid jargon and internal implementation detail.
• status_query → Direct, factual answer citing only relevant entries. Use timestamps and source attribution.
• other → Balanced summary across relevant quadrants.

Constraints:
- ONLY use information from the provided memory entries. Never invent facts.
- If memory is insufficient, say so plainly. Don't fill gaps with assumptions.
- Keep output under 500 words unless the query demands more.
- Use markdown formatting for readability."""


class PrimerGenerator:
    """Compiles context primers using LLM or structured offline synthesis."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
        self.custom_system_prompt: Optional[str] = None

    @property
    def active_system_prompt(self) -> str:
        """Return custom prompt if set, otherwise the default."""
        return self.custom_system_prompt or PRIMER_SYSTEM_PROMPT

    def generate(
        self,
        user_request: str,
        intent_tag: str,
        matched_entries: List[Dict[str, Any]],
    ) -> str:
        """
        Generate a tailored context primer for the user request and intent.
        
        Args:
            user_request: The user's input request.
            intent_tag: One of dev_task, external_comms, status_query, other.
            matched_entries: Ranked list of relevant memory entries.
            
        Returns:
            The compiled markdown context primer string.
        """
        if not matched_entries:
            return (
                f"**Intent:** `{intent_tag}`\n\n"
                f"Insufficient memory recorded in OwlThread for request: \"{user_request}\".\n"
                "No relevant memory entries were found across project memory quadrants to compile this primer."
            )

        user_prompt = self._format_user_prompt(user_request, intent_tag, matched_entries)

        if self.llm_client.is_available():
            try:
                result = self.llm_client.chat_complete(
                    system_prompt=self.active_system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.2,
                    max_tokens=1500,
                )
                if result and result.strip():
                    return result.strip()
            except Exception as e:
                logger.warning("LLM primer generation failed: %s. Using local synthesis.", e)

        return self._synthesize_offline_primer(user_request, intent_tag, matched_entries)

    def _format_user_prompt(
        self,
        user_request: str,
        intent_tag: str,
        matched_entries: List[Dict[str, Any]]
    ) -> str:
        """Format the user prompt containing request, intent, and memory entries."""
        lines = [
            f"User Request: {user_request}",
            f"Intent Tag: {intent_tag}",
            "",
            f"Relevant Memory Entries ({len(matched_entries)} entries retrieved):",
            "---",
        ]

        for idx, entry in enumerate(matched_entries, 1):
            eid = entry.get("id", idx)
            src = entry.get("source_app", "unknown")
            ts = entry.get("timestamp", "")
            quadrant = entry.get("quadrant") or "unclassified"
            summary = entry.get("summary") or ""
            raw_text = entry.get("raw_text", "").strip()

            entry_header = f"[Entry #{eid}] Quadrant: {quadrant} | Source: {src} | Timestamp: {ts}"
            if summary:
                entry_header += f" | Summary: {summary}"
            
            lines.append(entry_header)
            lines.append("Content:")
            lines.append(raw_text if raw_text else summary)
            lines.append("---")

        return "\n".join(lines)

    def _synthesize_offline_primer(
        self,
        user_request: str,
        intent_tag: str,
        matched_entries: List[Dict[str, Any]]
    ) -> str:
        """Deterministic, structured offline primer synthesis honoring the system prompt rules."""
        out = []

        if intent_tag == "dev_task":
            out.append(f"# Technical Brief: {user_request}\n")
            out.append("## Relevant Architecture & Settled Decisions")
            for e in matched_entries[:6]:
                src = e.get("source_app", "memory")
                summary = e.get("summary")
                text = e.get("raw_text", "").strip()
                display_content = summary if summary else "\n".join([f"> {line}" for line in text.splitlines()[:4]])
                out.append(f"- **[#{e.get('id')}] ({src})**: {display_content}")

            out.append("\n## Open Questions & Implementation Notes")
            out.append(f"- Target task: `{user_request}`")
            out.append(f"- Matched against {len(matched_entries)} active memory records.")

        elif intent_tag == "external_comms":
            out.append(f"# Executive Overview: {user_request}\n")
            out.append("## Narrative Summary")
            out.append("Based on the captured company and project memory, here is the high-level progress and context:\n")
            for e in matched_entries[:4]:
                summary = e.get("summary")
                text = e.get("raw_text", "").strip()
                clean_snippet = summary if summary else (text.splitlines()[0] if text.splitlines() else text)
                out.append(f"- {clean_snippet} *(Ref: #{e.get('id')})*")

            out.append("\n## What The Project Does & Value")
            out.append("OwlThread captures developer activity and decisions across local tools into an ambient memory engine.")

        elif intent_tag == "status_query":
            out.append(f"# Status Query: {user_request}\n")
            out.append("## Direct Status Answer")
            out.append(f"Found {len(matched_entries)} directly relevant active records:\n")
            for e in matched_entries[:5]:
                eid = e.get("id")
                ts = (e.get("timestamp") or "")[:19].replace("T", " ")
                src = e.get("source_app")
                summary = e.get("summary")
                text = e.get("raw_text", "").strip()
                summary_line = summary if summary else (text.splitlines()[0] if text.splitlines() else text)
                out.append(f"- **[{ts}] [#{eid}] ({src})**: {summary_line}")

        else:  # other
            out.append(f"# Context Primer: {user_request}\n")
            out.append(f"**Intent:** `{intent_tag}` | **Entries Citing:** {len(matched_entries)}\n")
            out.append("## Summary of Relevant Memory")
            for e in matched_entries[:6]:
                eid = e.get("id")
                src = e.get("source_app")
                summary = e.get("summary")
                text = e.get("raw_text", "").strip()
                out.append(f"### Entry #{eid} ({src}) - {summary or 'Record'}")
                out.append(f"```\n{text[:300]}\n```")

        return "\n".join(out)
