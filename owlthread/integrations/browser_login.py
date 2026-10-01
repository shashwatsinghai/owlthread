"""Browser sign-in for bundled connectors; secrets stay in protected local settings.

Cloudflare uses its official MCP OAuth server with public-client registration and
PKCE. GitHub device authorization requires OwlThread's own registered client ID.
No provider client secret is bundled in the desktop application.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError

from owlthread.integrations.context import CREDENTIAL_PREFIX, ProviderError, JsonResponse, _NoRedirects, SUPPORTED_SCOPES
from owlthread.security import protect
from owlthread.db.database import get_iso_now
from owlthread import __version__

CF_ORIGIN = "https://mcp.cloudflare.com"
CF_SCOPES = "offline_access user:read account:read zone.read dns.read workers-scripts.read pages.metadata_read"
AUTH_PREFIX = "integration_auth:"
MAX_BYTES = 2_000_000
# Public identifier, registered by the release owner. Device flow needs no secret.
GITHUB_CLIENT_ID = "Ov23lipL10mn453vuau8"
_RENEWAL_LOCK = threading.RLock()


class LoginCancelled(Exception):
    pass


class LoginHttp:
    """Fixed provider origins, no redirects, bounded bodies and finite waits."""
    def request(self, url: str, *, data: dict | None = None, form: bool = False,
                token: str = "", headers: dict | None = None) -> tuple[Any, dict]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {"mcp.cloudflare.com", "github.com", "api.github.com"} or parsed.username or parsed.password:
            raise ProviderError("Invalid sign-in destination")
        head = {"Accept": "application/json", "User-Agent": "OwlThread-browser-login"}
        head.update(headers or {})
        if token and (not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ProviderError("Invalid provider credential; sign in again")
        if token: head["Authorization"] = "Bearer " + token
        body = None
        if data is not None:
            body = (urlencode(data) if form else json.dumps(data)).encode()
            head["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        try:
            with build_opener(_NoRedirects()).open(Request(url, body, head), timeout=12) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES: raise ProviderError("Provider response is too large; narrow your selection")
                response_headers = dict(response.headers.items())
                if not raw: return {}, response_headers
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    # Cloudflare's stateless Streamable HTTP replies may use SSE.
                    messages = [json.loads(line[5:].strip()) for line in raw.decode().splitlines() if line.startswith("data:")]
                    return next((m for m in messages if isinstance(m, dict) and ("result" in m or "error" in m)), {}), response_headers
                return json.loads(raw), response_headers
        except HTTPError as error:
            code = error.code; error.close()
            raise ProviderError(f"Provider request failed (HTTP {code}); sign in again or try later") from None
        except (URLError, OSError, ValueError, UnicodeError, StopIteration):
            raise ProviderError("Could not complete the provider request; check your connection and try again") from None


def is_cloudflare_oauth(value: str) -> bool:
    try: return json.loads(value).get("kind") == "cloudflare_oauth"
    except (ValueError, TypeError, AttributeError): return False


def is_github_oauth(value: str) -> bool:
    try: return json.loads(value).get("kind") == "github_oauth"
    except (ValueError, TypeError, AttributeError): return False


def _token_bundle(provider: str, client_id: str, tokens: dict, previous: dict | None = None) -> str:
    """Validate provider credentials before storing them or adding HTTP headers."""
    previous = previous or {}
    access, refresh = tokens.get("access_token"), tokens.get("refresh_token", previous.get("refresh_token", ""))
    for value in (access, refresh):
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ProviderError("Provider returned invalid credentials; sign in again")
    if not access: raise ProviderError("Provider did not complete sign-in")
    if provider == "github" and set(re.split(r"[,\s]+", tokens.get("scope", "").strip())) - {"", "read:user", "offline_access"}:
        raise ProviderError("GitHub granted unexpected permissions; review the app and sign in again")
    try:
        expires = int(tokens.get("expires_in", 3600 if provider == "cloudflare" else 0))
        if expires < 0: raise ValueError
    except (ValueError, TypeError): raise ProviderError("Provider returned invalid token expiry") from None
    return json.dumps({"kind":provider+"_oauth", "client_id":client_id, "access_token":access,
                       "refresh_token":refresh, "expires_at":time.time()+expires if expires else 0})


class CloudflareMcpTransport:
    """Only fixed GET requests can reach Cloudflare's execute tool."""
    def __init__(self, http: LoginHttp | None = None): self.http = http or LoginHttp()

    def get(self, provider: str, path: str, credential: str, query: dict | None = None) -> JsonResponse:
        allowed = re.fullmatch(r"/(?:accounts|zones|accounts/[0-9a-f]{32}/(?:workers/scripts|pages/projects)|zones/[0-9a-f]{32}/dns_records)", path)
        if provider != "cloudflare" or not allowed or set(query or {}) - {"account.id", "per_page", "page"}:
            raise ProviderError("This connection only permits supported context reads")
        try: token = json.loads(credential)["access_token"]
        except (ValueError, KeyError, TypeError): raise ProviderError("Sign in to Cloudflare again") from None
        if not isinstance(token, str) or not token: raise ProviderError("Sign in to Cloudflare again")
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        def rpc(body: dict) -> dict:
            result, response_headers = self.http.request(CF_ORIGIN + "/mcp", data=body, token=token, headers=headers)
            session = response_headers.get("Mcp-Session-Id") or response_headers.get("mcp-session-id")
            if session:
                if len(session) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in session): raise ProviderError("Invalid provider session")
                headers["Mcp-Session-Id"] = session
            if not isinstance(result, dict) or "error" in result: raise ProviderError("Cloudflare could not complete this context read")
            return result.get("result", {})
        initialized = rpc({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"OwlThread","version":__version__}}})
        if not isinstance(initialized, dict) or not initialized.get("protocolVersion"): raise ProviderError("Invalid Cloudflare MCP response")
        rpc({"jsonrpc":"2.0","method":"notifications/initialized"})
        # Paths are allowlisted; values are JSON literals, never executable input.
        read_path = path + ("?" + urlencode(query) if query else "")
        code = "async () => { return await cloudflare.request({method: \"GET\", path: " + json.dumps(read_path) + "}); }"
        args = {"code": code}
        account = (query or {}).get("account.id") or (path.split("/")[2] if path.startswith("/accounts/") else None)
        if account: args["account_id"] = account
        result = rpc({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"execute","arguments":args}})
        if result.get("isError"): raise ProviderError("Cloudflare denied this read; check the permissions granted at sign-in")
        content = result.get("content", [])
        try:
            text = "\n".join(item["text"] for item in content if item.get("type") == "text")
            envelope = result.get("structuredContent") or json.loads(text)
            if isinstance(envelope, dict) and "result" not in envelope and isinstance(envelope.get("output"), dict): envelope = envelope["output"]
            if not isinstance(envelope, dict) or envelope.get("success") is not True or "result" not in envelope: raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError): raise ProviderError("Cloudflare returned unexpected or truncated context") from None
        info = envelope.get("result_info") or {}
        more = isinstance(info, dict) and isinstance(info.get("total_pages"), int) and info["total_pages"] > info.get("page", 1)
        return JsonResponse(envelope["result"], more)


@dataclass
class LoginSession:
    provider: str
    project_id: int
    scopes: list[str]
    id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    state: str = "starting"
    message: str = "Preparing secure sign-in…"
    browser_url: str = ""
    user_code: str = ""
    cancelled: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def public(self):
        return {"id":self.id,"provider":self.provider,"state":self.state,"message":self.message,
                "browser_url":self.browser_url,"user_code":self.user_code,"project_id":self.project_id}


class BrowserLoginService:
    """Nonblocking login sessions owned by the desktop, never its MCP clients."""
    def __init__(self, db: Any, *, http: LoginHttp | None = None, browser: Callable[[str], bool] | None = None):
        import webbrowser
        self.db, self.http = db, http or LoginHttp()
        self.browser = browser or webbrowser.open
        self.lock = threading.RLock()
        self.sessions: dict[str, LoginSession] = {}
        self.closed = False

    def client_id(self): return self.db.get_setting("github_oauth_client_id", "") or os.environ.get("OWLTHREAD_GITHUB_CLIENT_ID", "") or GITHUB_CLIENT_ID

    def status(self, provider: str) -> dict:
        raw = self.db.get_setting(AUTH_PREFIX + provider, "{}")
        try: saved = json.loads(raw)
        except (ValueError, TypeError): saved = {}
        if not isinstance(saved, dict): saved = {}
        signed_in = saved.get("method") == "browser" and bool(self.db.get_setting(CREDENTIAL_PREFIX + provider, ""))
        with self.lock:
            session = next((s.public() for s in self.sessions.values() if s.provider == provider), None)
        if session and session["state"] == "signed_in" and not signed_in: session = None
        return {"browser_login_available":provider == "cloudflare" or bool(self.client_id()),
                "signed_in":signed_in,
                "resources":saved.get("resources", []),"label":saved.get("label", ""),"session":session}

    def begin(self, provider: str, project_id: int, scopes: list[str] | None = None) -> dict:
        if provider not in SUPPORTED_SCOPES or not self.db.get_project_by_id(project_id): raise ValueError("Select a provider and project")
        scopes = list(scopes or SUPPORTED_SCOPES[provider])
        if not scopes or len(set(scopes)) != len(scopes) or any(s not in SUPPORTED_SCOPES[provider] for s in scopes): raise ValueError("Choose valid context reads")
        if provider == "github" and not re.fullmatch(r"[A-Za-z0-9_.-]{10,128}", str(self.client_id())):
            raise ValueError("GitHub sign-in needs OwlThread's registered app Client ID. Use Set up GitHub sign-in once.")
        with self.lock:
            if self.closed: raise ValueError("The application is closing")
            self.cancel(provider)
            session = LoginSession(provider, project_id, scopes)
            self.sessions = {key:s for key,s in self.sessions.items() if s.provider != provider}
            self.sessions[session.id] = session
            session.thread = threading.Thread(target=self._run, args=(session,), daemon=True, name="OwlThread-Login-"+provider)
            session.thread.start()
            return session.public()

    def cancel(self, provider: str):
        with self.lock:
            for session in self.sessions.values():
                if session.provider == provider and session.state in {"starting","waiting","discovering"}:
                    session.cancelled.set(); session.state = "cancelled"; session.message = "Sign-in cancelled."

    def close(self):
        with self.lock:
            self.closed = True
            for provider in SUPPORTED_SCOPES: self.cancel(provider)

    def _check(self, session):
        if session.cancelled.is_set() or self.closed: raise LoginCancelled()

    def _update(self, session, **values):
        with self.lock:
            self._check(session)
            for key,value in values.items(): setattr(session,key,value)

    def _open(self, session, url: str, user_code=""):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {"mcp.cloudflare.com","github.com"} or parsed.username or parsed.password:
            raise ProviderError("Provider returned an invalid sign-in URL")
        self._update(session, state="waiting", message="Finish signing in in your browser." + (" Enter code " + user_code + "." if user_code else ""), browser_url=url, user_code=user_code)
        self._check(session)
        if not self.browser(url): self._update(session, message="Open the browser using the link below to finish sign-in.")

    def _cloudflare(self, session) -> tuple[str,list[dict],str]:
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        result: dict = {}
        cancelled = session.cancelled
        class Callback(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(handler):
                parsed = urlsplit(handler.path)
                values = parse_qs(parsed.query, keep_blank_values=True)
                valid = (handler.headers.get("Host") == f"127.0.0.1:{handler.server.server_port}" and parsed.path == "/oauth/callback" and len(handler.path) <= 4096 and not cancelled.is_set() and
                         len(values.get("state", [])) == 1 and secrets.compare_digest(values["state"][0], state) and
                         ("iss" not in values or values["iss"] == [CF_ORIGIN]) and not result)
                valid = valid and (len(values.get("code", [])) == 1 or len(values.get("error", [])) == 1)
                handler.send_response(200 if valid else 400)
                handler.send_header("Content-Type","text/html; charset=utf-8")
                handler.send_header("Cache-Control","no-store")
                handler.send_header("Content-Security-Policy","default-src 'none'; frame-ancestors 'none'")
                handler.end_headers()
                if valid:
                    result.update({"code":values.get("code",[""])[0],"denied":bool(values.get("error"))})
                    handler.wfile.write(b"<h1>Return to OwlThread</h1><p>You can close this tab. OwlThread is finishing the connection.</p>")
                else: handler.wfile.write(b"<h1>This sign-in link is invalid or expired.</h1>")
        class LoopbackServer(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(1)
                return connection, address
        server = LoopbackServer(("127.0.0.1",0), Callback); server.timeout = .25
        try:
            redirect = f"http://127.0.0.1:{server.server_port}/oauth/callback"
            client,_ = self.http.request(CF_ORIGIN+"/register",data={"client_name":"OwlThread","redirect_uris":[redirect],"grant_types":["authorization_code","refresh_token"],"response_types":["code"],"token_endpoint_auth_method":"none","scope":CF_SCOPES})
            client_id = client.get("client_id") if isinstance(client,dict) else None
            if not isinstance(client_id,str) or not client_id or len(client_id)>256: raise ProviderError("Cloudflare could not register this sign-in")
            self._open(session, CF_ORIGIN+"/authorize?"+urlencode({"client_id":client_id,"redirect_uri":redirect,"response_type":"code","scope":CF_SCOPES,"state":state,"code_challenge":challenge,"code_challenge_method":"S256","resource":CF_ORIGIN+"/mcp"}))
            # First-time sign-in can include password recovery or MFA. Keep the
            # callback alive while the user completes provider approval.
            deadline = time.monotonic()+600
            while not result:
                self._check(session)
                if time.monotonic() > deadline: raise ProviderError("Sign-in timed out. Click Sign in to try again.")
                server.handle_request()
            self._check(session)
            if result["denied"]: raise ProviderError("Sign-in was declined. You can try again when ready.")
            tokens,_ = self.http.request(CF_ORIGIN+"/token",data={"grant_type":"authorization_code","client_id":client_id,"redirect_uri":redirect,"code":result["code"],"code_verifier":verifier,"resource":CF_ORIGIN+"/mcp"},form=True)
            access = tokens.get("access_token") if isinstance(tokens,dict) else None
            if not isinstance(access,str) or not access: raise ProviderError("Cloudflare did not complete sign-in")
            credential = _token_bundle("cloudflare",client_id,tokens)
            self._update(session,state="discovering",message="Finding your Cloudflare accounts…")
            response = CloudflareMcpTransport(self.http).get("cloudflare","/accounts",credential,{"per_page":100,"page":1})
            if not isinstance(response.data,list): raise ProviderError("Cloudflare could not list accounts")
            resources = [{"id":r["id"],"label":str(r.get("name") or r["id"])[:200],"options":{"account_id":r["id"],"zone_id":""}} for r in response.data if isinstance(r,dict) and re.fullmatch(r"[0-9a-f]{32}",str(r.get("id","")))]
            return credential, resources[:100], "Cloudflare"
        finally: server.server_close()

    def _github(self, session) -> tuple[str,list[dict],str]:
        client_id = self.client_id()
        reply,_ = self.http.request("https://github.com/login/device/code",data={"client_id":client_id,"scope":"read:user"},form=True)
        if not isinstance(reply,dict) or not all(isinstance(reply.get(k),str) and reply[k] for k in ("device_code","user_code","verification_uri")): raise ProviderError("GitHub could not start sign-in; verify the registered app has device flow enabled")
        if reply["verification_uri"] != "https://github.com/login/device": raise ProviderError("Invalid GitHub sign-in destination")
        self._open(session, reply["verification_uri"], reply["user_code"])
        interval = min(30,max(5,int(reply.get("interval",5))))
        deadline = time.monotonic()+min(900,max(30,int(reply.get("expires_in",900))))
        while time.monotonic() < deadline:
            if session.cancelled.wait(interval): raise LoginCancelled()
            self._check(session)
            token,_ = self.http.request("https://github.com/login/oauth/access_token",data={"client_id":client_id,"device_code":reply["device_code"],"grant_type":"urn:ietf:params:oauth:grant-type:device_code"},form=True)
            if not isinstance(token,dict): raise ProviderError("GitHub returned an invalid sign-in response")
            if token.get("access_token"): break
            error = token.get("error")
            if error == "authorization_pending": continue
            if error == "slow_down": interval = min(60,interval+5); continue
            raise ProviderError("GitHub sign-in was declined or expired. Click Sign in to try again.")
        else: raise ProviderError("GitHub sign-in timed out. Click Sign in to try again.")
        credential = _token_bundle("github",client_id,token)
        access = token["access_token"]
        self._update(session,state="discovering",message="Finding your GitHub repositories…")
        user,_ = self.http.request("https://api.github.com/user",token=access)
        repos,_ = self.http.request("https://api.github.com/user/repos?per_page=100&sort=updated",token=access)
        if not isinstance(user,dict) or not isinstance(user.get("login"),str) or not isinstance(repos,list): raise ProviderError("GitHub could not list repositories")
        resources = [{"id":r["full_name"],"label":r["full_name"],"options":{"repository":r["full_name"]}} for r in repos if isinstance(r,dict) and not r.get("private") and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.-]{1,100}",str(r.get("full_name","")))]
        return credential, resources[:100], user["login"]

    def _run(self, session):
        try:
            credential,resources,name = self._cloudflare(session) if session.provider == "cloudflare" else self._github(session)
            with self.lock:
                self._check(session)
                def write(conn):
                    now = get_iso_now()
                    values = {CREDENTIAL_PREFIX+session.provider:protect(credential), AUTH_PREFIX+session.provider:json.dumps({"method":"browser","resources":resources,"label":name,"project_id":session.project_id,"scopes":session.scopes}),
                              "integration_config:"+session.provider:json.dumps({"enabled":False,"scopes":[],"project_id":None})}
                    for key,value in values.items(): conn.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,value,now))
                self.db.execute_write(write)
                session.state = "signed_in"; session.message = "Signed in. Choose what to import." if resources else "Signed in. No accessible resources were found; check provider permissions."
        except LoginCancelled: pass
        except Exception as error:
            with self.lock:
                if not session.cancelled.is_set() and not self.closed:
                    session.state="error"; session.message=str(error) if isinstance(error,ProviderError) else "Could not finish sign-in. Please try again."

    def select(self, provider: str, resource_id: str) -> dict:
        from owlthread.integrations.context import ContextConnectorService, _options, _revision_value, OPTIONS_PREFIX
        if provider not in SUPPORTED_SCOPES: raise ValueError("Unknown provider")
        # Bind resource selection to the exact auth/credential pair in one
        # transaction. Another sign-in must never reuse a stale resource/project.
        def configure(conn):
            rows=conn.execute("SELECT key,value FROM settings WHERE key IN (?,?)",(AUTH_PREFIX+provider,CREDENTIAL_PREFIX+provider)).fetchall()
            snapshot={row["key"]:row["value"] for row in rows}
            try:
                saved=json.loads(snapshot[AUTH_PREFIX+provider])
                resource=next((r for r in saved["resources"] if r["id"]==resource_id),None)
                if saved.get("method") != "browser" or not resource or not snapshot[CREDENTIAL_PREFIX+provider]: raise ValueError
                project=saved["project_id"];scopes=saved["scopes"]
                if type(project) is not int or not conn.execute("SELECT id FROM projects WHERE id=?",(project,)).fetchone(): raise ValueError
                if not isinstance(scopes,list) or not scopes or any(s not in SUPPORTED_SCOPES[provider] for s in scopes): raise ValueError
                if provider == "cloudflare": scopes=[s for s in scopes if s != "dns.read"]
                options=_options(provider,resource["options"],scopes)
            except (ValueError, KeyError, TypeError):
                raise ValueError("Choose an account or repository from your current signed-in connection") from None
            grant={"enabled":True,"scopes":scopes,"project_id":project}
            now=get_iso_now()
            for key,value in {"integration_config:"+provider:json.dumps(grant),OPTIONS_PREFIX+provider:json.dumps(options,sort_keys=True)}.items():
                conn.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,value,now))
            return _revision_value({"enabled":True,"configured_scopes":scopes,"project_id":project},options,snapshot[CREDENTIAL_PREFIX+provider])
        # Renewal precedes the selection revision; it also rejects stale writes.
        refresh_browser_credential(self.db,provider)
        revision=self.db.execute_write(configure)
        return ContextConnectorService(self.db).sync(provider,expected_revision=revision)


def refresh_browser_credential(db: Any, provider: str, http: LoginHttp | None = None):
    """Renew before the import snapshot, serialize rotation, and reject stale writes."""
    if provider not in SUPPORTED_SCOPES: raise ValueError("Unknown provider")
    with _RENEWAL_LOCK:
        raw = db.get_setting(CREDENTIAL_PREFIX+provider, "")
        if not (is_cloudflare_oauth(raw) if provider == "cloudflare" else is_github_oauth(raw)): return
        bundle = json.loads(raw)
        expiry = bundle.get("expires_at",0)
        if (provider == "github" and expiry == 0) or expiry > time.time()+60: return
        if not bundle.get("refresh_token"): raise ProviderError(provider.title()+" sign-in expired. Sign in again.")
        data = {"grant_type":"refresh_token","refresh_token":bundle["refresh_token"],"client_id":bundle["client_id"]}
        if provider == "cloudflare": data["resource"] = CF_ORIGIN+"/mcp"
        endpoint = CF_ORIGIN+"/token" if provider == "cloudflare" else "https://github.com/login/oauth/access_token"
        tokens,_ = (http or LoginHttp()).request(endpoint,data=data,form=True)
        if not isinstance(tokens,dict): raise ProviderError("Sign-in expired. Sign in again.")
        renewed = _token_bundle(provider,bundle["client_id"],tokens,bundle)
        def write(conn):
            row=conn.execute("SELECT value FROM settings WHERE key=?",(CREDENTIAL_PREFIX+provider,)).fetchone()
            from owlthread.security import unprotect
            if not row or unprotect(row["value"]) != raw: raise ProviderError("Connection changed during renewal; try again")
            conn.execute("UPDATE settings SET value=?,updated_at=? WHERE key=?",(protect(renewed),get_iso_now(),CREDENTIAL_PREFIX+provider))
        db.execute_write(write)


def refresh_cloudflare(db: Any, http: LoginHttp | None = None):
    refresh_browser_credential(db,"cloudflare",http)
