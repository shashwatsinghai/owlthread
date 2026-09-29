"""SQLite FTS5 BM25 retrieval with bounded recency adjustment and citations."""
from __future__ import annotations
import math
import re
from datetime import datetime,timezone
from typing import Any
from owlthread.db.database import Database
from owlthread.config import VALID_QUADRANTS

STOP_WORDS=set("a an the and or to for of in on at by with is are was were be am this that what how i we you it my our your want need like going did do does mai main hum ye yeh ek ko ka ki ke hai hoon raha rahi jaa".split())
QUADRANT_ORDER=("technical_architecture","business_rules","settled_decisions","open_questions")


def extract_keywords(text: str) -> list[str]:
    tokens=(t for t in re.findall(r"[\w+#.-]+",text.lower()) if len(t)>1 and t not in STOP_WORDS)
    return list(dict.fromkeys(t[:-1] if len(t)>4 and t.endswith("s") and not t.endswith("ss") else t for t in tokens))


def parse_timestamp_iso(value: str | None) -> datetime:
    try:
        parsed=datetime.fromisoformat((value or "").replace("Z","+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):
        return datetime(1970,1,1,tzinfo=timezone.utc)


def match_expression(query: str) -> str:
    # Treat all user text as terms, never as FTS operators or SQL.
    parts=[]
    for phrase,word in re.findall(r'"([^"]+)"|([^\s"]+)',query):
        if phrase:
            tokens=re.findall(r"\w+",phrase)
            if tokens: parts.append('"'+ " ".join(tokens)+'"')
        else:
            for token in extract_keywords(word):
                if re.search(r"\w",token): parts.append('"'+token.replace('"','""')+'"')
    return " OR ".join(dict.fromkeys(parts[:32]))


def _compact(text: str) -> str:
    return re.sub(r"\s+"," ",text or "").strip()


def _evidence_excerpt(text: str, query: str, limit: int = 800) -> str:
    """Return a compact bounded excerpt centred on the first useful query term."""
    clean=_compact(text)
    if len(clean)<=limit:
        return clean
    lower=clean.casefold()
    positions=[lower.find(term.casefold()) for term in extract_keywords(query)]
    positions=[position for position in positions if position>=0]
    centre=min(positions) if positions else 0
    start=max(0,centre-limit//3)
    end=min(len(clean),start+limit)
    start=max(0,end-limit)
    return ("…" if start else "")+clean[start:end].strip()+("…" if end<len(clean) else "")


class MemorySearcher:
    def __init__(self,db: Database | None = None):
        self.db=db or Database()

    def search(self,query: str,limit: int = 12,recency_half_life_hours: float | None = None,
               include_history: bool = False,project_id: int | None = None,
               quadrant: str | None = None) -> list[dict[str,Any]]:
        if not isinstance(query,str) or len(query)>4000:
            raise ValueError("Search query must be at most 4000 characters")
        if quadrant is not None and quadrant not in VALID_QUADRANTS:
            raise ValueError("Invalid quadrant")
        if type(limit) is not int: raise ValueError("Invalid search limit")
        if limit<=0: return []
        limit=min(limit,200)
        expression=match_expression(query)
        if not expression:
            if query.strip(): return []
            rows=self.db.get_entries(limit=limit,project_id=project_id,quadrant=quadrant,include_history=include_history)
            return [{**row,"score":1.0,"bm25_score":0.0,"recency_weight":1.0,"citation":f"owlthread://memory/{row['id']}"} for row in rows]
        terms=["memory_fts MATCH ?"]
        params: list[Any]=[expression]
        if not include_history: terms.append("m.status='active'")
        for key,value in (("project_id",project_id),("quadrant",quadrant)):
            if value is not None:
                terms.append(f"m.{key}=?");params.append(value)
        # Retrieve a bounded BM25 candidate pool, then apply only a 5% age adjustment.
        rows=self.db.execute_read("""SELECT m.*,bm25(memory_fts,2.0,1.0,1.0) AS fts_rank
            FROM memory_fts JOIN memory_entries m ON m.id=memory_fts.rowid
            WHERE """+" AND ".join(terms)+" ORDER BY fts_rank,m.id DESC LIMIT ?",tuple(params+[max(200,limit*5)]))
        now=datetime.now(timezone.utc)
        half_life=max(1,recency_half_life_hours or 24*30)
        for row in rows:
            age=max(0,(now-parse_timestamp_iso(row.get("updated_at") or row.get("created_at"))).total_seconds()/3600)
            weight=.95+.05*math.exp(-math.log(2)*age/half_life)
            relevance=max(0,-row.pop("fts_rank"))
            row.update(score=relevance*weight,bm25_score=relevance,recency_weight=weight,
                       age_hours=age,citation=f"owlthread://memory/{row['id']}")
        return sorted(rows,key=lambda row:(row["score"],row["id"]),reverse=True)[:limit]

    def search_captures(self,query: str,limit: int = 12,project_id: int | None = None,
                        recency_half_life_hours: float | None = None) -> list[dict[str,Any]]:
        """Search the durable raw capture log, including skipped and failed extraction."""
        if not isinstance(query,str) or len(query)>4000:
            raise ValueError("Search query must be at most 4000 characters")
        if type(limit) is not int:
            raise ValueError("Invalid search limit")
        if limit<=0:
            return []
        limit=min(limit,200)
        expression=match_expression(query)
        params: list[Any]=[]
        terms: list[str]=[]
        if expression:
            terms.append("capture_fts MATCH ?")
            params.append(expression)
        elif query.strip():
            return []
        if project_id is not None:
            terms.append("c.project_id=?")
            params.append(project_id)
        where=" WHERE "+" AND ".join(terms) if terms else ""
        if expression:
            rows=self.db.execute_read("""SELECT c.id,c.raw_text,c.source_app,c.captured_at,c.project_id,
                c.source_metadata,c.processed,c.processed_chars,c.extraction_status,c.extraction_reason,c.attempts,
                bm25(capture_fts,1.0) AS fts_rank
                FROM capture_fts JOIN capture_buffer c ON c.id=capture_fts.rowid"""+where+
                " ORDER BY fts_rank,c.id DESC LIMIT ?",tuple(params+[max(200,limit*5)]))
        else:
            rows=self.db.execute_read("""SELECT c.id,c.raw_text,c.source_app,c.captured_at,c.project_id,
                c.source_metadata,c.processed,c.processed_chars,c.extraction_status,c.extraction_reason,c.attempts,
                0.0 AS fts_rank FROM capture_buffer c"""+where+" ORDER BY c.id DESC LIMIT ?",tuple(params+[limit]))
        now=datetime.now(timezone.utc)
        half_life=max(1,recency_half_life_hours or 24*30)
        for row in rows:
            age=max(0,(now-parse_timestamp_iso(row.get("captured_at"))).total_seconds()/3600)
            weight=.95+.05*math.exp(-math.log(2)*age/half_life)
            relevance=1.0 if not expression else max(0,-row.pop("fts_rank"))
            row.update(score=relevance*weight,bm25_score=0.0 if not expression else relevance,
                       recency_weight=weight,age_hours=age,context_kind="capture",
                       citation=f"[C#{row['id']}]")
        return sorted(rows,key=lambda row:(row["score"],row["id"]),reverse=True)[:limit]

    def search_context(self,query: str,project_id: int | None = None,per_quadrant_limit: int = 12,
                       capture_limit: int | None = None,char_budget: int = 12000,
                       include_history: bool = False) -> dict[str,Any]:
        """Fan out locally, diversify, de-duplicate and pack cited context to a hard budget."""
        if type(char_budget) is not int or not 256<=char_budget<=100_000:
            raise ValueError("char_budget must be an integer from 256 to 100000")
        if type(per_quadrant_limit) is not int or not 1<=per_quadrant_limit<=200:
            raise ValueError("per_quadrant_limit must be an integer from 1 to 200")
        if capture_limit is None:
            capture_limit=per_quadrant_limit
        if type(capture_limit) is not int or not 0<=capture_limit<=200:
            raise ValueError("capture_limit must be an integer from 0 to 200")

        streams=[self.search(query,limit=per_quadrant_limit,project_id=project_id,quadrant=quadrant,
                             include_history=include_history) for quadrant in QUADRANT_ORDER]
        streams.append(self.search_captures(query,limit=capture_limit,project_id=project_id))
        candidates=[]
        for index in range(max((len(stream) for stream in streams),default=0)):
            for stream in streams:
                if index<len(stream):
                    candidates.append(stream[index])

        unique=[]
        seen=set()
        for row in candidates:
            kind=row.get("context_kind","memory")
            body=row.get("summary") or row.get("raw_text") or ""
            key=_compact(body).casefold().rstrip(".!。")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append({**row,"context_kind":kind})

        lines: list[str]=[]
        packed: list[dict[str,Any]]=[]
        body_was_trimmed=False
        for row in unique:
            if row["context_kind"]=="capture":
                citation=f"[C#{row['id']}]"
                label=f"raw evidence · {row.get('source_app') or 'capture'}"
                body=_evidence_excerpt(row.get("raw_text") or "",query,800)
            else:
                citation=f"[#{row['id']}]"
                label=str(row.get("quadrant") or "memory").replace("_"," ")
                body=_compact(row.get("summary") or row.get("raw_text") or "")[:480]
            prefix=f"- {citation} {label}: "
            separator="\n" if lines else ""
            remaining=char_budget-len("\n".join(lines))-len(separator)
            if remaining<=len(prefix):
                break
            allowed=remaining-len(prefix)
            rendered_body=body[:allowed]
            if len(rendered_body)<len(body):
                rendered_body=rendered_body.rstrip()+"…"
                if len(rendered_body)>allowed:
                    rendered_body=rendered_body[:allowed]
                body_was_trimmed=True
            line=prefix+rendered_body
            lines.append(line)
            packed.append({**row,"citation":citation,"context_excerpt":rendered_body})
            if len("\n".join(lines))>=char_budget:
                break
        context_text="\n".join(lines)
        return {"items":packed,"context_text":context_text,"chars_used":len(context_text),
                "char_budget":char_budget,"truncated":body_was_trimmed or len(packed)<len(unique),
                "candidates_considered":len(unique),
                "memory_count":sum(row["context_kind"]!="capture" for row in packed),
                "capture_count":sum(row["context_kind"]=="capture" for row in packed)}
