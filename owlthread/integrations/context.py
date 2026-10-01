"""Bundled, read-only context clients. Availability is separate from authentication.

Provider API references:
https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/list/
https://developers.cloudflare.com/api/resources/pages/subresources/projects/methods/list/
https://docs.github.com/en/rest/repos/repos
https://docs.github.com/en/rest/issues/issues
https://docs.github.com/en/rest/pulls/pulls
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from owlthread import __version__
from owlthread.db.database import get_iso_now
from owlthread.security import unprotect


CREDENTIAL_PREFIX = "integration_credential:"
OPTIONS_PREFIX = "integration_options:"
STATE_PREFIX = "integration_state:"
SUPPORTED_SCOPES = {
    "cloudflare": ("zones.read", "dns.read", "workers.read", "pages.read"),
    "github": ("repositories.read", "issues.read", "pull-requests.read"),
}
API_HOSTS = {
    "cloudflare": "https://api.cloudflare.com/client/v4",
    "github": "https://api.github.com",
}
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORD_CHARS = 64_000
VERIFICATION_TTL_SECONDS = 15 * 60
_CF_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.-]{1,100}\Z")


class ProviderError(RuntimeError):
    """A safe error with no response body, credential or exception URL."""


@dataclass(frozen=True)
class JsonResponse:
    data: Any
    has_more: bool = False


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        # Tokens must never follow redirects, including same-host redirects.
        return None


class ReadOnlyTransport:
    """GET only, fixed provider hosts, bounded bodies, finite network waits."""

    def get(self, provider: str, path: str, token: str,
            query: dict[str, Any] | None = None) -> JsonResponse:
        if provider not in API_HOSTS or not path.startswith("/") or any(c in path for c in "?#\\"):
            raise ValueError("Invalid provider request")
        url = API_HOSTS[provider] + path
        if query:
            url += "?" + urlencode(query)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json",
                   "User-Agent": "OwlThread-context/" + __version__}
        if provider == "github":
            headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
        try:
            with build_opener(_NoRedirects()).open(Request(url, headers=headers, method="GET"), timeout=12) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProviderError("Provider response is too large; narrow the selected account or repository")
                data = json.loads(body)
                has_more = 'rel="next"' in response.headers.get("Link", "")
        except HTTPError as error:
            error.close()
            if error.code == 401:
                message = "Provider rejected the token; enter a valid token and test again"
            elif error.code == 403:
                message = "Provider denied access; check read permissions or rate limits"
            elif error.code == 404:
                message = "Resource was not found or the token cannot access it"
            elif error.code == 429:
                message = "Provider rate limit reached; try again later"
            elif 300 <= error.code < 400:
                message = "Provider redirected the request; verify the selected resource"
            else:
                message = f"Provider request failed (HTTP {error.code}); try again later"
            raise ProviderError(message) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise ProviderError("Could not reach the provider; check the network and try again") from None
        except (ValueError, UnicodeError):
            raise ProviderError("Provider returned an invalid JSON response") from None
        if provider == "cloudflare":
            if not isinstance(data, dict) or data.get("success") is not True or "result" not in data:
                raise ProviderError("Cloudflare rejected the request; check token permissions and account IDs")
            info = data.get("result_info")
            if isinstance(info, dict):
                total_pages, page = info.get("total_pages"), info.get("page", 1)
                has_more = isinstance(total_pages, int) and isinstance(page, int) and total_pages > page
            data = data["result"]
        return JsonResponse(data, has_more)


def _json_setting(db: Any, prefix: str, integration_id: str) -> dict[str, Any]:
    raw = db.get_setting(prefix + integration_id)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _options(integration_id: str, value: Any, scopes: list[str] | tuple[str, ...]) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
        raise ValueError("Connector options must be text fields")
    if integration_id == "cloudflare":
        if set(value) - {"account_id", "zone_id"}:
            raise ValueError("Unsupported Cloudflare option")
        account = value.get("account_id", "").strip()
        zone = value.get("zone_id", "").strip()
        if not _CF_ID.fullmatch(account):
            raise ValueError("Cloudflare account_id must be its 32-character hexadecimal ID")
        if zone and not _CF_ID.fullmatch(zone):
            raise ValueError("Cloudflare zone_id must be its 32-character hexadecimal ID")
        if "dns.read" in scopes and not zone:
            raise ValueError("Select a Cloudflare zone_id to read DNS records")
        return {"account_id": account.lower(), "zone_id": zone.lower()}
    if set(value) != {"repository"} or not _REPOSITORY.fullmatch(value["repository"].strip()):
        raise ValueError("GitHub repository must use owner/name, without a URL")
    repository = value["repository"].strip()
    if any(part in {".", ".."} for part in repository.split("/")):
        raise ValueError("Invalid GitHub repository")
    return {"repository": repository}


def _raw_credential(db: Any, integration_id: str) -> str:
    rows = db.execute_read("SELECT value FROM settings WHERE key=?", (CREDENTIAL_PREFIX + integration_id,))
    return rows[0]["value"] if rows else ""


def _revision(db: Any, base: dict[str, Any], options: dict[str, Any]) -> str:
    # Include ciphertext, not plaintext; any local credential/grant change invalidates verification.
    return _revision_value(base, options, _raw_credential(db, base["id"]))


def _revision_value(base: dict[str, Any], options: dict[str, Any], credential: str) -> str:
    value = [base["enabled"], base["configured_scopes"], base["project_id"], options, credential]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def enrich_status(db: Any, base: dict[str, Any]) -> dict[str, Any]:
    """Local snapshot only. No network call or secret field is returned."""
    integration_id = base["id"]
    builtin = integration_id in SUPPORTED_SCOPES
    base.update({"builtin": builtin, "supported_scopes": list(SUPPORTED_SCOPES.get(integration_id, ()))})
    if not builtin:
        return base
    options = _json_setting(db, OPTIONS_PREFIX, integration_id)
    state = _json_setting(db, STATE_PREFIX, integration_id)
    key = CREDENTIAL_PREFIX + integration_id
    stored = bool(_raw_credential(db, integration_id))
    credential = db.get_setting(key, "") if stored else ""
    base.update({"credential_stored": stored, "options": options, "last_checked_at": None,
                 "last_sync_at": None, "last_error": None, "verification_cached": False})
    browser_auth = _json_setting(db, "integration_auth:", integration_id)
    base.update({"auth_method": browser_auth.get("method", "token"),
                 "signed_in": bool(credential) and browser_auth.get("method") == "browser"})
    if not base["configuration_valid"] or not base["enabled"]:
        return base
    if not credential:
        base["connection_state"] = "credential_unavailable" if stored else "credentials_required"
        return base
    if not base["project_id"]:
        base["connection_state"] = "project_required"
        return base
    if not base["configured_scopes"] or any(s not in SUPPORTED_SCOPES[integration_id] for s in base["configured_scopes"]):
        base["connection_state"] = "scopes_required"
        return base
    try:
        _options(integration_id, options, base["configured_scopes"])
    except ValueError:
        base["connection_state"] = "options_required"
        return base
    base.update({"can_execute": True, "connection_state": "unverified"})
    if state.get("revision") != _revision(db, base, options):
        return base
    base.update({"last_checked_at": state.get("last_checked_at"), "last_sync_at": state.get("last_sync_at"),
                 "last_error": state.get("last_error")})
    if state.get("last_error"):
        base["connection_state"] = "error"
        return base
    try:
        checked = datetime.fromisoformat(state["last_checked_at"])
        age = (datetime.now(timezone.utc) - checked).total_seconds()
        recent = 0 <= age <= VERIFICATION_TTL_SECONDS
    except (KeyError, TypeError, ValueError):
        recent = False
    base.update({"connected": recent, "verification_cached": recent,
                 "connection_state": "connected" if recent else "verification_expired"})
    return base


def _selected(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: item[key] for key in fields if key in item}


def _records(response: JsonResponse, scope: str, fields: tuple[str, ...], limit: int,
             *, skip_pull_requests: bool = False) -> tuple[list[dict[str, Any]], bool]:
    items = response.data
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ProviderError("Provider returned an unexpected list response")
    if skip_pull_requests:
        items = [item for item in items if "pull_request" not in item]
    records = [{"scope": scope, "data": _selected(item, fields)} for item in items[:limit]]
    return records, response.has_more or len(items) > limit


def _scope_resource(integration_id: str, scope: str, options: dict[str, str]) -> dict[str, str]:
    # DNS's API accepts an exact zone ID, independently of account-scoped APIs.
    if integration_id == "cloudflare":
        field = "zone_id" if scope == "dns.read" else "account_id"
        return {field: options[field]}
    return {"repository": options["repository"]}


class ContextConnectorService:
    """Local credential setup, explicit provider tests, and bounded raw-context imports."""

    def __init__(self, db: Any, *, transport: ReadOnlyTransport | None = None) -> None:
        self.db = db
        self.transport = transport or ReadOnlyTransport()

    def status(self, integration_id: str) -> dict[str, Any]:
        from owlthread.integrations.registry import IntegrationRegistry
        return IntegrationRegistry(self.db).status(integration_id)

    def configure(self, integration_id: str, *, options: dict[str, str], scopes: list[str],
                  project_id: int, token: str | None = None, enabled: bool = True) -> dict[str, Any]:
        if integration_id not in SUPPORTED_SCOPES:
            raise ValueError("This integration has no bundled context client")
        if type(enabled) is not bool or not isinstance(scopes, list) or not scopes or any(type(s) is not str for s in scopes):
            raise ValueError("Choose at least one exact read scope")
        if len(scopes) != len(set(scopes)) or any(s not in SUPPORTED_SCOPES[integration_id] for s in scopes):
            raise PermissionError("Bundled context connectors support only their listed read scopes")
        if type(project_id) is not int or project_id <= 0 or not self.db.get_project_by_id(project_id):
            raise ValueError("Select an existing OwlThread project for imported context")
        options = _options(integration_id, options, scopes)
        if token is not None:
            if not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise ValueError("API token must be text without spaces or control characters")
            # Prefix belongs to DatabaseManager's protected settings, never plain config.
            self.db.set_setting(CREDENTIAL_PREFIX + integration_id, token)
            self.db.set_setting("integration_auth:" + integration_id, "{}")
        self.db.set_setting(OPTIONS_PREFIX + integration_id, json.dumps(options, sort_keys=True))
        from owlthread.integrations.registry import IntegrationRegistry
        return IntegrationRegistry(self.db).configure(integration_id, enabled=enabled, scopes=scopes, project_id=project_id)

    def disconnect(self, integration_id: str) -> dict[str, Any]:
        """Explicit local disconnect also works when saved options or secrets are invalid."""
        if integration_id not in SUPPORTED_SCOPES:
            raise ValueError("This integration has no bundled context client")
        self.db.set_setting(CREDENTIAL_PREFIX + integration_id, "")
        self.db.set_setting("integration_auth:" + integration_id, "{}")
        from owlthread.integrations.registry import IntegrationRegistry
        return IntegrationRegistry(self.db).configure(integration_id, enabled=False, scopes=[], project_id=None)

    def _setup(self, integration_id: str) -> tuple[dict[str, Any], str, str]:
        status = self.status(integration_id)
        if integration_id not in SUPPORTED_SCOPES:
            raise ValueError("This integration has no bundled context client")
        if not status["can_execute"]:
            raise ValueError("Enable this connector and provide a token, read scopes, resource IDs and a project first")
        from owlthread.integrations.browser_login import refresh_browser_credential
        refresh_browser_credential(self.db,integration_id)
        status = self.status(integration_id)
        if not status["can_execute"]:
            raise ValueError("Connector setup changed during sign-in renewal; enable it and test or import again")
        # Read grant, options and encrypted token in one SQLite snapshot so the
        # revision always describes the exact credential used for the request.
        keys = [prefix + integration_id for prefix in ("integration_config:", OPTIONS_PREFIX, CREDENTIAL_PREFIX)]
        rows = self.db.execute_read("SELECT key,value FROM settings WHERE key IN (?,?,?)", tuple(keys))
        snapshot = {row["key"]: row["value"] for row in rows}
        try:
            grant = json.loads(snapshot[keys[0]])
            options = json.loads(snapshot[keys[1]])
            if grant != {"enabled": status["enabled"], "scopes": status["configured_scopes"], "project_id": status["project_id"]} or options != status["options"]:
                raise ValueError("Connector setup changed; test or import again")
            encrypted = snapshot[keys[2]]
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("Connector setup changed; test or import again") from None
        try:
            token = unprotect(encrypted)
        except RuntimeError:
            raise ValueError("The stored token is unavailable; enter it again in Connect") from None
        if not token:
            raise ValueError("The stored token is unavailable; enter it again in Connect")
        return status, token, _revision_value(status, options, encrypted)

    def _fetch(self, integration_id: str, status: dict[str, Any], token: str,
               limit: int) -> tuple[list[dict[str, Any]], bool]:
        records: list[dict[str, Any]] = []
        truncated = False
        options = _options(integration_id, status["options"], status["configured_scopes"])
        transport = self.transport
        if integration_id == "cloudflare":
            from owlthread.integrations.browser_login import is_cloudflare_oauth, CloudflareMcpTransport
            if is_cloudflare_oauth(token): transport = CloudflareMcpTransport()
        else:
            from owlthread.integrations.browser_login import is_github_oauth
            if is_github_oauth(token): token = json.loads(token)["access_token"]
        for scope in status["configured_scopes"]:
            if integration_id == "cloudflare":
                account, zone = options["account_id"], options["zone_id"]
                if scope == "zones.read":
                    response = transport.get(integration_id, "/zones", token,
                        {"account.id": account, "per_page": min(50, max(5, limit)), "page": 1})
                    # Defensive account isolation even if a provider/fixture ignores its filter.
                    if not isinstance(response.data, list) or any(not isinstance(item, dict) or
                        not isinstance(item.get("account"), dict) or item["account"].get("id") != account for item in response.data):
                        raise ProviderError("Cloudflare returned zones outside the selected account")
                    fields = ("id", "name", "status", "paused", "type", "name_servers", "created_on", "modified_on")
                elif scope == "dns.read":
                    response = transport.get(integration_id, f"/zones/{zone}/dns_records", token,
                        {"per_page": limit, "page": 1})
                    fields = ("id", "name", "type", "content", "ttl", "proxied", "priority", "created_on", "modified_on")
                elif scope == "workers.read":
                    response = transport.get(integration_id, f"/accounts/{account}/workers/scripts", token)
                    fields = ("id", "created_on", "modified_on", "etag", "handlers", "compatibility_date")
                else:
                    response = transport.get(integration_id, f"/accounts/{account}/pages/projects", token,
                        {"per_page": limit, "page": 1})
                    fields = ("id", "name", "subdomain", "domains", "created_on", "production_branch")
            else:
                path = "/repos/" + options["repository"]
                if scope == "repositories.read":
                    response = self.transport.get(integration_id, path, token)
                    if not isinstance(response.data, dict) or str(response.data.get("full_name", "")).lower() != options["repository"].lower():
                        raise ProviderError("GitHub returned a different repository; verify owner/name")
                    fields = ("id", "full_name", "description", "html_url", "private", "default_branch", "language",
                              "topics", "archived", "created_at", "updated_at", "pushed_at")
                    response = JsonResponse([response.data])
                else:
                    endpoint = "/issues" if scope == "issues.read" else "/pulls"
                    response = self.transport.get(integration_id, path + endpoint, token,
                        {"state": "all", "sort": "updated", "direction": "desc", "per_page": limit, "page": 1})
                    fields = ("id", "number", "title", "body", "state", "html_url", "created_at", "updated_at", "closed_at")
            batch, more = _records(response, scope, fields, limit,
                skip_pull_requests=(integration_id == "github" and scope == "issues.read"))
            records.extend(batch)
            truncated = truncated or more
        return records, truncated

    def _commit(self, status: dict[str, Any], revision: str, *, error: str | None = None,
                prepared: list[tuple[str, str, str]] | None = None) -> tuple[list[int], int]:
        """Validate the grant, import all snapshots and record state in one transaction."""
        integration_id = status["id"]
        def write(conn: sqlite3.Connection) -> tuple[list[int], int]:
            def setting(prefix: str) -> str:
                row = conn.execute("SELECT value FROM settings WHERE key=?", (prefix + integration_id,)).fetchone()
                return row["value"] if row else ""
            try:
                grant = json.loads(setting("integration_config:"))
                options = json.loads(setting(OPTIONS_PREFIX))
                current = {"enabled": grant["enabled"], "configured_scopes": grant["scopes"], "project_id": grant["project_id"]}
                if set(grant) != {"enabled", "scopes", "project_id"} or _revision_value(current, options, setting(CREDENTIAL_PREFIX)) != revision:
                    raise ValueError
                if not conn.execute("SELECT id FROM projects WHERE id=?", (status["project_id"],)).fetchone():
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                raise PermissionError("Connector setup changed during the request; test or import again") from None
            now = get_iso_now()
            ids: list[int] = []
            duplicates = 0
            for raw, scope, digest in prepared or ():
                source_app, key = "integration:" + integration_id, "snapshot:" + digest
                prior = conn.execute("SELECT fingerprint FROM capture_receipts WHERE source_app=? AND project_id=? AND dedup_key=?",
                    (source_app, status["project_id"], key)).fetchone()
                if prior:
                    if prior["fingerprint"] != digest:
                        raise ValueError("An integration snapshot receipt is inconsistent")
                    duplicates += 1
                    continue
                metadata = {"provider": integration_id, "scope": scope,
                            "resource": _scope_resource(integration_id, scope, status["options"]),
                            "imported_at": now, "read_only": True}
                capture_id = int(conn.execute("""INSERT INTO capture_buffer
                    (raw_text,source_app,captured_at,project_id,source_metadata) VALUES(?,?,?,?,?)""",
                    (raw, source_app, now, status["project_id"], json.dumps(metadata))).lastrowid)
                conn.execute("INSERT INTO capture_receipts VALUES(?,?,?,?,?)",
                    (source_app, status["project_id"], key, digest, capture_id))
                ids.append(capture_id)
            try:
                previous = json.loads(setting(STATE_PREFIX))
            except (ValueError, TypeError):
                previous = {}
            if not isinstance(previous, dict):
                previous = {}
            last_sync = previous.get("last_sync_at") if previous.get("revision") == revision else None
            state = {"revision": revision, "last_checked_at": now, "last_error": error,
                     "last_sync_at": now if prepared is not None else last_sync}
            conn.execute("""INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (STATE_PREFIX + integration_id, json.dumps(state, sort_keys=True), now))
            return ids, duplicates
        return self.db.execute_write(write)

    def test(self, integration_id: str) -> dict[str, Any]:
        status, token, revision = self._setup(integration_id)
        try:
            records, truncated = self._fetch(integration_id, status, token, 1)
        except ProviderError as error:
            self._commit(status, revision, error=str(error))
            return {"ok": False, "error": str(error), "status": self.status(integration_id)}
        self._commit(status, revision)
        return {"ok": True, "sampled_count": len(records), "truncated": truncated,
                "status": self.status(integration_id)}

    def sync(self, integration_id: str, limit: int = 25, *, expected_revision: str | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100 per selected scope")
        status, token, revision = self._setup(integration_id)
        if expected_revision is not None and expected_revision != revision:
            raise PermissionError("Connection changed after selection; choose the current resource again")
        try:
            records, truncated = self._fetch(integration_id, status, token, limit)
            prepared: list[tuple[str, str, str]] = []
            for record in records:
                data = record["data"]
                if isinstance(data.get("body"), str) and len(data["body"]) > 16_000:
                    data["body"] = data["body"][:16_000] + "\n[Body truncated by OwlThread]"
                    truncated = True
                envelope = {"provider": integration_id, "scope": record["scope"],
                            "resource": _scope_resource(integration_id, record["scope"], status["options"]), "data": data}
                # Defensive redaction if a provider resource body contains the supplied token.
                raw = json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2).replace(token, "[credential redacted]")
                from owlthread.integrations.browser_login import is_cloudflare_oauth, is_github_oauth
                if is_cloudflare_oauth(token) or is_github_oauth(token):
                    for field in ("access_token", "refresh_token"):
                        secret = json.loads(token).get(field)
                        if secret: raw = raw.replace(secret, "[credential redacted]")
                if len(raw) > MAX_RECORD_CHARS:
                    raise ProviderError("A provider context record is too large; narrow the selected resource")
                prepared.append((raw, record["scope"], hashlib.sha256(raw.encode()).hexdigest()))
        except ProviderError as error:
            self._commit(status, revision, error=str(error))
            return {"ok": False, "error": str(error), "imported_count": 0, "duplicate_count": 0,
                    "capture_ids": [], "status": self.status(integration_id)}
        capture_ids, duplicates = self._commit(status, revision, prepared=prepared)
        return {"ok": True, "imported_count": len(capture_ids), "duplicate_count": duplicates,
                "capture_ids": capture_ids, "truncated": truncated, "limit_per_scope": limit,
                "status": self.status(integration_id)}
