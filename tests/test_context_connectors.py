"""Bundled context behavior with deterministic provider fixtures, not live certification."""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from owlthread.db.database import Database
from owlthread.integrations.context import (CREDENTIAL_PREFIX, MAX_RESPONSE_BYTES, OPTIONS_PREFIX,
    STATE_PREFIX, ContextConnectorService, JsonResponse, ProviderError, ReadOnlyTransport, _NoRedirects)
from owlthread.integrations.registry import IntegrationRegistry
from owlthread.primer.search import MemorySearcher


ACCOUNT = "a" * 32
ZONE = "b" * 32
TOKEN = "fixture-context-token-123"


class FixtureTransport:
    def __init__(self, responses: dict[str, JsonResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []
        self.on_request = None

    def get(self, provider: str, path: str, token: str, query: dict | None = None) -> JsonResponse:
        self.calls.append((provider, path, query))
        if self.on_request:
            self.on_request()
        result = self.responses[path]
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


class ContextConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "context.db"))
        self.pid = self.db.get_or_create_project("Connector project")
        self.transport = FixtureTransport({
            "/repos/example/project": JsonResponse({"id": 1, "full_name": "example/project", "description": "Repository context", "default_branch": "main"}),
            "/repos/example/project/issues": JsonResponse([
                {"id": 2, "number": 2, "title": "Fix capture delivery", "body": "Extension context arrives offline", "state": "open"},
                {"id": 3, "number": 3, "title": "Pull request is not an issue capture", "pull_request": {"url": "irrelevant"}},
            ]),
            "/repos/example/project/pulls": JsonResponse([{ "id": 4, "number": 3, "title": "Improve Windows UX", "body": "Read-only provider context", "state": "open" }]),
            "/zones": JsonResponse([{ "id": ZONE, "account": {"id": ACCOUNT}, "name": "example.test", "status": "active" }]),
            f"/zones/{ZONE}/dns_records": JsonResponse([{ "id": "dns-id", "type": "A", "name": "example.test", "content": "192.0.2.1" }]),
            f"/accounts/{ACCOUNT}/workers/scripts": JsonResponse([{ "id": "context-worker", "modified_on": "2026-09-29" }]),
            f"/accounts/{ACCOUNT}/pages/projects": JsonResponse([{ "id": "pages-id", "name": "context-pages", "subdomain": "context.pages.dev" }]),
        })
        self.service = ContextConnectorService(self.db, transport=self.transport)

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def configure_github(self, scopes: list[str] | None = None, token: str | None = TOKEN) -> dict:
        return self.service.configure("github", options={"repository": "example/project"},
            scopes=scopes or ["repositories.read", "issues.read", "pull-requests.read"], project_id=self.pid, token=token)

    def test_setup_is_bundled_but_never_connected_without_a_provider_test(self) -> None:
        status = self.service.status("github")
        self.assertTrue(status["builtin"])
        self.assertFalse(status["connected"])
        self.assertFalse(status["credential_stored"])
        self.assertFalse(self.service.status("gmail")["builtin"])
        self.assertEqual(self.transport.calls, [])
        configured = self.configure_github(token=None)
        self.assertEqual(configured["connection_state"], "credentials_required")
        with self.assertRaises(ValueError):
            self.service.sync("github")
        self.assertEqual(self.transport.calls, [])

    def test_token_is_protected_and_omitted_from_status_and_settings_snapshot(self) -> None:
        status = self.configure_github()
        self.assertEqual(status["connection_state"], "unverified")
        self.assertTrue(status["can_execute"])
        self.assertNotIn(TOKEN, json.dumps(status))
        self.assertNotIn(CREDENTIAL_PREFIX + "github", self.db.get_all_settings())
        raw = self.db.execute_read("SELECT value FROM settings WHERE key=?", (CREDENTIAL_PREFIX + "github",))[0]["value"]
        if sys.platform == "win32":
            self.assertTrue(raw.startswith("dpapi:"))
            self.assertNotIn(TOKEN, raw)
        self.assertEqual(self.db.get_setting(CREDENTIAL_PREFIX + "github"), TOKEN)

    def test_authentication_test_reads_all_selected_scopes_without_importing(self) -> None:
        self.configure_github()
        result = self.service.test("github")
        self.assertTrue(result["ok"])
        self.assertTrue(result["status"]["connected"])
        self.assertTrue(result["status"]["verification_cached"])
        self.assertIsNotNone(result["status"]["last_checked_at"])
        self.assertEqual(self.db.pending_count(), 0)
        self.assertEqual(len(self.transport.calls), 3)

    def test_sync_imports_scoped_searchable_raw_context_and_deduplicates(self) -> None:
        self.configure_github()
        first = self.service.sync("github")
        self.assertEqual(first["imported_count"], 3)
        captures = self.db.get_unprocessed_captures()
        self.assertTrue(all(c["project_id"] == self.pid for c in captures))
        self.assertTrue(all(c["source_app"] == "integration:github" for c in captures))
        raw = "\n".join(c["raw_text"] for c in captures)
        self.assertNotIn("Pull request is not an issue capture", raw)
        self.assertNotIn(TOKEN, raw)
        self.assertIn("Fix capture delivery", raw)
        # Same durable raw FTS used by primers must find imported evidence immediately.
        self.assertTrue(MemorySearcher(self.db).search_captures("capture delivery", project_id=self.pid))
        second = self.service.sync("github")
        self.assertEqual(second["imported_count"], 0)
        self.assertEqual(second["duplicate_count"], 3)
        self.assertEqual(self.db.pending_count(), 3)
        self.assertIsNotNone(second["status"]["last_sync_at"])

    def test_no_ungranted_provider_endpoint_is_read(self) -> None:
        self.configure_github(["issues.read"])
        result = self.service.sync("github")
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual([call[1] for call in self.transport.calls], ["/repos/example/project/issues"])

    def test_cloudflare_account_zone_workers_and_pages_are_read_only(self) -> None:
        self.service.configure("cloudflare", options={"account_id": ACCOUNT, "zone_id": ZONE},
            scopes=["zones.read", "dns.read", "workers.read", "pages.read"], project_id=self.pid, token=TOKEN)
        result = self.service.sync("cloudflare", limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["imported_count"], 4)
        zone_request = next(call for call in self.transport.calls if call[1] == "/zones")
        self.assertEqual(zone_request[2]["account.id"], ACCOUNT)
        self.assertEqual(len(self.transport.calls), 4)
        dns_capture = next(json.loads(c["raw_text"]) for c in self.db.get_unprocessed_captures()
                           if json.loads(c["raw_text"])["scope"] == "dns.read")
        self.assertEqual(dns_capture["resource"], {"zone_id": ZONE})

    def test_scope_resource_and_project_validation_precedes_any_credential_write(self) -> None:
        cases = [
            {"options": {"repository": "https://github.com/example/project"}},
            {"options": {"repository": "example/.."}},
            {"scopes": ["issues.write"]}, {"scopes": ["issues.read", "issues.read"]},
            {"project_id": 99999}, {"project_id": True}, {"token": "bad\nvalue"},
        ]
        defaults = {"options": {"repository": "example/project"}, "scopes": ["issues.read"], "project_id": self.pid, "token": TOKEN}
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises((ValueError, PermissionError)):
                self.service.configure("github", **(defaults | changes))
            self.assertIsNone(self.db.get_setting(CREDENTIAL_PREFIX + "github"))
        with self.assertRaises(ValueError):
            self.service.configure("cloudflare", options={"account_id": ACCOUNT}, scopes=["dns.read"], project_id=self.pid, token=TOKEN)
        self.assertIsNone(self.db.get_setting(CREDENTIAL_PREFIX + "cloudflare"))

    def test_limit_validation_and_provider_pagination_are_explicit(self) -> None:
        self.configure_github(["issues.read"])
        for limit in (0, 101, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.service.sync("github", limit)
        self.transport.responses["/repos/example/project/issues"] = JsonResponse([{ "id": 2, "title": "one" }], has_more=True)
        result = self.service.sync("github", limit=1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["limit_per_scope"], 1)

    def test_provider_failure_marks_error_and_imports_nothing(self) -> None:
        self.configure_github()
        self.transport.responses["/repos/example/project/pulls"] = ProviderError("Provider denied access; check read permissions or rate limits")
        result = self.service.sync("github")
        self.assertFalse(result["ok"])
        self.assertEqual(result["imported_count"], 0)
        self.assertEqual(self.db.pending_count(), 0)
        self.assertFalse(result["status"]["connected"])
        self.assertEqual(result["status"]["connection_state"], "error")

    def test_read_grant_changed_during_request_cannot_import_or_verify(self) -> None:
        for method in (self.service.test, self.service.sync):
            self.configure_github(["repositories.read"])
            self.transport.on_request = lambda: IntegrationRegistry(self.db).configure("github", enabled=False, scopes=[], project_id=self.pid)
            with self.subTest(method=method.__name__), self.assertRaises(PermissionError):
                method("github")
            self.assertEqual(self.db.pending_count(), 0)
            self.assertIsNone(self.db.get_setting(STATE_PREFIX + "github"))

    def test_token_changed_during_request_cannot_verify_old_token(self) -> None:
        self.configure_github(["repositories.read"])
        self.transport.on_request = lambda: self.db.set_setting(CREDENTIAL_PREFIX + "github", "new-fixture-token")
        with self.assertRaises(PermissionError):
            self.service.test("github")
        self.assertFalse(self.service.status("github")["connected"])
        self.assertIsNone(self.db.get_setting(STATE_PREFIX + "github"))

    def test_project_changed_during_request_cannot_import_to_old_project(self) -> None:
        self.configure_github(["repositories.read"])
        other_project = self.db.get_or_create_project("Another project")
        self.transport.on_request = lambda: IntegrationRegistry(self.db).configure("github", enabled=True,
            scopes=["repositories.read"], project_id=other_project)
        with self.assertRaises(PermissionError):
            self.service.sync("github")
        self.assertEqual(self.db.pending_count(), 0)

    def test_database_failure_rolls_back_the_whole_import_and_receipts(self) -> None:
        self.configure_github(["issues.read"])
        self.transport.responses["/repos/example/project/issues"] = JsonResponse([
            {"id": 1, "title": "First record"}, {"id": 2, "title": "Fail second record"}])
        self.db.execute_write("""CREATE TRIGGER fixture_import_failure BEFORE INSERT ON capture_buffer
            WHEN new.raw_text LIKE '%Fail second record%' BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.sync("github")
        self.assertEqual(self.db.pending_count(), 0)
        self.assertEqual(self.db.execute_read("SELECT COUNT(*) AS n FROM capture_receipts")[0]["n"], 0)
        self.assertIsNone(self.db.get_setting(STATE_PREFIX + "github"))

    def test_cloudflare_does_not_import_zones_from_a_different_account(self) -> None:
        self.service.configure("cloudflare", options={"account_id": ACCOUNT}, scopes=["zones.read"],
            project_id=self.pid, token=TOKEN)
        self.transport.responses["/zones"] = JsonResponse([{ "id": ZONE, "account": {"id": "c" * 32}, "name": "unselected.test" }])
        result = self.service.sync("cloudflare")
        self.assertFalse(result["ok"])
        self.assertEqual(result["imported_count"], 0)
        self.assertIn("outside the selected account", result["error"])

    def test_unreadable_copied_credential_is_preserved_until_disconnect(self) -> None:
        self.configure_github(["repositories.read"])
        # Simulate ciphertext from a different Windows user without printing its value.
        self.db.execute_write("UPDATE settings SET value=? WHERE key=?", ("dpapi:invalid-copied-value", CREDENTIAL_PREFIX + "github"))
        status = self.service.status("github")
        self.assertEqual(status["connection_state"], "credential_unavailable")
        self.assertTrue(status["credential_stored"])
        self.assertFalse(status["can_execute"])
        self.assertEqual(self.db.execute_read("SELECT value FROM settings WHERE key=?", (CREDENTIAL_PREFIX + "github",))[0]["value"], "dpapi:invalid-copied-value")
        self.service.disconnect("github")
        self.assertFalse(self.service.status("github")["credential_stored"])

    def test_new_grants_and_verification_expiry_require_new_tests(self) -> None:
        self.configure_github(["repositories.read"])
        self.service.test("github")
        self.assertTrue(self.service.status("github")["connected"])
        self.configure_github(["issues.read"], token=None)
        self.assertFalse(self.service.status("github")["connected"])
        self.service.test("github")
        state = json.loads(self.db.get_setting(STATE_PREFIX + "github"))
        state["last_checked_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        self.db.set_setting(STATE_PREFIX + "github", json.dumps(state))
        self.assertEqual(self.service.status("github")["connection_state"], "verification_expired")

    def test_resource_mismatch_rejected_and_large_record_preflight_is_atomic(self) -> None:
        self.configure_github(["repositories.read"])
        self.transport.responses["/repos/example/project"] = JsonResponse({"full_name": "other/repository"})
        self.assertFalse(self.service.sync("github")["ok"])
        self.assertEqual(self.db.pending_count(), 0)
        self.configure_github(["issues.read"])
        self.transport.responses["/repos/example/project/issues"] = JsonResponse([
            {"id": 1, "title": "First would be fine"}, {"id": 2, "title": "x" * 70_000}])
        self.assertFalse(self.service.sync("github")["ok"])
        self.assertEqual(self.db.pending_count(), 0)

    def test_body_bounds_and_token_redaction(self) -> None:
        self.configure_github(["issues.read"])
        self.transport.responses["/repos/example/project/issues"] = JsonResponse([
            {"id": 2, "title": "Bounded context", "body": TOKEN + "x" * 20_000}])
        result = self.service.sync("github")
        self.assertTrue(result["truncated"])
        raw = self.db.get_unprocessed_captures()[0]["raw_text"]
        self.assertNotIn(TOKEN, raw)
        self.assertIn("[credential redacted]", raw)
        self.assertIn("[Body truncated by OwlThread]", raw)

    def test_disconnect_works_for_corrupt_options_without_touching_captures(self) -> None:
        self.configure_github(["repositories.read"])
        self.service.sync("github")
        self.db.set_setting(OPTIONS_PREFIX + "github", "invalid-json")
        result = self.service.disconnect("github")
        self.assertFalse(result["enabled"])
        self.assertFalse(result["connected"])
        self.assertFalse(result["credential_stored"])
        self.assertEqual(self.db.pending_count(), 1)


class TransportBoundaryTests(unittest.TestCase):
    def test_get_only_official_host_and_versioned_github_header(self) -> None:
        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"full_name":"example/project"}'
        with patch("owlthread.integrations.context.build_opener") as build:
            build.return_value.open.return_value = Response()
            ReadOnlyTransport().get("github", "/repos/example/project", TOKEN)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, "https://api.github.com/repos/example/project")
            self.assertEqual(request.headers["X-github-api-version"], "2026-03-10")
            self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 12)

    def test_redirects_never_forward_credentials(self) -> None:
        self.assertIsNone(_NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://other.test"))

    def test_http_error_never_echoes_provider_body_or_token_url(self) -> None:
        with patch("owlthread.integrations.context.build_opener") as build:
            build.return_value.open.side_effect = HTTPError("https://secret.test/" + TOKEN, 403, TOKEN, {}, None)
            with self.assertRaises(ProviderError) as error:
                ReadOnlyTransport().get("github", "/repos/example/project", TOKEN)
            self.assertNotIn(TOKEN, str(error.exception))
            self.assertIn("denied access", str(error.exception))

    def test_oversized_body_and_cloudflare_failed_envelope_are_rejected(self) -> None:
        class Response:
            headers = {}
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return self.body
        for body in (b"x" * (MAX_RESPONSE_BYTES + 1), b'{"success":false,"errors":[{"message":"secret"}]}'):
            with self.subTest(size=len(body)), patch("owlthread.integrations.context.build_opener") as build:
                build.return_value.open.return_value = Response(body)
                with self.assertRaises(ProviderError):
                    ReadOnlyTransport().get("cloudflare", "/zones", TOKEN)


if __name__ == "__main__":
    unittest.main()
