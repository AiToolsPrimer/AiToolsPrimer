"""SQLite-backed agency memory: content, assets, actions, approvals, metrics,
scout findings and a small vector index for semantic recall.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,            -- post | article | video | short | image | reply
  platform TEXT NOT NULL,
  topic TEXT,
  title TEXT,
  body TEXT,
  assets TEXT,                   -- JSON list of asset ids
  status TEXT NOT NULL,          -- draft | queued | approved | published | rejected | failed
  scheduled_for TEXT,
  published_at TEXT,
  remote_id TEXT,
  remote_url TEXT,
  meta TEXT                      -- JSON
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,            -- image | video | audio | music | srt | script
  path TEXT NOT NULL,
  prompt TEXT,
  model TEXT,
  meta TEXT
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  platform TEXT NOT NULL,
  verdict TEXT NOT NULL,
  reason TEXT,
  content_id INTEGER,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS http_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  method TEXT, url TEXT, blocked INTEGER, reason TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  platform TEXT NOT NULL,
  content_id INTEGER,
  remote_id TEXT,
  impressions INTEGER, likes INTEGER, replies INTEGER, shares INTEGER, clicks INTEGER, followers INTEGER,
  raw TEXT
);
CREATE TABLE IF NOT EXISTS engagement (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  platform TEXT NOT NULL,
  content_id INTEGER,
  remote_comment_id TEXT UNIQUE,
  author TEXT,
  text TEXT,
  replied INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scout (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  found_at TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  kind TEXT,
  free INTEGER,
  has_api INTEGER,
  fit_score REAL,
  rationale TEXT,
  signup_kit TEXT,               -- JSON
  status TEXT NOT NULL           -- found | kit_ready | registered | dismissed
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  source TEXT NOT NULL,          -- analyst | director | human
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  found_at TEXT NOT NULL,
  platform TEXT NOT NULL,
  summary TEXT NOT NULL,
  field TEXT,
  new_value TEXT,
  source TEXT,
  confidence REAL,
  status TEXT NOT NULL,          -- proposed | applied | dismissed
  UNIQUE(platform, summary)
);
CREATE TABLE IF NOT EXISTS knowledge_checks (
  platform TEXT PRIMARY KEY,
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  url TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  facts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  content_id INTEGER,
  platform TEXT,
  kind TEXT,
  original TEXT NOT NULL,
  edited TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_urls (
  url TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  submitted_at TEXT
);
CREATE TABLE IF NOT EXISTS vectors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref_table TEXT NOT NULL,
  ref_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  vec TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_status ON content(status);
CREATE INDEX IF NOT EXISTS idx_actions_at ON actions(at);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class Store:
    path: Path
    embed: Callable[[list[str]], list[list[float]]] | None = None

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.executescript(SCHEMA)

    # ----------------------------------------------------------------- helpers
    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock, self.conn:
            return self.conn.execute(sql, tuple(params))

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    # ----------------------------------------------------------------- content
    def add_content(self, kind: str, platform: str, *, topic: str = "", title: str = "", body: str = "", assets: list[int] | None = None, status: str = "draft", scheduled_for: str | None = None, meta: dict[str, Any] | None = None) -> int:
        cur = self._exec(
            "INSERT INTO content(created_at,kind,platform,topic,title,body,assets,status,scheduled_for,meta) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (utcnow(), kind, platform, topic, title, body, json.dumps(assets or []), status, scheduled_for, json.dumps(meta or {})),
        )
        cid = int(cur.lastrowid)
        self.index_text("content", cid, f"{title}\n{body}"[:4000])
        return cid

    def update_content(self, cid: int, **fields: Any) -> None:
        if not fields:
            return
        for k in ("assets", "meta"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k])
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE content SET {cols} WHERE id=?", (*fields.values(), cid))

    def get_content(self, cid: int) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM content WHERE id=?", (cid,))
        return _decode(rows[0]) if rows else None

    def list_content(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self._rows("SELECT * FROM content WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            rows = self._rows("SELECT * FROM content ORDER BY id DESC LIMIT ?", (limit,))
        return [_decode(r) for r in rows]

    def recent_topics(self, days: int = 30) -> list[str]:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        rows = self._rows("SELECT DISTINCT topic FROM content WHERE created_at>=? AND topic!='' ORDER BY id DESC", (since,))
        return [r["topic"] for r in rows]

    # ----------------------------------------------------------------- assets
    def add_asset(self, kind: str, path: Path | str, *, prompt: str = "", model: str = "", meta: dict[str, Any] | None = None) -> int:
        cur = self._exec("INSERT INTO assets(created_at,kind,path,prompt,model,meta) VALUES(?,?,?,?,?,?)", (utcnow(), kind, str(path), prompt, model, json.dumps(meta or {})))
        return int(cur.lastrowid)

    def get_asset(self, aid: int) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM assets WHERE id=?", (aid,))
        return _decode(rows[0]) if rows else None

    def list_assets(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if kind:
            return [_decode(r) for r in self._rows("SELECT * FROM assets WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))]
        return [_decode(r) for r in self._rows("SELECT * FROM assets ORDER BY id DESC LIMIT ?", (limit,))]

    # ----------------------------------------------------------------- actions / audit
    def log_action(self, kind: str, platform: str, verdict: str, reason: str, content_id: int | None = None, payload: dict[str, Any] | None = None) -> int:
        cur = self._exec("INSERT INTO actions(at,kind,platform,verdict,reason,content_id,payload) VALUES(?,?,?,?,?,?,?)", (utcnow(), kind, platform, verdict, reason, content_id, json.dumps(payload or {})[:4000]))
        return int(cur.lastrowid)

    def count_recent_actions(self, platform: str, kind: str, window: dt.timedelta, verdict: str = "allow") -> int:
        since = (dt.datetime.now(dt.timezone.utc) - window).isoformat()
        if platform == "*browser*":
            rows = self._rows("SELECT COUNT(*) AS n FROM actions WHERE kind IN ('browser_publish','browser_comment') AND verdict=? AND at>=?", (verdict, since))
        elif platform == "*":
            rows = self._rows("SELECT COUNT(*) AS n FROM actions WHERE kind=? AND verdict=? AND at>=?", (kind, verdict, since))
        else:
            rows = self._rows("SELECT COUNT(*) AS n FROM actions WHERE platform=? AND kind=? AND verdict=? AND at>=?", (platform, kind, verdict, since))
        return int(rows[0]["n"])

    def list_actions(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,))

    def audit_http(self, record: dict[str, Any]) -> None:
        self._exec("INSERT INTO http_audit(at,method,url,blocked,reason) VALUES(?,?,?,?,?)", (utcnow(), record.get("method"), record.get("url"), int(bool(record.get("blocked"))), record.get("reason")))

    def list_http_audit(self, limit: int = 200, blocked_only: bool = False) -> list[dict[str, Any]]:
        if blocked_only:
            return self._rows("SELECT * FROM http_audit WHERE blocked=1 ORDER BY id DESC LIMIT ?", (limit,))
        return self._rows("SELECT * FROM http_audit ORDER BY id DESC LIMIT ?", (limit,))

    # ----------------------------------------------------------------- metrics / engagement
    def add_metrics(self, platform: str, content_id: int | None, remote_id: str | None, **m: Any) -> None:
        self._exec(
            "INSERT INTO metrics(at,platform,content_id,remote_id,impressions,likes,replies,shares,clicks,followers,raw) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (utcnow(), platform, content_id, remote_id, m.get("impressions"), m.get("likes"), m.get("replies"), m.get("shares"), m.get("clicks"), m.get("followers"), json.dumps(m.get("raw", {}))),
        )

    def metrics_summary(self, days: int = 14) -> list[dict[str, Any]]:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        return self._rows(
            "SELECT m.platform, c.kind, c.topic, c.title, MAX(m.impressions) AS impressions, MAX(m.likes) AS likes, MAX(m.replies) AS replies, MAX(m.shares) AS shares, MAX(m.clicks) AS clicks "
            "FROM metrics m LEFT JOIN content c ON c.id=m.content_id WHERE m.at>=? GROUP BY m.platform, m.content_id ORDER BY impressions DESC LIMIT 50",
            (since,),
        )

    def add_engagement(self, platform: str, content_id: int | None, remote_comment_id: str, author: str, text: str) -> bool:
        try:
            self._exec("INSERT INTO engagement(at,platform,content_id,remote_comment_id,author,text) VALUES(?,?,?,?,?,?)", (utcnow(), platform, content_id, remote_comment_id, author, text))
            return True
        except sqlite3.IntegrityError:
            return False

    def pending_engagement(self, platform: str | None = None) -> list[dict[str, Any]]:
        if platform:
            return self._rows("SELECT * FROM engagement WHERE replied=0 AND platform=? ORDER BY id", (platform,))
        return self._rows("SELECT * FROM engagement WHERE replied=0 ORDER BY id")

    def mark_replied(self, eid: int) -> None:
        self._exec("UPDATE engagement SET replied=1 WHERE id=?", (eid,))

    # ----------------------------------------------------------------- scout
    def add_scout(self, name: str, url: str, kind: str, free: bool | None, has_api: bool | None, fit_score: float, rationale: str) -> int | None:
        try:
            cur = self._exec("INSERT INTO scout(found_at,name,url,kind,free,has_api,fit_score,rationale,status) VALUES(?,?,?,?,?,?,?,?,'found')", (utcnow(), name, url, kind, None if free is None else int(free), None if has_api is None else int(has_api), fit_score, rationale))
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def set_scout_kit(self, sid: int, kit: dict[str, Any]) -> None:
        self._exec("UPDATE scout SET signup_kit=?, status='kit_ready' WHERE id=?", (json.dumps(kit), sid))

    def set_scout_status(self, sid: int, status: str) -> None:
        self._exec("UPDATE scout SET status=? WHERE id=?", (status, sid))

    def list_scout(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM scout WHERE status=? ORDER BY fit_score DESC", (status,)) if status else self._rows("SELECT * FROM scout ORDER BY fit_score DESC")
        for r in rows:
            r["signup_kit"] = json.loads(r["signup_kit"]) if r.get("signup_kit") else None
        return rows

    # ----------------------------------------------------------------- site urls (IndexNow)
    def new_site_urls(self, urls: list[str]) -> list[str]:
        known = {r["url"] for r in self._rows("SELECT url FROM site_urls")}
        fresh = [u for u in urls if u not in known]
        for u in fresh:
            self._exec("INSERT OR IGNORE INTO site_urls(url,first_seen) VALUES(?,?)", (u, utcnow()))
        return fresh

    def mark_site_urls_submitted(self, urls: list[str]) -> None:
        for u in urls:
            self._exec("UPDATE site_urls SET submitted_at=? WHERE url=?", (utcnow(), u))

    # ----------------------------------------------------------------- facts & corrections
    def get_facts(self, url: str, max_age_days: int = 14) -> list[dict[str, Any]] | None:
        rows = self._rows("SELECT * FROM facts WHERE url=?", (url,))
        if not rows:
            return None
        if rows[0]["at"] < (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)).isoformat():
            return None
        return json.loads(rows[0]["facts"])

    def set_facts(self, url: str, facts: list[dict[str, Any]]) -> None:
        self._exec("INSERT INTO facts(url,at,facts) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET at=excluded.at, facts=excluded.facts", (url, utcnow(), json.dumps(facts)))

    def add_correction(self, content_id: int | None, platform: str, kind: str, original: str, edited: str) -> int:
        cur = self._exec("INSERT INTO corrections(at,content_id,platform,kind,original,edited) VALUES(?,?,?,?,?,?)", (utcnow(), content_id, platform, kind, original, edited))
        return int(cur.lastrowid)

    def list_corrections(self, limit: int = 500) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM corrections ORDER BY id DESC LIMIT ?", (limit,))

    def count_corrections(self) -> int:
        return int(self._rows("SELECT COUNT(*) AS n FROM corrections")[0]["n"])

    # ----------------------------------------------------------------- knowledge
    def add_knowledge_update(self, platform: str, summary: str, field: str, new_value: str, source: str, confidence: float) -> int | None:
        try:
            cur = self._exec("INSERT INTO knowledge_updates(found_at,platform,summary,field,new_value,source,confidence,status) VALUES(?,?,?,?,?,?,?,'proposed')", (utcnow(), platform, summary, field, new_value, source, confidence))
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def get_knowledge_update(self, uid: int) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM knowledge_updates WHERE id=?", (uid,))
        return rows[0] if rows else None

    def list_knowledge_updates(self, status: str | None = "proposed") -> list[dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM knowledge_updates WHERE status=? ORDER BY confidence DESC, id DESC", (status,))
        return self._rows("SELECT * FROM knowledge_updates ORDER BY id DESC")

    def set_knowledge_update_status(self, uid: int, status: str) -> None:
        self._exec("UPDATE knowledge_updates SET status=? WHERE id=?", (status, uid))

    def touch_knowledge_check(self, platform: str) -> None:
        self._exec("INSERT INTO knowledge_checks(platform,checked_at) VALUES(?,?) ON CONFLICT(platform) DO UPDATE SET checked_at=excluded.checked_at", (platform, utcnow()))

    def knowledge_checks(self) -> dict[str, str]:
        return {r["platform"]: r["checked_at"] for r in self._rows("SELECT * FROM knowledge_checks")}

    # ----------------------------------------------------------------- notes & vectors
    def add_note(self, source: str, text: str) -> int:
        cur = self._exec("INSERT INTO notes(at,source,text) VALUES(?,?,?)", (utcnow(), source, text))
        nid = int(cur.lastrowid)
        self.index_text("notes", nid, text[:4000])
        return nid

    def recent_notes(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,))

    def index_text(self, ref_table: str, ref_id: int, text: str) -> None:
        if not self.embed or not text.strip():
            return
        try:
            vec = self.embed([text])[0]
        except Exception:
            return
        self._exec("INSERT INTO vectors(ref_table,ref_id,text,vec) VALUES(?,?,?,?)", (ref_table, ref_id, text, json.dumps(vec)))

    def recall(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Semantic recall; falls back to keyword match when no embedder is configured."""
        if not self.embed:
            words = [w for w in query.lower().split() if len(w) > 3]
            rows = self._rows("SELECT ref_table, ref_id, text FROM vectors") or []
            if not rows:
                rows = [{"ref_table": "content", "ref_id": r["id"], "text": f"{r['title']}\n{r['body']}"} for r in self._rows("SELECT id,title,body FROM content ORDER BY id DESC LIMIT 500")]
            scored = [(sum(w in (r["text"] or "").lower() for w in words), r) for r in rows]
            return [r for s, r in sorted(scored, key=lambda x: -x[0]) if s > 0][:k]
        q = self.embed([query])[0]
        rows = self._rows("SELECT ref_table, ref_id, text, vec FROM vectors")
        scored = []
        for r in rows:
            v = json.loads(r["vec"])
            scored.append((_cosine(q, v), {"ref_table": r["ref_table"], "ref_id": r["ref_id"], "text": r["text"]}))
        return [r for _, r in sorted(scored, key=lambda x: -x[0])[:k]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    for k in ("assets", "meta"):
        if k in row and isinstance(row[k], str):
            try:
                row[k] = json.loads(row[k])
            except json.JSONDecodeError:
                pass
    return row
