"""Validate urllib request shapes and errors without sending data to paid APIs."""
from __future__ import annotations
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock,patch
from owlthread.primer.llm import LLMClient


class ProviderAdapters(unittest.TestCase):
    def invoke(self, provider: str, reply: dict, **options: str) -> tuple[str,object]:
        client = LLMClient(provider=provider,api_key="test-key",**options)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(reply).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch("urllib.request.build_opener",return_value=opener):
            result = client.complete("system instructions","user context")
        return result,opener.open.call_args.args[0]

    def test_openai(self) -> None:
        text,req = self.invoke("openai",{"choices":[{"message":{"content":"A brief"}}]})
        self.assertEqual(text,"A brief")
        self.assertEqual(req.full_url,"https://api.openai.com/v1/chat/completions")
        payload = json.loads(req.data)
        self.assertEqual(payload["messages"][0]["role"],"system")
        self.assertEqual(payload["max_completion_tokens"],1000)
        self.assertEqual(req.get_header("Authorization"),"Bearer test-key")

    def test_ollama(self) -> None:
        _,req = self.invoke("ollama",{"choices":[{"message":{"content":"Local brief"}}]},base_url="http://localhost:11434",model="llama3")
        self.assertEqual(req.full_url,"http://localhost:11434/v1/chat/completions")
        self.assertEqual(json.loads(req.data)["model"],"llama3")
        self.assertIn("max_tokens",json.loads(req.data))

    def test_anthropic(self) -> None:
        text,req = self.invoke("anthropic",{"content":[{"type":"text","text":"First"},{"type":"thinking","thinking":"hidden"},{"type":"text","text":"Second"}]})
        self.assertEqual(text,"First\nSecond")
        self.assertEqual(req.get_header("Anthropic-version"),"2023-06-01")
        self.assertEqual(json.loads(req.data)["system"],"system instructions")

    def test_gemini(self) -> None:
        text,req = self.invoke("gemini",{"candidates":[{"content":{"parts":[{"text":"Thought","thought":True},{"text":"First"},{"text":"Second"}]}}]})
        self.assertEqual(text,"First\nSecond")
        self.assertNotIn("test-key",req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"),"test-key")
        self.assertIn("systemInstruction",json.loads(req.data))
        self.assertIn("/models/gemini-3.5-flash-lite:generateContent",req.full_url)

    def test_custom_base_model_and_no_key(self) -> None:
        client = LLMClient(provider="custom",api_key="",base_url="http://localhost:8080/v1",model="custom-model")
        self.assertTrue(client.is_available())

    def test_remote_http_rejected(self) -> None:
        client = LLMClient(provider="custom",base_url="http://example.com/v1",model="model")
        with self.assertRaisesRegex(ValueError,"HTTPS"):
            client.chat_complete("system","text",raise_on_error=True)

    def test_connection_reports_failure_without_fallback_success(self) -> None:
        client = LLMClient(provider="ollama")
        with patch.object(client,"_request",side_effect=RuntimeError("Cannot connect")):
            result = client.test_connection()
        self.assertFalse(result["success"])
        self.assertGreaterEqual(result["latency_ms"],0)
        self.assertIn("Cannot connect",result["error"])

    def test_http_error_does_not_expose_server_body_or_api_key(self) -> None:
        client = LLMClient(provider="openai",api_key="secret")
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError("https://example.com",401,"unauthorized",{},io.BytesIO(b"secret raw request"))
        with patch("urllib.request.build_opener",return_value=opener):
            result = client.test_connection()
        self.assertFalse(result["success"])
        self.assertIn("401",result["error"])
        self.assertNotIn("secret",result["error"])

    def test_offline_never_uses_network(self) -> None:
        client = LLMClient(provider="fallback")
        with patch("urllib.request.build_opener",side_effect=AssertionError("network")):
            self.assertTrue(client.test_connection()["success"])
