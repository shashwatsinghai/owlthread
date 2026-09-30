"""Local credential protection and strict input boundaries. No secret logging."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
import logging
import re
import secrets
import sys
from typing import Any
from urllib.parse import urlsplit

SECRET_SETTINGS = {"local_api_token", "llm_api_key"}
EXTENSION_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}\Z")
MAX_CAPTURE = 200_000
logger = logging.getLogger(__name__)


def is_secret_setting(key: str) -> bool:
    return key in SECRET_SETTINGS or key.startswith("integration_credential:")


def paired_origin_count(db: Any) -> int:
    try:
        origins = json.loads(db.get_setting("authorized_origins", "[]"))
        return len({origin for origin in origins if isinstance(origin, str) and EXTENSION_ORIGIN.fullmatch(origin)}) if isinstance(origins, list) else 0
    except (ValueError, TypeError):
        return 0


def protect(value: str) -> str:
    if not value or value.startswith("dpapi:"):
        return value
    if sys.platform == "win32":
        import win32crypt
        encrypted = win32crypt.CryptProtectData(value.encode(), "OwlThread credential", None, None, None, 1)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    # Non-Windows is experimental; the DB file is restricted to its owner.
    return value


def unprotect(value: str) -> str:
    if not value.startswith("dpapi:"):
        return value
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(base64.b64decode(value[6:]), None, None, None, 1)[1].decode()
    except Exception:
        raise RuntimeError("Stored credential cannot be unlocked on this account; enter it again in Settings") from None


def local_token(db: Any, rotate: bool = False) -> str:
    def write(conn: Any) -> str:
        replace_token = rotate
        row = conn.execute("SELECT value FROM settings WHERE key='local_api_token'").fetchone()
        if row and row[0] and not replace_token:
            try:
                return unprotect(row[0])
            except RuntimeError:
                logger.warning("Stored browser pairing token cannot be unlocked; browser connections must be paired again")
                replace_token = True
        token = secrets.token_urlsafe(32)
        updated_at = datetime.now(timezone.utc).isoformat()
        conn.execute("""INSERT INTO settings(key,value,updated_at) VALUES('local_api_token',?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            (protect(token), updated_at))
        if replace_token:
            conn.execute("DELETE FROM settings WHERE key='authorized_origins'")
        return token
    return db.execute_write(write)


def project_name(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100 or any(ord(c) < 32 for c in value):
        raise ValueError("project must be a name of 1 to 100 characters without control characters")
    return value.strip()


def web_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid page URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Page URL must be a normal HTTP or HTTPS URL without credentials")
    try:
        parsed.port
    except ValueError:
        raise ValueError("Invalid page URL port") from None
    return value
