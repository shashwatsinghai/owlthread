"""Canonical versioned mutation engine shared by extraction and MCP.
The caller owns one BEGIN IMMEDIATE transaction, including its capture checkpoint.
UPDATE is refinement; SUPERSEDE is replacement. Both create an immutable successor.
"""
from __future__ import annotations
import re
import sqlite3
import unicodedata
from typing import Any
from owlthread.config import VALID_QUADRANTS
from owlthread.db.database import get_iso_now

MAX_SUMMARY = 240


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"^(decision|architecture|business rule|open question):\s*", "", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".!。")


def validate_actions(data: Any, source: str, existing: list[dict[str,Any]]) -> list[dict[str,Any]]:
    if not isinstance(data,list) or len(data) > 24:
        raise ValueError("Expected at most 24 extraction actions")
    known = {row["id"]:row for row in existing}
    validated = []
    targets = set()
    for item in data:
        if not isinstance(item,dict) or item.get("action") not in {"ADD","UPDATE","SUPERSEDE","NOOP"}:
            raise ValueError("Invalid extraction action")
        action = item["action"]
        if action == "NOOP":
            continue
        summary,snippet = item.get("summary"),item.get("source_snippet")
        if item.get("quadrant") not in VALID_QUADRANTS or not isinstance(summary,str) or not 1 <= len(summary.strip()) <= MAX_SUMMARY or len(summary.split()) > 30:
            raise ValueError("Invalid quadrant or summary")
        if not isinstance(snippet,str) or not snippet.strip() or len(snippet) > 4000 or snippet not in source:
            raise ValueError("Source evidence must be an exact excerpt of this capture slice")
        confidence = item.get("confidence",1.0)
        if type(confidence) not in {int,float} or not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")
        if confidence < .8:
            continue
        target = item.get("target_memory_id")
        if action in {"UPDATE","SUPERSEDE"}:
            if type(target) is not int or target not in known or known[target]["quadrant"] != item["quadrant"] or target in targets:
                raise ValueError("Replacement target must be supplied, unique and in the same quadrant")
            targets.add(target)
        elif target is not None:
            raise ValueError("ADD cannot replace a target")
        reason = item.get("rationale", "Refinement of prior memory" if action == "UPDATE" else "Replacement of prior memory")
        if not isinstance(reason,str) or len(reason)>500:
            raise ValueError("Invalid action rationale")
        validated.append({**item,"summary":summary.strip(),"rationale":reason})
    return validated


def apply_actions(conn: sqlite3.Connection, capture: dict[str,Any], actions: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Apply validated actions under the caller's write transaction; never commits."""
    now = get_iso_now()
    results=[]
    for item in actions:
        action=item["action"]
        if action=="NOOP":
            continue
        pid,quadrant,summary=capture["project_id"],item["quadrant"],item["summary"]
        if quadrant not in VALID_QUADRANTS:
            raise ValueError("Invalid quadrant")
        target=item.get("target_memory_id") if action in {"UPDATE","SUPERSEDE"} else None
        if target is not None and not conn.execute("SELECT id FROM memory_entries WHERE id=? AND project_id=? AND quadrant=? AND status='active'",(target,pid,quadrant)).fetchone():
            raise ValueError("Memory changed during extraction; retry the pending capture")
        summaries=conn.execute("SELECT summary FROM memory_entries WHERE project_id=? AND quadrant=? AND status='active'",(pid,quadrant))
        if any(normalized(row[0])==normalized(summary) for row in summaries):
            continue
        eid=conn.execute("""INSERT INTO memory_entries
            (quadrant,summary,raw_text,source_app,project_id,created_at,updated_at,timestamp,source_metadata)
            VALUES(?,?,?,?,?,?,?,?,?)""",(quadrant,summary,item["source_snippet"],capture["source_app"],pid,now,now,
            capture.get("captured_at") or now,capture.get("source_metadata"))).lastrowid
        if target is not None:
            conn.execute("UPDATE memory_entries SET status='superseded',superseded_by=?,updated_at=? WHERE id=?",(eid,now,target))
            conn.execute("INSERT INTO memory_lineage VALUES(?,?,?,?)",(eid,target,item["rationale"],now))
        results.append({"entry_id":eid,"quadrant":quadrant,"summary":summary,"project_id":pid,"status":"active","action":action,"superseded_id":target})
    return results
