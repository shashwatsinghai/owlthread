"""Bounded loopback HTTP ingestion and primer API."""
from __future__ import annotations

import json
import logging
import threading
import secrets
import time
import re
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from owlthread.config import DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT, VALID_QUADRANTS
from owlthread.db.database import Database, get_iso_now
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.primer.engine import PrimerEngine
from owlthread.context_awareness import PageIntelligence
from owlthread.security import local_token, EXTENSION_ORIGIN, MAX_CAPTURE, web_url, project_name
from owlthread.site_policy import is_hard_blocked_url

logger = logging.getLogger(__name__)
MAX_BODY = 1_048_576


class CaptureRequestHandler(BaseHTTPRequestHandler):
    server: CaptureHTTPServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args: Any) -> None:
        # Paths can contain user query text. Do not put it in logs.
        logger.debug("Local HTTP request completed")

    def _send(self, code: int, data: dict[str,Any]) -> None:
        body = json.dumps(data,ensure_ascii=False,default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        origin = self.headers.get("Origin", "")
        if EXTENSION_ORIGIN.fullmatch(origin) and (self.path == "/pair" or self.server.origin_allowed(origin)):
            self.send_header("Access-Control-Allow-Origin",origin)
            self.send_header("Vary","Origin")
            self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):
            logger.debug("HTTP client disconnected")

    def _host_ok(self) -> bool:
        host = self.headers.get("Host","").lower()
        if len(self.headers.get_all("Host", [])) != 1 or host not in {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}:
            self._send(403,{"error":"Loopback Host header required"})
            return False
        return True

    def _authorized(self, preflight: bool = False) -> bool:
        if not self._host_ok():
            return False
        if not self.server.allow_request():
            self._send(429,{"error":"Too many local requests; retry shortly"})
            return False
        origin = self.headers.get("Origin")
        path = urlsplit(self.path).path
        if origin is not None and (len(self.headers.get_all("Origin", [])) != 1 or not EXTENSION_ORIGIN.fullmatch(origin)
                                   or (path != "/pair" and not self.server.origin_allowed(origin))):
            self._send(403,{"error":"Browser origin is not authorized"})
            return False
        if preflight:
            if not origin or self.headers.get("Access-Control-Request-Method") not in {"GET","POST"}:
                self._send(403,{"error":"Invalid preflight"})
                return False
            requested = {s.strip().lower() for s in self.headers.get("Access-Control-Request-Headers","").split(",") if s.strip()}
            if not requested <= {"authorization","content-type"}:
                self._send(403,{"error":"Unsupported request headers"})
                return False
            return True
        if path == "/health" and self.command == "GET":
            return True
        credential = self.headers.get("Authorization", "")
        if len(self.headers.get_all("Authorization", [])) != 1 or not secrets.compare_digest(
                credential.encode(), ("Bearer " + local_token(self.server.db)).encode()):
            self._send(401,{"error":"Pair this client in OwlThread Settings"})
            return False
        return True

    def _project(self, payload: dict[str,Any]) -> int:
        pid = payload.get("project_id")
        name = payload.get("project",payload.get("project_name"))
        if pid is not None:
            if type(pid) is not int or pid <= 0:
                raise ValueError("Invalid project_id")
            project = self.server.db.get_project_by_id(pid)
            if not project or (name is not None and project_name(name) != project["name"]):
                raise ValueError("Project does not exist or conflicts with project_id")
            return pid
        return self.server.db.get_or_create_project(project_name(name if name is not None else self.server.db.get_setting("active_project","General")))

    def _payload(self) -> dict[str,Any]:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Chunked requests are not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise ValueError("Exactly one numeric Content-Length is required")
        length = int(lengths[0])
        if not 0 < length <= MAX_BODY:
            raise ValueError("Request body must be between 1 byte and 1 MiB")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("Incomplete request body")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload,dict):
            raise ValueError("JSON body must be an object")
        return payload

    @staticmethod
    def _limit(value: Any, default: int = 20) -> int:
        if value is None:
            return default
        if isinstance(value,bool) or not str(value).isdigit() or not 1 <= int(value) <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        return int(value)

    @staticmethod
    def _text(payload: dict[str,Any], *keys: str) -> str:
        value = next((payload[k] for k in keys if k in payload),"")
        if not isinstance(value,str) or not value.strip():
            raise ValueError(f"{keys[0]} must be a nonempty string")
        return value.strip()

    def do_OPTIONS(self) -> None:
        if self._authorized(preflight=True):
            self._send(200,{"status":"ok"})

    def do_GET(self) -> None:
        if not self._authorized():
            return
        try:
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if url.path == "/health":
                self._send(200,{"status":"healthy","app":"OwlThread"})
            elif url.path in {"/","/status","/state"}:
                status = self.server.status_callback() if self.server.status_callback else {}
                self._send(200,{"status":"healthy","app":"OwlThread",**status,
                               "total_entries":self.server.db.count_entries(),"pending_captures":self.server.db.pending_count()})
            elif url.path == "/entries":
                quadrant = query.get("quadrant",[None])[0]
                if quadrant is not None and quadrant not in VALID_QUADRANTS:
                    raise ValueError("Invalid quadrant")
                fields = {k:v[0] for k,v in query.items()}
                if "project_id" in fields:
                    if not fields["project_id"].isdigit():
                        raise ValueError("Invalid project_id")
                    fields["project_id"] = int(fields["project_id"])
                rows = self.server.db.get_entries(project_id=self._project(fields),quadrant=quadrant,limit=self._limit(query.get("limit",[None])[0]))
                self._send(200,{"entries":rows,"count":len(rows)})
            elif url.path in {"/primer","/query"}:
                fields = {k:v[0] for k,v in query.items()}
                text = self._text(fields,"q","query")
                if len(text)>4000: raise ValueError("Query exceeds 4000 characters")
                if "project_id" in fields:
                    if not fields["project_id"].isdigit(): raise ValueError("Invalid project_id")
                    fields["project_id"] = int(fields["project_id"])
                self._send(200,{"status":"ok",**self.server.primer_engine.generate_primer(text,project_id=self._project(fields)).to_dict()})
            elif url.path == "/projects":
                self._send(200,{"projects":self.server.db.list_projects()})
            else:
                self._send(404,{"error":"Not found"})
        except (ValueError,TypeError) as exc:
            self._send(400,{"error":str(exc)})
        except Exception:
            logger.exception("HTTP read failed")
            self._send(500,{"error":"Local operation failed; inspect application logs"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        try:
            path = urlsplit(self.path).path
            payload = self._payload()
            if path == "/pair":
                origin = self.headers.get("Origin", "")
                if not EXTENSION_ORIGIN.fullmatch(origin):
                    raise ValueError("Pairing requires an extension origin")
                def pair(conn: Any) -> None:
                    row = conn.execute("SELECT value FROM settings WHERE key='authorized_origins'").fetchone()
                    origins = set(json.loads(row[0])) if row else set()
                    origins.add(origin)
                    conn.execute("""INSERT INTO settings(key,value,updated_at) VALUES('authorized_origins',?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                        (json.dumps(sorted(origins)), get_iso_now()))
                self.server.db.execute_write(pair)
                self._send(200,{"status":"paired"})
            elif path == "/context":
                page_url = web_url(payload.get("url", ""))
                if is_hard_blocked_url(page_url):
                    raise ValueError("OwlThread is permanently disabled for this site")
                result = self.server.page_intelligence.describe_page(payload)
                self._send(200,{"status":"ok",**result})
            elif path in {"/capture","/capture-smart"}:
                if self.server.is_paused or self.server.db.get_setting("capture_paused","false") == "true":
                    self._send(409,{"error":"Capture is paused"})
                    return
                text = self._text(payload,"text","raw_text")
                if len(text) > (12000 if path == "/capture-smart" else MAX_CAPTURE):
                    raise ValueError("Capture exceeds the allowed size")
                source = payload.get("source",payload.get("source_app","browser_extension"))
                if not isinstance(source,str) or not source.strip() or len(source)>80:
                    raise ValueError("Invalid source")
                metadata = {}
                for key,maximum in (("platform",80),("url",2048),("title",500),("capture_mode",20),
                                    ("capture_kind",80),("conversation_id",500),("turn_key",128)):
                    if key in payload:
                        if not isinstance(payload[key],str) or len(payload[key]) > maximum:
                            raise ValueError("Invalid capture metadata")
                        metadata[key] = web_url(payload[key]) if key == "url" else payload[key]
                if is_hard_blocked_url(metadata.get("url")):
                    raise ValueError("OwlThread is permanently disabled for this site")
                dedup = payload.get("dedup_key")
                if dedup is not None and (not isinstance(dedup,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",dedup)):
                    raise ValueError("Invalid dedup_key")
                pid = self._project(payload)
                if path == "/capture-smart":
                    assessment = self.server.page_intelligence.assess_capture(text,metadata)
                    if not assessment["important"]:
                        self._send(200,{"status":"skipped","accepted":False,**assessment})
                        return
                cid = self.server.db.insert_capture(text,source,pid,metadata,dedup_key=dedup)
                for callback in self.server.capture_callbacks:
                    try:
                        callback({"id":cid,"raw_text":text,"source_app":source,"project_id":pid})
                    except Exception:
                        logger.exception("Capture callback failed")
                self._send(200,{"status":"ok","stage":"buffered" if cid else "duplicate","accepted":True,"id":cid,"capture_id":cid,"project_id":pid})
            elif path in {"/primer","/query"}:
                text = self._text(payload,"query","request")
                if len(text) > 4000:
                    raise ValueError("Query exceeds 4000 characters")
                pid = self._project(payload)
                history = payload.get("include_history",False)
                if not isinstance(history,bool):
                    raise ValueError("include_history must be boolean")
                result = self.server.primer_engine.generate_primer(text,intent_override=payload.get("intent"),
                    search_limit=self._limit(payload.get("limit"),12),include_history=history,project_id=pid)
                self._send(200,{"status":"ok",**result.to_dict()})
            elif path in {"/flush","/done","/ship"}:
                result = self.server.pipeline.handle_done_signal()
                self._send(200,result)
            else:
                self._send(404,{"error":"Not found"})
        except (ValueError,TypeError,UnicodeError) as exc:
            self._send(400,{"error":str(exc)})
        except (TimeoutError,OSError):
            logger.debug("HTTP request timed out or disconnected")
        except Exception:
            logger.exception("HTTP operation failed")
            self._send(500,{"error":"Local operation failed; inspect application logs"})


class CaptureHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str,int], db: Database, pipeline: ExtractionPipeline | None = None) -> None:
        if address[0] != DEFAULT_HTTP_HOST:
            raise ValueError("OwlThread only listens on 127.0.0.1")
        self.db = db
        self.pipeline = pipeline or ExtractionPipeline(db)
        self.primer_engine = PrimerEngine(db,extraction_pipeline=self.pipeline)
        self.page_intelligence = PageIntelligence(db,self.pipeline.llm_client)
        self.capture_callbacks: list[Callable[[dict[str,Any]],None]] = []
        self.status_callback: Callable[[],dict[str,Any]] | None = None
        self.is_paused = False
        local_token(db)
        self._rate_lock = threading.Lock()
        self._requests: deque[float] = deque()
        self.rate_limit = 120
        self._slots = threading.BoundedSemaphore(16)
        super().__init__(address,CaptureRequestHandler)

    def origin_allowed(self, origin: str) -> bool:
        try:
            return origin in json.loads(self.db.get_setting("authorized_origins", "[]"))
        except (ValueError,TypeError):
            return False

    def allow_request(self) -> bool:
        with self._rate_lock:
            now = time.monotonic()
            while self._requests and now - self._requests[0] >= 60:
                self._requests.popleft()
            if len(self._requests) >= self.rate_limit:
                return False
            self._requests.append(now)
            return True

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request,client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request,client_address)
        finally:
            self._slots.release()


class LocalHttpListener:
    def __init__(self, db: Database, host: str = DEFAULT_HTTP_HOST, port: int = DEFAULT_HTTP_PORT,
                 pipeline: ExtractionPipeline | None = None) -> None:
        self.db,self.host,self.port = db,host,port
        self.pipeline = pipeline or ExtractionPipeline(db)
        self._server: CaptureHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable[[dict[str,Any]],None]] = []
        self.status_callback: Callable[[],dict[str,Any]] | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def add_capture_callback(self, callback: Callable[[dict[str,Any]],None]) -> None:
        self._callbacks.append(callback)
        if self._server:
            self._server.capture_callbacks = self._callbacks

    def start(self) -> None:
        if self.is_running:
            return
        self._server = CaptureHTTPServer((self.host,self.port),self.db,self.pipeline)
        self._server.capture_callbacks = self._callbacks
        self._server.status_callback = self.status_callback
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever,kwargs={"poll_interval":0.1},daemon=True,name="OwlThread-HTTP")
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            if self._thread:
                self._thread.join()
            # Wait for in-flight requests before the owner closes its database.
            for _ in range(16):
                self._server._slots.acquire()
            self._server = None
