"""LLM Client integration for OwlThread."""

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM client supporting OpenAI-compatible, Anthropic, and Gemini endpoints,
    with a graceful fallback synthesizer when offline or without API keys.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.provider = (provider or os.environ.get("OWLTHREAD_LLM_PROVIDER") or "").lower()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.model = model or os.environ.get("OWLTHREAD_LLM_MODEL")
        self.timeout = timeout

        self._setup_provider()

    def _setup_provider(self) -> None:
        """Resolve active provider based on current credentials and config."""
        if not self.provider or self.provider in ("auto", "default"):
            if self.api_key and self.api_key.startswith("AIza"):
                self.provider = "gemini"
            elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                self.provider = "gemini"
            elif os.environ.get("ANTHROPIC_API_KEY"):
                self.provider = "anthropic"
            elif self.base_url and "11434" in self.base_url:
                self.provider = "ollama"
            elif self.api_key or self.base_url:
                self.provider = "openai"
            else:
                self.provider = "fallback"

    def reload_from_db(self, db: Any) -> None:
        """Reload credentials and model settings from SQLite database settings."""
        if not db:
            return
        db_provider = db.get_setting("llm_provider", "")
        db_key = db.get_setting("llm_api_key", "")
        db_url = db.get_setting("llm_base_url", "")
        db_model = db.get_setting("llm_model", "")

        if db_provider:
            self.provider = db_provider.lower().strip()
        if db_key:
            self.api_key = db_key.strip()
        if db_url:
            self.base_url = db_url.strip()
        if db_model:
            self.model = db_model.strip()
        self._setup_provider()

    def is_available(self) -> bool:
        """Return True if an external LLM provider is configured with credentials."""
        if self.provider == "ollama":
            return True
        return self.provider in ("openai", "anthropic", "gemini") and bool(self.api_key or self.base_url)

    def test_connection(self) -> tuple[bool, str]:
        """Test active configuration with a minimal prompt to verify connectivity."""
        if not self.is_available():
            if self.provider in ("fallback", "offline", ""):
                return (True, "Offline Heuristic Synthesizer is active (No API key required)")
            return (False, f"Missing API key or base URL for provider '{self.provider}'")

        try:
            prompt = "Say 'OwlThread Connected' in exactly 2 words."
            result = self.chat_complete(
                system_prompt="You are a connection tester. Reply concisely in 2 words.",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=20,
                raise_on_error=True,
            )
            model_info = self.model or "default"
            return (True, f"Successfully connected to {self.provider.upper()} ({model_info})")
        except Exception as e:
            return (False, f"{self.provider.upper()} error: {e}")

    def chat_complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        raise_on_error: bool = False,
    ) -> str:
        """
        Execute chat completion against configured LLM provider.
        Falls back to local heuristic synthesis if provider is not configured or fails.
        """
        if not self.is_available():
            return self._fallback_chat(system_prompt, user_prompt)

        try:
            if self.provider in ("openai", "ollama"):
                return self._call_openai(system_prompt, user_prompt, temperature, max_tokens)
            elif self.provider == "anthropic":
                return self._call_anthropic(system_prompt, user_prompt, temperature, max_tokens)
            elif self.provider == "gemini":
                return self._call_gemini(system_prompt, user_prompt, temperature, max_tokens)
            else:
                return self._fallback_chat(system_prompt, user_prompt)
        except Exception as e:
            if raise_on_error:
                raise
            logger.warning("LLM API call failed (%s): %s. Falling back to local synthesizer.", self.provider, e)
            return self._fallback_chat(system_prompt, user_prompt)

    def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        base = (self.base_url or "").strip().rstrip("/")
        if self.provider == "ollama":
            if not base:
                base = "http://localhost:11434/v1"
            elif not base.endswith("/v1"):
                base = f"{base}/v1"
        elif not base:
            base = "https://api.openai.com/v1"

        url = f"{base}/chat/completions"
        model_name = (self.model or "gpt-4o-mini").strip()
        api_key = (self.api_key or "").strip()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI API error (HTTP {err.code}): {err_msg or err.reason}")

    def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        url = "https://api.anthropic.com/v1/messages"
        model_name = (self.model or "claude-3-5-haiku-latest").strip()
        api_key = (self.api_key or "").strip()
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        is_claude_5 = any(m in model_name.lower() for m in ["sonnet-5", "opus-5", "fable-5"])
        payload = {
            "model": model_name,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
        }
        if is_claude_5:
            payload["thinking"] = {"type": "adaptive"}
        else:
            payload["temperature"] = temperature

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
                return "\n".join(text_blocks).strip()
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Anthropic API error (HTTP {err.code}): {err_msg or err.reason}")

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        model_name = (self.model or "gemini-2.0-flash").strip()
        if model_name.startswith("models/"):
            model_name = model_name[7:]
        api_key = (self.api_key or "").strip()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Gemini API error (HTTP {err.code}): {err_msg or err.reason}")

        candidates = data.get("candidates", [])
        if not candidates:
            feedback = data.get("promptFeedback", {})
            block_reason = feedback.get("blockReason")
            if block_reason:
                raise RuntimeError(f"Gemini blocked content: {block_reason}")
            raise RuntimeError("Gemini returned empty candidates list.")

        first_cand = candidates[0]
        content = first_cand.get("content", {})
        parts = content.get("parts", [])
        if not parts:
            finish_reason = first_cand.get("finishReason", "UNKNOWN")
            raise RuntimeError(f"Gemini response parts empty (finishReason: {finish_reason})")

        return parts[0].get("text", "").strip()

    def _fallback_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Local synthesizer fallback when no external LLM is reachable."""
        low_sys = system_prompt.lower()
        if "intent classifier" in low_sys or "tag the request" in low_sys or ("dev_task" in low_sys and len(user_prompt) < 500):
            return self._heuristic_classify_intent(user_prompt)
        
        return self._heuristic_synthesize_primer(user_prompt)

    def _heuristic_classify_intent(self, prompt: str) -> str:
        """Rule-based heuristic intent classifier."""
        text = prompt.lower()
        
        # dev_task cues
        dev_keywords = [
            "code", "coding", "dev", "bug", "fix", "feature", "integrate", "stripe", "billing",
            "api", "endpoint", "refactor", "database", "schema", "sqlite", "test", "unittest",
            "build", "install", "deploy", "git", "commit", "function", "class", "module", "script",
            "frontend", "backend", "fullstack", "ui", "component", "interface", "pr", "pull request",
            "patch", "error", "exception", "traceback", "debug", "python", "javascript", "typescript",
            "sql", "migrate", "migration"
        ]
        
        # external_comms cues
        comms_keywords = [
            "investor", "pitch", "deck", "email", "client", "customer", "partner", "founder",
            "send this idea", "announcement", "newsletter", "press", "tweet", "post", "blog",
            "stakeholder", "external", "message to", "reach out", "proposal", "executive summary",
            "non-technical", "market", "audience"
        ]
        
        # status_query cues
        status_keywords = [
            "audit", "status", "update", "state", "what is the status", "how is", "progress",
            "latest", "recent", "health", "check", "current state", "where are we", "summary of",
            "what changed", "overview", "metric", "report", "log", "entries", "new update"
        ]
        
        for kw in comms_keywords:
            if kw in text:
                return "external_comms"
                
        for kw in dev_keywords:
            if kw in text:
                return "dev_task"
                
        for kw in status_keywords:
            if kw in text:
                return "status_query"
                
        return "other"

    def _heuristic_synthesize_primer(self, prompt: str) -> str:
        """Generate structured markdown primer from prompt context when offline."""
        lines = prompt.splitlines()
        intent = "other"
        for line in lines:
            if line.startswith("Intent:"):
                intent = line.replace("Intent:", "").strip()
                break

        return f"[Offline Synthesizer - Intent: {intent}]\n" + prompt[:400]
