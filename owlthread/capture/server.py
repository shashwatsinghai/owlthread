"""Local HTTP Server for receiving browser extension captures, serving Primer requests, and flushing buffers."""

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from owlthread.config import (
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    SOURCE_BROWSER,
)
from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.primer.engine import PrimerEngine

logger = logging.getLogger(__name__)


class CaptureRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for /capture, /health, /entries, /primer, and /flush."""

    server: "CaptureHTTPServer"  # Type hint for custom server attribute

    def _set_cors_headers(self) -> None:
        """Set CORS headers to permit browser extension fetch requests."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With")

    def _send_json_response(self, status_code: int, data: dict) -> None:
        """Send a JSON payload response."""
        response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        """Handle GET requests for /health, /entries, and /primer."""
        parsed_url = urlparse(self.path)
        parsed_path = parsed_url.path

        if parsed_path in ("/", "/health", "/status"):
            count = self.server.db.count_entries()
            self._send_json_response(HTTPStatus.OK, {
                "status": "healthy",
                "app": "OwlThread",
                "total_entries": count
            })
            return

        if parsed_path == "/entries":
            entries = self.server.db.get_entries(limit=20)
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "count": len(entries),
                "entries": entries
            })
            return

        if parsed_path in ("/primer", "/query"):
            qs = parse_qs(parsed_url.query)
            query_list = qs.get("q") or qs.get("query") or []
            if not query_list or not query_list[0].strip():
                self._send_json_response(HTTPStatus.BAD_REQUEST, {
                    "error": "Query parameter 'q' or 'query' is required."
                })
                return

            query = query_list[0].strip()
            intent_override = qs.get("intent", [None])[0]
            include_history = qs.get("include_history", ["false"])[0].lower() in ("true", "1")
            result = self.server.primer_engine.generate_primer(
                user_request=query,
                intent_override=intent_override,
                include_history=include_history,
            )
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                **result.to_dict()
            })
            return

        if parsed_path == "/settings":
            settings = self.server.db.get_all_settings()
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "settings": settings
            })
            return

        if parsed_path in ("/projects", "/api/projects"):
            active_project = self.server.db.get_setting("active_project", "General")
            projects = [p["name"] for p in self.server.db.list_projects()]
            if "General" not in projects:
                projects.insert(0, "General")
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "active_project": active_project,
                "projects": projects
            })
            return

        if parsed_path == "/state":
            is_paused = getattr(self.server, "is_paused", False)
            active_project = self.server.db.get_setting("active_project", "General")
            llm_provider = self.server.db.get_setting("llm_provider", "fallback")
            llm_model = self.server.db.get_setting("llm_model", "gemini-2.0-flash")
            has_api_key = bool(self.server.db.get_setting("llm_api_key", ""))
            projects = [p["name"] for p in self.server.db.list_projects()]
            if "General" not in projects:
                projects.insert(0, "General")
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "is_paused": is_paused,
                "total_entries": self.server.db.count_entries(),
                "active_project": active_project,
                "projects": projects,
                "ai_provider": llm_provider,
                "ai_model": llm_model,
                "has_api_key": has_api_key,
            })
            return

        if parsed_path == "/sites":
            sites_json = self.server.db.get_setting("site_permissions", "{}")
            try:
                sites_data = json.loads(sites_json) if sites_json else {}
            except Exception:
                sites_data = {}
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "sites": sites_data
            })
            return

        self._send_json_response(HTTPStatus.NOT_FOUND, {
            "error": "Not Found",
            "path": parsed_path
        })

    def do_POST(self) -> None:
        """Handle POST /capture, POST /primer, and POST /flush requests."""
        parsed_path = self.path.split("?")[0]

        if parsed_path in ("/primer", "/query"):
            self._handle_primer_post()
            return

        if parsed_path in ("/flush", "/done", "/ship"):
            self._handle_flush_post()
            return

        if parsed_path == "/settings":
            self._handle_settings_post()
            return

        if parsed_path == "/sites":
            self._handle_sites_post()
            return

        if parsed_path == "/state":
            self._handle_state_post()
            return

        if parsed_path in ("/projects", "/api/projects"):
            self._handle_projects_post()
            return

        if parsed_path in ("/test-ai", "/api/test-ai"):
            self._handle_test_ai_post()
            return

        if parsed_path in ("/delete-entry", "/delete"):
            self._handle_delete_entry_post()
            return

        if parsed_path == "/reset":
            self.server.db.clear_entries()
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "message": "Database cleared successfully."
            })
            return

        if parsed_path != "/capture":
            self._send_json_response(HTTPStatus.NOT_FOUND, {
                "error": "Endpoint not found"
            })
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Empty request body"
            })
            return

        try:
            body_bytes = self.rfile.read(content_length)
            body_str = body_bytes.decode("utf-8", errors="ignore")
            payload = json.loads(body_str)
        except Exception as e:
            logger.error("Failed to parse JSON body: %s", e)
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": f"Invalid JSON payload: {str(e)}"
            })
            return

        raw_text = payload.get("text") or payload.get("raw_text") or ""
        if not raw_text or not raw_text.strip():
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Field 'text' or 'raw_text' is required and must not be empty."
            })
            return

        source_app = payload.get("source_app") or SOURCE_BROWSER
        active_project = self.server.db.get_setting("active_project", "General")
        req_project = payload.get("project_name") or payload.get("project")
        if req_project and str(req_project).strip() and str(req_project).strip() != "General":
            project_name = str(req_project).strip()
        else:
            project_name = active_project or "General"

        root_path = payload.get("root_path")
        timestamp = payload.get("timestamp")
        url = payload.get("url")
        title = payload.get("title")
        extra_meta = payload.get("metadata", {})

        domain = extra_meta.get("hostname")
        if not domain and url and "://" in url:
            try:
                domain = url.split("/")[2].split(":")[0]
            except Exception:
                domain = None

        source_metadata = {
            "source": "browser_extension",
            "url": url,
            "title": title,
            "domain": domain,
            **extra_meta
        }

        try:
            # 1. Ingest into extraction pipeline (buffers per project + source_app)
            extracted_items = self.server.pipeline.ingest_capture(
                raw_text=raw_text,
                source_app=source_app,
                project_name=project_name,
                root_path=root_path,
                timestamp=timestamp
            )

            # 2. Immediate lightweight classification for instant rich card & vault entries
            quick_quad, quick_sum = self.server.pipeline.extractor.quick_classify(raw_text)

            project_id = self.server.db.get_or_create_project(name=project_name, root_path=root_path)
            entry_id = self.server.db.insert_entry(
                raw_text=raw_text,
                source_app=source_app,
                project_id=project_id,
                source_metadata=source_metadata,
                timestamp=timestamp,
                quadrant=quick_quad,
                summary=quick_sum,
                status="active"
            )

            logger.info("Captured entry #%d [%s] from %s: %s", entry_id, quick_quad, source_app, quick_sum)

            entry_data = {
                "id": entry_id,
                "project_id": project_id,
                "project_name": project_name or "General",
                "source_app": source_app,
                "raw_text": raw_text,
                "timestamp": timestamp,
                "source_metadata": source_metadata,
                "quadrant": quick_quad,
                "summary": quick_sum,
                "extracted_count": len(extracted_items),
                "extracted_items": extracted_items,
            }
            if hasattr(self.server, "notify_capture"):
                self.server.notify_capture(entry_data)

            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "id": entry_id,
                "project_id": project_id,
                "extracted_count": len(extracted_items),
                "extracted_items": extracted_items,
                "message": "Captured and buffered successfully"
            })
        except Exception as e:
            logger.error("Error processing capture entry: %s", e)
            self._send_json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": f"Capture processing failed: {str(e)}"
            })

    def _handle_primer_post(self) -> None:
        """Handle POST /primer requests."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Empty request body"
            })
            return

        try:
            body_bytes = self.rfile.read(content_length)
            body_str = body_bytes.decode("utf-8", errors="ignore")
            payload = json.loads(body_str)
        except Exception as e:
            logger.error("Failed to parse JSON body for primer: %s", e)
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": f"Invalid JSON payload: {str(e)}"
            })
            return

        query = payload.get("query") or payload.get("request") or payload.get("text") or ""
        if not query or not query.strip():
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Field 'query' or 'request' is required."
            })
            return

        intent_override = payload.get("intent")
        search_limit = int(payload.get("limit", 12))
        auto_copy = bool(payload.get("copy", True))
        include_history = bool(payload.get("include_history", False))
        project_id = payload.get("project_id")

        try:
            result = self.server.primer_engine.generate_primer(
                user_request=query.strip(),
                intent_override=intent_override,
                search_limit=search_limit,
                auto_copy=auto_copy,
                include_history=include_history,
                project_id=project_id,
            )
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                **result.to_dict()
            })
        except Exception as e:
            logger.exception("Error generating primer: %s", e)
            self._send_json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": f"Primer generation failed: {str(e)}"
            })

    def _handle_flush_post(self) -> None:
        """Handle POST /flush or /done requests."""
        try:
            result = self.server.pipeline.handle_done_signal()
            self._send_json_response(HTTPStatus.OK, result)
        except Exception as e:
            logger.exception("Error handling flush/done signal: %s", e)
            self._send_json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": f"Flush failed: {str(e)}"
            })

    def _handle_settings_post(self) -> None:
        """Handle POST /settings requests — save user-customizable prompts and config."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Empty request body"
            })
            return

        try:
            body_bytes = self.rfile.read(content_length)
            body_str = body_bytes.decode("utf-8", errors="ignore")
            payload = json.loads(body_str)
        except Exception as e:
            logger.error("Failed to parse JSON body for settings: %s", e)
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": f"Invalid JSON payload: {str(e)}"
            })
            return

        if not isinstance(payload, dict):
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Settings payload must be a JSON object with key-value pairs."
            })
            return

        # Valid settings keys
        allowed_keys = {
            "extraction_prompt",
            "primer_prompt",
            "llm_provider",
            "llm_api_key",
            "llm_model",
            "llm_base_url",
            "active_project",
        }
        saved_keys = []

        for key, value in payload.items():
            if key not in allowed_keys:
                continue
            if not isinstance(value, str):
                continue
            self.server.db.set_setting(key, value.strip())
            saved_keys.append(key)

        # Reload prompts into pipeline if extraction/primer prompts were updated
        if "extraction_prompt" in saved_keys:
            custom = self.server.db.get_setting("extraction_prompt")
            if custom:
                self.server.pipeline.extractor.custom_system_prompt = custom
        if "primer_prompt" in saved_keys:
            custom = self.server.db.get_setting("primer_prompt")
            if custom:
                self.server.primer_engine.generator.custom_system_prompt = custom

        # Reload LLM clients if any AI keys were changed
        if any(k.startswith("llm_") for k in saved_keys):
            self.server.pipeline.extractor.llm_client.reload_from_db(self.server.db)
            self.server.primer_engine.generator.llm_client.reload_from_db(self.server.db)

        self._send_json_response(HTTPStatus.OK, {
            "status": "ok",
            "saved_keys": saved_keys,
            "message": f"Saved {len(saved_keys)} setting(s)."
        })

    def _handle_sites_post(self) -> None:
        """Handle POST /sites requests — store or update domain permissions."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": "Empty request body"})
            return

        try:
            body_bytes = self.rfile.read(content_length)
            payload = json.loads(body_bytes.decode("utf-8", errors="ignore"))
        except Exception as e:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {e}"})
            return

        if not isinstance(payload, dict):
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": "Payload must be a JSON object"})
            return

        hostname = payload.get("hostname")
        status = payload.get("status")  # "allowed" or "blocked"
        if not hostname or status not in ("allowed", "blocked"):
            self._send_json_response(HTTPStatus.BAD_REQUEST, {
                "error": "Both 'hostname' and 'status' ('allowed' or 'blocked') are required."
            })
            return

        sites_json = self.server.db.get_setting("site_permissions", "{}")
        try:
            sites_data = json.loads(sites_json) if sites_json else {}
        except Exception:
            sites_data = {}

        sites_data[hostname] = status
        self.server.db.set_setting("site_permissions", json.dumps(sites_data))

        self._send_json_response(HTTPStatus.OK, {
            "status": "ok",
            "hostname": hostname,
            "permission": status,
            "all_sites": sites_data,
        })

    def _handle_state_post(self) -> None:
        """Handle POST /state requests — update global capture pause or active project status."""
        content_length = int(self.headers.get("Content-Length", 0))
        try:
            body_bytes = self.rfile.read(content_length)
            payload = json.loads(body_bytes.decode("utf-8", errors="ignore"))
        except Exception as e:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {e}"})
            return

        if isinstance(payload, dict):
            if "is_paused" in payload:
                self.server.is_paused = bool(payload["is_paused"])
            if "active_project" in payload:
                proj = str(payload["active_project"]).strip()
                if proj:
                    self.server.db.get_or_create_project(name=proj)
                    self.server.db.set_setting("active_project", proj)

        active_project = self.server.db.get_setting("active_project", "General")
        projects = [p["name"] for p in self.server.db.list_projects()]
        if "General" not in projects:
            projects.insert(0, "General")

        self._send_json_response(HTTPStatus.OK, {
            "status": "ok",
            "is_paused": getattr(self.server, "is_paused", False),
            "active_project": active_project,
            "projects": projects
        })

    def _handle_projects_post(self) -> None:
        """Handle POST /projects requests — switch or create active project."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": "Empty body"})
            return
        try:
            body_bytes = self.rfile.read(content_length)
            payload = json.loads(body_bytes.decode("utf-8", errors="ignore"))
        except Exception as e:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {e}"})
            return

        if not isinstance(payload, dict):
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": "Payload must be JSON object"})
            return

        project_name = (payload.get("name") or payload.get("project") or payload.get("active_project") or "").strip()
        if not project_name:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": "Project name is required"})
            return

        self.server.db.get_or_create_project(name=project_name)
        self.server.db.set_setting("active_project", project_name)

        projects = [p["name"] for p in self.server.db.list_projects()]
        if "General" not in projects:
            projects.insert(0, "General")

        self._send_json_response(HTTPStatus.OK, {
            "status": "ok",
            "active_project": project_name,
            "projects": projects,
            "message": f"Active project switched to '{project_name}'"
        })

    def _handle_test_ai_post(self) -> None:
        """Handle POST /test-ai requests — ping active AI connection."""
        try:
            client = self.server.pipeline.extractor.llm_client
            ok, msg = client.test_connection()
            self._send_json_response(HTTPStatus.OK, {
                "status": "ok",
                "success": ok,
                "message": msg,
                "provider": client.provider,
                "model": client.model,
            })
        except Exception as e:
            self._send_json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "status": "error",
                "success": False,
                "message": str(e),
            })

    def _handle_delete_entry_post(self) -> None:
        """Handle POST /delete-entry requests — delete a memory entry by ID."""
        content_length = int(self.headers.get("Content-Length", 0))
        try:
            body_bytes = self.rfile.read(content_length)
            payload = json.loads(body_bytes.decode("utf-8", errors="ignore"))
        except Exception as e:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {e}"})
            return

        entry_id = payload.get("id") if isinstance(payload, dict) else None
        if not entry_id:
            self._send_json_response(HTTPStatus.BAD_REQUEST, {"error": "Missing entry 'id'"})
            return

        success = self.server.db.delete_entry(int(entry_id))
        self._send_json_response(HTTPStatus.OK, {
            "status": "ok",
            "id": entry_id,
            "deleted": success
        })

    def log_message(self, format: str, *args) -> None:
        """Suppress default stdout logging or redirect to logger."""
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


class CaptureHTTPServer(ThreadingHTTPServer):
    """Custom ThreadingHTTPServer holding reference to Database, Pipeline, and PrimerEngine."""

    def __init__(self, server_address, RequestHandlerClass, db: Database):
        self.db = db
        self.pipeline = ExtractionPipeline(db=self.db)
        self.primer_engine = PrimerEngine(db=self.db, extraction_pipeline=self.pipeline)
        self.capture_callbacks: List[Any] = []
        # Load user-saved custom prompts from settings
        custom_extraction = self.db.get_setting("extraction_prompt")
        if custom_extraction:
            self.pipeline.extractor.custom_system_prompt = custom_extraction
        custom_primer = self.db.get_setting("primer_prompt")
        if custom_primer:
            self.primer_engine.generator.custom_system_prompt = custom_primer
        super().__init__(server_address, RequestHandlerClass)

    def add_capture_callback(self, callback: Any) -> None:
        """Register a callback invoked when a new capture entry arrives."""
        if callback not in self.capture_callbacks:
            self.capture_callbacks.append(callback)

    def remove_capture_callback(self, callback: Any) -> None:
        """Unregister a capture callback."""
        if callback in self.capture_callbacks:
            self.capture_callbacks.remove(callback)

    def notify_capture(self, entry_data: Dict[str, Any]) -> None:
        """Notify all registered listeners about a new capture."""
        for cb in list(self.capture_callbacks):
            try:
                cb(entry_data)
            except Exception as e:
                logger.debug("Error in capture listener: %s", e)


class LocalHttpListener:
    """
    Local HTTP Listener for OwlThread.
    
    Bound strictly to localhost (127.0.0.1) with no external network exposure.
    """

    def __init__(
        self,
        db: Database,
        host: str = DEFAULT_HTTP_HOST,
        port: int = DEFAULT_HTTP_PORT
    ):
        self.db = db
        self.host = "127.0.0.1" if host in ("0.0.0.0", "", "localhost") else host
        self.port = port
        self._server: Optional[CaptureHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._callbacks: List[Any] = []

    def add_capture_callback(self, callback: Any) -> None:
        """Register a capture callback."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
        if self._server:
            self._server.add_capture_callback(callback)

    def remove_capture_callback(self, callback: Any) -> None:
        """Unregister a capture callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
        if self._server:
            self._server.remove_capture_callback(callback)

    @property
    def is_running(self) -> bool:
        """Return True if server is listening."""
        return self._is_running

    def start(self) -> None:
        """Start the HTTP server on a daemon thread."""
        if self._is_running:
            return

        try:
            self._server = CaptureHTTPServer((self.host, self.port), CaptureRequestHandler, self.db)
            for cb in self._callbacks:
                self._server.add_capture_callback(cb)
            self._is_running = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="OwlThread-HttpServer",
                daemon=True
            )
            self._thread.start()
            logger.info("LocalHttpListener started on http://%s:%d", self.host, self.port)
        except Exception as e:
            self._is_running = False
            logger.error("Failed to start HTTP server on %s:%d: %s", self.host, self.port, e)
            raise

    def stop(self) -> None:
        """Stop and shutdown the HTTP server."""
        if not self._is_running:
            return

        self._is_running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("LocalHttpListener stopped.")
