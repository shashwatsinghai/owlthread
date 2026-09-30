"""Unified model adapters using only urllib.request for HTTP."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)
QWEN_MEMORY_REASONING = "medium"
QWEN_MEMORY_TOKEN_BUDGET = 4096
DEFAULTS = {
    "openai": ("https://api.openai.com/v1","gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1","llama3"),
    "anthropic": ("https://api.anthropic.com/v1","claude-sonnet-4-5"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta","gemini-3.5-flash-lite"),
    "custom": ("",""),
    "groq": ("https://api.groq.com/openai/v1","qwen/qwen3.8-27b"),
    "fallback": ("",""),
}


class LLMClient:
    """Provider configuration can be changed in SQLite without restarting."""

    def __init__(self, provider: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, model: str | None = None, timeout: float = 15) -> None:
        self._lock = threading.RLock()
        self._db: Any = None
        self.timeout = timeout
        self.last_error: str | None = None
        self._retry_after = 0.0
        provider = provider or os.environ.get("OWLTHREAD_LLM_PROVIDER","")
        if provider in {"","auto","default"}:
            if api_key and api_key.startswith("gsk_"):
                provider = "groq"
            elif api_key and api_key.startswith("sk-ant-"):
                provider = "anthropic"
            elif api_key and api_key.startswith("AIza"):
                provider = "gemini"
            elif base_url and "11434" in base_url:
                provider = "ollama"
            elif api_key or os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            elif os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                provider = "gemini"
            elif os.environ.get("GROQ_API_KEY"):
                provider = "groq"
            else:
                provider = "fallback"
        self.provider = provider.lower()
        key_env = {"openai":"OPENAI_API_KEY","anthropic":"ANTHROPIC_API_KEY","gemini":"GEMINI_API_KEY","groq":"GROQ_API_KEY"}
        self.api_key = api_key if api_key is not None else os.environ.get(key_env.get(self.provider,""),"")
        if self.provider == "gemini" and not self.api_key:
            self.api_key = os.environ.get("GOOGLE_API_KEY","")
        self.base_url = base_url if base_url is not None else (os.environ.get("OPENAI_BASE_URL","") if self.provider == "openai" else "")
        self.model = model if model is not None else os.environ.get("OWLTHREAD_LLM_MODEL","")
        self._initial = (self.provider,self.api_key,self.base_url,self.model)

    def reload_from_db(self, db: Any) -> None:
        """An explicitly empty key/URL/model clears the previous value."""
        with self._lock:
            self._db = db
            settings = db.get_all_settings()
            values = tuple(settings.get(key,default) for key,default in zip(
                ("llm_provider","llm_api_key","llm_base_url","llm_model"),self._initial))
            if values != (self.provider,self.api_key,self.base_url,self.model):
                self._retry_after = 0
                self.last_error = None
            self.provider,self.api_key,self.base_url,self.model = values
            self.provider = (self.provider or "fallback").lower()

    def is_available(self) -> bool:
        with self._lock:
            if self._db is not None:
                self.reload_from_db(self._db)
            if self.provider == "ollama":
                return True
            if self.provider == "custom":
                return bool(self.base_url and self.model)
            return self.provider in {"openai","anthropic","gemini","groq"} and bool(self.api_key)

    def memory_generation_options(self, max_tokens: int) -> dict[str, Any]:
        """Durable decisions and evidence synthesis warrant more reasoning than labels."""
        with self._lock:
            model = self.model or DEFAULTS.get(self.provider, ("", ""))[1]
            if self.provider == "groq" and model == "qwen/qwen3.8-27b":
                return {"reasoning_effort": QWEN_MEMORY_REASONING,
                        "max_tokens": QWEN_MEMORY_TOKEN_BUDGET}
        return {"max_tokens": max_tokens}

    def _request(self, system: str, user: str, temperature: float, max_tokens: int,
                 reasoning_effort: str = "none") -> str:
        with self._lock:
            provider,key,base,model = self.provider,self.api_key,self.base_url,self.model
        default_base,default_model = DEFAULTS.get(provider,("",""))
        base = (base or default_base).rstrip("/")
        model = model or default_model
        if not model:
            raise ValueError("Set a model name in Settings")
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid provider base URL")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost","127.0.0.1","::1"}:
            raise ValueError("Remote model endpoints must use HTTPS")
        headers = {"Content-Type":"application/json", "User-Agent":"OwlThread/1.5"}
        payload: dict[str,Any]
        if provider == "anthropic":
            url = base + "/messages"
            headers.update({"x-api-key":key,"anthropic-version":"2023-06-01"})
            payload = {"model":model,"system":system,"messages":[{"role":"user","content":user}],"max_tokens":max_tokens}
        elif provider == "gemini":
            url = base+"/models/"+urllib.parse.quote(model.removeprefix("models/"),safe="")+":generateContent"
            headers["x-goog-api-key"] = key
            payload = {"systemInstruction":{"parts":[{"text":system}]},"contents":[{"role":"user","parts":[{"text":user}]}],
                       "generationConfig":{"temperature":temperature,"maxOutputTokens":max_tokens}}
        else:
            if provider == "ollama" and not base.endswith("/v1"):
                base += "/v1"
            url = base+"/chat/completions"
            if key:
                headers["Authorization"] = "Bearer "+key
            payload = {"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":user}]}
            official = provider == "openai" and urllib.parse.urlsplit(base).hostname == "api.openai.com"
            payload["max_completion_tokens" if official or provider == "groq" else "max_tokens"] = max_tokens
            if not (official and (model.startswith(("o1","o3","o4","gpt-5","gpt-6")))):
                payload["temperature"] = temperature
            if provider == "groq" and model == "qwen/qwen3.8-27b":
                if reasoning_effort not in {"none", "default", "low", "medium", "high"}:
                    raise ValueError("Invalid Qwen reasoning effort")
                # Keep reasoning out of JSON extraction and saved context briefs.
                payload.update(reasoning_effort=reasoning_effort, reasoning_format="parsed",
                               top_p=0.95, stream=False)
        request = urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),headers=headers,method="POST")
        # Never send provider keys through redirects or local requests through an ambient proxy.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req: Any, fp: Any, code: int, msg: str, hdrs: Any, newurl: str) -> None:
                return None
        handlers: list[Any] = [NoRedirect()]
        if parsed.hostname in {"localhost","127.0.0.1","::1"}:
            handlers.append(urllib.request.ProxyHandler({}))
        try:
            request_timeout = self.timeout
            if provider == "groq" and model == "qwen/qwen3.8-27b" and reasoning_effort in {"medium", "high"}:
                request_timeout = max(request_timeout, 45)
            with urllib.request.build_opener(*handlers).open(request,timeout=request_timeout) as response:
                data = json.loads(response.read(4_000_001).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise RuntimeError(f"{provider} returned HTTP {code}; check model, endpoint and credentials") from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise RuntimeError(f"{provider} could not be reached") from None
        if provider == "anthropic":
            text = "\n".join(b["text"] for b in data.get("content",[]) if b.get("type")=="text")
        elif provider == "gemini":
            text = "\n".join(p.get("text","") for p in data["candidates"][0]["content"]["parts"] if not p.get("thought"))
        else:
            text = data["choices"][0]["message"]["content"]
        if not isinstance(text,str) or not text.strip():
            raise ValueError("Model returned an empty response")
        return text.strip()

    def chat_complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.2,
                      max_tokens: int = 1500, raise_on_error: bool = False,
                      reasoning_effort: str = "none") -> str:
        if not self.is_available():
            if raise_on_error:
                raise RuntimeError("Model is offline or not configured")
            return self._fallback_chat(system_prompt,user_prompt)
        try:
            if time.monotonic() < self._retry_after:
                raise RuntimeError("Model unavailable; retrying after a short cooldown")
            result = self._request(system_prompt,user_prompt,temperature,max_tokens,reasoning_effort)
            self.last_error = None
            return result
        except Exception as exc:
            self.last_error = str(exc)
            self._retry_after = time.monotonic()+30
            if raise_on_error:
                raise
            logger.warning("Model unavailable; using local synthesis")
            return self._fallback_chat(system_prompt,user_prompt)

    def complete(self, system_prompt: str, user_message: str, max_tokens: int = 1000) -> str:
        return self.chat_complete(system_prompt,user_message,max_tokens=max_tokens)

    def test_connection(self) -> dict[str,Any]:
        start = time.perf_counter()
        error = ""
        try:
            if self.is_available():
                self._request("Reply briefly.","Say OwlThread connected.",0,40)
                self._retry_after = 0
            elif self.provider not in {"fallback","offline",""}:
                raise ValueError("Set provider credentials, endpoint and model in Settings")
        except Exception as exc:
            error = str(exc)
        return {"success":not error,"latency_ms":round((time.perf_counter()-start)*1000,1),
                "error":error,"provider":self.provider}

    def _heuristic_classify_intent(self, prompt: str) -> str:
        from owlthread.primer.classifier import IntentClassifier
        return IntentClassifier(self).heuristic_classify(prompt)

    def _fallback_chat(self, system_prompt: str, user_prompt: str) -> str:
        if "intent classifier" in system_prompt.lower():
            return self._heuristic_classify_intent(user_prompt)
        if "extract" in system_prompt.lower():
            from owlthread.extraction.extractor import MemoryExtractor
            return json.dumps(MemoryExtractor(self).heuristic_extract(user_prompt))
        return "## Local Context\n\n"+user_prompt
