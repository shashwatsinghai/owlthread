"""Relevance search over memory_entries using keyword and recency scoring with active status filtering."""

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from owlthread.db.database import Database

# Common stop words to exclude from keyword extraction
STOP_WORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "want", "like", "need", "going"
}


def extract_keywords(text: str) -> List[str]:
    """
    Extract meaningful keywords from user query, preserving technical terms.
    """
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Z0-9_\-\.]{2,}", text.lower())
    keywords = [tok for tok in tokens if tok not in STOP_WORDS and len(tok) >= 2]
    return keywords


def parse_timestamp_iso(ts_str: Optional[str]) -> datetime:
    """Parse ISO timestamp with fallback to current UTC time."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


class MemorySearcher:
    """
    Searches memory_entries across all quadrants using keyword relevance and recency scoring.
    Filters status='active' by default with optional include_history toggle.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def search(
        self,
        query: str,
        limit: int = 15,
        recency_half_life_hours: float = 72.0,
        include_history: bool = False,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search memory entries relevant to query.
        
        Args:
            query: User's task or search query.
            limit: Maximum number of relevant entries to return.
            recency_half_life_hours: Hours for recency score to decay by half.
            include_history: If True, includes superseded/historical entries; otherwise status='active' only.
            project_id: Optional project filter.
            
        Returns:
            List of matching memory entries with 'score', 'keyword_score', and 'recency_weight'.
        """
        keywords = extract_keywords(query)
        now = datetime.now(timezone.utc)

        # Retrieve candidate entries from SQLite database
        candidates = self._fetch_candidates(
            keywords=keywords,
            candidate_pool_limit=100,
            include_history=include_history,
            project_id=project_id
        )
        if not candidates:
            return []

        scored_entries: List[Dict[str, Any]] = []
        clean_query = query.strip().lower()

        for row in candidates:
            summary_text = (row.get("summary") or "").lower()
            raw_text = (row.get("raw_text") or "").lower()
            combined_text = f"{summary_text} {raw_text}"

            # 1. Keyword scoring
            kw_score = 0.0
            if keywords:
                # Exact phrase match bonus
                if len(clean_query) > 3 and clean_query in summary_text:
                    kw_score += 20.0
                elif len(clean_query) > 3 and clean_query in raw_text:
                    kw_score += 15.0

                # Individual keyword matches (summary matches weighted higher than raw body)
                matched_kw_count = 0
                for kw in keywords:
                    count_sum = summary_text.count(kw)
                    count_raw = raw_text.count(kw)
                    if count_sum > 0 or count_raw > 0:
                        matched_kw_count += 1
                        kw_score += 5.0 * min(count_sum, 3) + 2.0 * min(count_raw, 4)

                # Bonus for matching multiple distinct query keywords
                if len(keywords) > 1:
                    match_ratio = matched_kw_count / len(keywords)
                    kw_score += match_ratio * 12.0
            else:
                kw_score = 1.0

            # 2. Recency scoring
            entry_ts = parse_timestamp_iso(row.get("timestamp"))
            age_hours = max(0.0, (now - entry_ts).total_seconds() / 3600.0)
            
            # Exponential decay: score decays with half-life, with a baseline floor of 0.25
            decay_lambda = math.log(2) / max(1.0, recency_half_life_hours)
            recency_weight = 0.25 + 0.75 * math.exp(-decay_lambda * age_hours)

            # 3. Composite score calculation
            if keywords and kw_score == 0.0:
                final_score = 0.0
            else:
                final_score = kw_score * recency_weight

            if final_score > 0:
                entry_dict = dict(row)
                entry_dict["score"] = round(final_score, 3)
                entry_dict["keyword_score"] = round(kw_score, 3)
                entry_dict["recency_weight"] = round(recency_weight, 3)
                entry_dict["age_hours"] = round(age_hours, 1)
                scored_entries.append(entry_dict)

        # Sort by final score descending
        scored_entries.sort(key=lambda x: x["score"], reverse=True)
        return scored_entries[:limit]

    def _fetch_candidates(
        self,
        keywords: List[str],
        candidate_pool_limit: int = 100,
        include_history: bool = False,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch candidates using SQL query filtering by status and keywords."""
        with self.db._lock, self.db.connection() as conn:
            cursor = conn.cursor()

            base_conditions = []
            base_params = []

            if not include_history:
                base_conditions.append("status = 'active'")

            if project_id is not None:
                base_conditions.append("project_id = ?")
                base_params.append(project_id)

            if not keywords:
                where_str = f"WHERE {' AND '.join(base_conditions)}" if base_conditions else ""
                sql = f"""
                    SELECT id, project_id, timestamp, source_app, raw_text, quadrant, summary, status, superseded_by
                    FROM memory_entries
                    {where_str}
                    ORDER BY id DESC
                    LIMIT ?
                """
                params = base_params + [candidate_pool_limit]
                cursor.execute(sql, params)
                return [dict(r) for r in cursor.fetchall()]

            # Build SQL with LIKE clauses across summary and raw_text
            kw_conditions = []
            kw_params = []
            for kw in keywords[:8]:
                pattern = f"%{kw}%"
                kw_conditions.append("(summary LIKE ? OR raw_text LIKE ?)")
                kw_params.extend([pattern, pattern])

            kw_where_clause = " OR ".join(kw_conditions)
            all_conditions = base_conditions + [f"({kw_where_clause})"]
            where_sql = f"WHERE {' AND '.join(all_conditions)}"

            sql = f"""
                SELECT id, project_id, timestamp, source_app, raw_text, quadrant, summary, status, superseded_by
                FROM memory_entries
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
            """
            params = base_params + kw_params + [candidate_pool_limit]

            cursor.execute(sql, params)
            matches = [dict(r) for r in cursor.fetchall()]

            # If fewer than 10 matches found, also include some recent active entries as fallback context
            if len(matches) < 10:
                fallback_where = f"WHERE {' AND '.join(base_conditions)}" if base_conditions else ""
                cursor.execute(
                    f"""
                    SELECT id, project_id, timestamp, source_app, raw_text, quadrant, summary, status, superseded_by
                    FROM memory_entries
                    {fallback_where}
                    ORDER BY id DESC
                    LIMIT 20
                    """,
                    base_params
                )
                recent = [dict(r) for r in cursor.fetchall()]
                existing_ids = {m["id"] for m in matches}
                for r in recent:
                    if r["id"] not in existing_ids:
                        matches.append(r)

            return matches
