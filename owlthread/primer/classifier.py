"""Intent Classifier for OwlThread Query & Primer Engine."""

from __future__ import annotations

import logging
import re
from typing import Optional

from owlthread.primer.llm import LLMClient

logger = logging.getLogger(__name__)

INTENT_DEV_TASK = "dev_task"
INTENT_EXTERNAL_COMMS = "external_comms"
INTENT_STATUS_QUERY = "status_query"
INTENT_OTHER = "other"

VALID_INTENTS = {
    INTENT_DEV_TASK,
    INTENT_EXTERNAL_COMMS,
    INTENT_STATUS_QUERY,
    INTENT_OTHER,
}

CLASSIFIER_SYSTEM_PROMPT = """You are a fast, lightweight intent classifier for a project context engine.
Classify the user's free-text work request into EXACTLY ONE of these four categories:

1. dev_task: A coding, development, debugging, architectural, or technical implementation task (e.g. "integrate Stripe billing", "fix CORS error in fastAPI", "refactor SQLite connector").
2. external_comms: External communication, pitch, founder/investor update, marketing, client message, or non-technical presentation (e.g. "I want to send this idea to an investor", "draft customer pitch email", "write changelog for users").
3. status_query: A status check, audit, progress review, or summary of current system state (e.g. "audit new update", "what is the status of the capture engine", "how is the build progress", "audit recent commits").
4. other: Anything that does not clearly fit the above three categories.

Respond with ONLY the category identifier: dev_task, external_comms, status_query, or other. Do NOT provide explanation or quotes."""


class IntentClassifier:
    """Classifies user requests into dev_task, external_comms, status_query, or other."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def classify(self, user_request: str) -> str:
        """
        Classify user's free-text request into one of the 4 intent categories.
        
        Args:
            user_request: The user's input string.
            
        Returns:
            One of 'dev_task', 'external_comms', 'status_query', 'other'.
        """
        if not user_request or not user_request.strip():
            return INTENT_OTHER

        cleaned = user_request.strip()

        # Common work intents are deterministic and free. Ask a configured model
        # only for genuinely ambiguous text, so a normal primer needs at most the
        # single synthesis call made by PrimerGenerator.
        heuristic_intent = self.heuristic_classify(cleaned)
        if heuristic_intent != INTENT_OTHER:
            return heuristic_intent
        if not self.llm_client.is_available():
            return INTENT_OTHER

        # Run LLM classification only for the ambiguous remainder.
        try:
            raw_response = self.llm_client.chat_complete(
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                user_prompt=cleaned,
                temperature=0.0,
                max_tokens=20,
            )
            parsed_intent = self._parse_intent_response(raw_response)
            if parsed_intent in VALID_INTENTS:
                return parsed_intent
        except Exception as e:
            logger.warning("LLM intent classification failed: %s. Using heuristic fallback.", e)

        return self.heuristic_classify(cleaned)

    def _parse_intent_response(self, response: str) -> Optional[str]:
        """Normalize and parse LLM response into a valid intent string."""
        if not response:
            return None

        # Clean text
        text = response.strip().lower()
        # Remove punctuation / markdown backticks
        text = re.sub(r"[`'\"]", "", text)
        
        for intent in (INTENT_DEV_TASK, INTENT_EXTERNAL_COMMS, INTENT_STATUS_QUERY, INTENT_OTHER):
            if intent in text:
                return intent

        return None

    def heuristic_classify(self, user_request: str) -> str:
        """
        Deterministic rule-based intent classification fallback.
        """
        text = user_request.strip().lower()
        if re.search(r"\b(fix|debug|refactor|implement)\b", text):
            return INTENT_DEV_TASK
        if (re.search(r"\b(?:i(?:'m| am)?|we(?:'re| are)?|mai|main|hum)\b.{0,60}\b(?:going to |plan(?:ning)? to )?(?:build|create|make|develop)\b", text)
                or re.search(r"\b(?:mai|main|hum)\b.{0,80}\b(?:banana|banane|banaunga|banaungi|banayenge|bana rahe|bana raha|bana rahi)\b", text)
                or re.search(r"(?:मैं|हम).{0,80}(?:बनाने|बनाऊंगा|बनाऊंगी|बनाएंगे|बना रहा|बना रही)", text)):
            return INTENT_DEV_TASK
        if re.search(r"\bwhat (did|have) we decid", text):
            return INTENT_STATUS_QUERY

        # 1. External comms indicators
        comms_patterns = [
            r"\binvestor\b",
            r"\bpitch\b",
            r"\bdeck\b",
            r"\bemail\b",
            r"\bclient\b",
            r"\bcustomer\b",
            r"\bpartner\b",
            r"\bfounder\b",
            r"\bsend this idea\b",
            r"\bannouncement\b",
            r"\bnewsletter\b",
            r"\bpress\b",
            r"\btweet\b",
            r"\bpost\b",
            r"\bblog\b",
            r"\bstakeholder\b",
            r"\bmarketing\b",
            r"\bnon-technical\b",
            r"\bmessage to\b",
            r"\breach out\b",
            r"\bproposal\b",
            r"\bexecutive summary\b",
        ]
        if any(re.search(pat, text) for pat in comms_patterns):
            return INTENT_EXTERNAL_COMMS

        # 2. Status query indicators (check before dev tasks to capture "audit update", "how is progress", etc.)
        status_patterns = [
            r"\baudit\b",
            r"\bstatus\b",
            r"\bprogress\b",
            r"\bhealth\b",
            r"\bhow is\b",
            r"\bwhat is the\b",
            r"\bwhere are we\b",
            r"\bsummary of\b",
            r"\bwhat changed\b",
            r"\boverview\b",
            r"\breport\b",
            r"\bnew update\b",
            r"\bcurrent state\b",
            r"\bcheck latest\b",
        ]
        if any(re.search(pat, text) for pat in status_patterns):
            return INTENT_STATUS_QUERY

        # 3. Dev task indicators
        dev_patterns = [
            r"\bintegrat\w*\b",
            r"\bstripe\b",
            r"\bbilling\b",
            r"\bcode\b",
            r"\bcoding\b",
            r"\bdev\b",
            r"\bdevelop\w*\b",
            r"\bbug\b",
            r"\bfix\b",
            r"\bfeature\b",
            r"\bapi\b",
            r"\bendpoint\b",
            r"\brefactor\w*\b",
            r"\bdatabase\b",
            r"\bsqlite\b",
            r"\bschema\b",
            r"\btest\b",
            r"\bunittest\b",
            r"\bbuild\b",
            r"\binstall\b",
            r"\bdeploy\w*\b",
            r"\bgit\b",
            r"\bcommit\b",
            r"\bfunction\b",
            r"\bclass\b",
            r"\bmodule\b",
            r"\bscript\b",
            r"\bfrontend\b",
            r"\bbackend\b",
            r"\bui\b",
            r"\bcomponent\b",
            r"\binterface\b",
            r"\bpr\b",
            r"\bpull request\b",
            r"\bpatch\b",
            r"\berror\b",
            r"\bexception\b",
            r"\btraceback\b",
            r"\bdebug\b",
            r"\bpython\b",
            r"\bjavascript\b",
            r"\btypescript\b",
            r"\bsql\b",
            r"\bmigrat\w*\b",
            r"\bban(?:a|ana|ane|aunga|aungi|ayenge)\b",
        ]
        if any(re.search(pat, text) for pat in dev_patterns):
            return INTENT_DEV_TASK

        return INTENT_OTHER
