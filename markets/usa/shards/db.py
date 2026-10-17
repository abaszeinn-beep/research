"""SQLite state for the usa_other_platforms shard (resumable discovery + verification)."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
DB_PATH = os.environ.get("USA_SHARD_DB", os.path.join(WORK, "usa_other_platforms.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates(
  key TEXT PRIMARY KEY, url TEXT, root_domain TEXT, platform_hint TEXT, priority REAL DEFAULT 0,
  hits INTEGER DEFAULT 0, sample_url TEXT, status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
  last_attempt TEXT, first_seen TEXT, lang TEXT, tld TEXT);
CREATE INDEX IF NOT EXISTS cand_status ON candidates(status, priority);
CREATE TABLE IF NOT EXISTS candidate_sources(key TEXT, source TEXT, detail TEXT, PRIMARY KEY(key, source, detail));
CREATE TABLE IF NOT EXISTS jobs(kind TEXT, job TEXT, status TEXT, n INTEGER, new INTEGER, info TEXT, at TEXT, PRIMARY KEY(kind, job));
CREATE TABLE IF NOT EXISTS verifications(
  key TEXT PRIMARY KEY, final_url TEXT, final_key TEXT, http_status INTEGER, store_name TEXT, platform TEXT,
  category TEXT, us_score REAL, us_evidence TEXT, ecom_evidence TEXT, product_evidence TEXT, status TEXT, reason TEXT,
  evidence_url TEXT, verified_at TEXT, method TEXT, elapsed REAL);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=120, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


def retry(con, fn):
    for i in range(30):
        try:
            con.execute("BEGIN IMMEDIATE")
            out = fn()
            con.execute("COMMIT")
            return out
        except sqlite3.OperationalError:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            time.sleep(0.5 + i * 0.2)
    raise RuntimeError("sqlite busy")


def job_done(con, kind, job) -> bool:
    r = con.execute("SELECT status FROM jobs WHERE kind=? AND job=?", (kind, job)).fetchone()
    return bool(r and r[0] == "done")


def mark_job(con, kind, job, status, n=0, new=0, info=""):
    retry(con, lambda: con.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?)", (kind, job, status, n, new, info, now())))


def add_candidates(con, rows, source, detail=""):
    """rows: iterable of dicts with key,url,root_domain,platform_hint,priority,hits,sample_url,lang,tld."""
    rows = list(rows)

    def _do():
        new = 0
        ts = now()
        for r in rows:
            cur = con.execute(
                "INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,priority,hits,sample_url,first_seen,lang,tld) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (r["key"], r["url"], r["root_domain"], r.get("platform_hint"), r.get("priority", 0), r.get("hits", 0),
                 r.get("sample_url"), ts, r.get("lang"), r.get("tld")))
            if cur.rowcount:
                new += 1
            else:
                con.execute(
                    "UPDATE candidates SET hits=hits+?, priority=max(priority,?), "
                    "platform_hint=coalesce(platform_hint,?), sample_url=coalesce(sample_url,?) WHERE key=?",
                    (r.get("hits", 0), r.get("priority", 0), r.get("platform_hint"), r.get("sample_url"), r["key"]))
            con.execute("INSERT OR IGNORE INTO candidate_sources VALUES(?,?,?)", (r["key"], source, detail))
        return new

    return retry(con, _do)
