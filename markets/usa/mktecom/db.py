"""SQLite shared state. WAL mode so several discovery/verification processes can write."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

from .common import identity, MARKETPLACE_ROOTS

from .market import M

DB_PATH = os.environ.get("MKT_ECOM_DB", os.path.join(os.path.dirname(__file__), "..", "data", f"{M.code}_ecom.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    root_domain TEXT,
    platform_hint TEXT,
    first_source TEXT,
    source_detail TEXT,
    discovered_at TEXT,
    status TEXT DEFAULT 'pending',      -- pending|in_progress|verified|rejected|unverified|duplicate
    priority INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    last_attempt TEXT
);
CREATE INDEX IF NOT EXISTS idx_cand_status ON candidates(status, priority DESC);
CREATE TABLE IF NOT EXISTS candidate_sources (
    key TEXT, source TEXT, detail TEXT, ts TEXT,
    PRIMARY KEY (key, source)
);
CREATE TABLE IF NOT EXISTS verifications (
    key TEXT PRIMARY KEY,
    final_url TEXT, final_key TEXT, http_status INTEGER,
    store_name TEXT, platform TEXT, category TEXT, subcategory TEXT,
    market_score REAL, market_evidence TEXT, ecom_evidence TEXT, product_evidence TEXT,
    status TEXT, reason TEXT, evidence_url TEXT, verified_at TEXT,
    duplicate_of TEXT, method TEXT, elapsed REAL, cat_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_ver_final ON verifications(final_key);
CREATE TABLE IF NOT EXISTS queries (
    engine TEXT, query TEXT, status TEXT, n_results INTEGER, n_new INTEGER, ts TEXT, workstream TEXT,
    PRIMARY KEY (engine, query)
);
CREATE TABLE IF NOT EXISTS jobs (
    kind TEXT, job TEXT, status TEXT, n INTEGER, n_new INTEGER, ts TEXT, info TEXT,
    PRIMARY KEY (kind, job)
);
CREATE TABLE IF NOT EXISTS sources (
    source TEXT PRIMARY KEY, type TEXT, description TEXT, status TEXT, notes TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS metrics (ts TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS workers (
    name TEXT PRIMARY KEY, kind TEXT, concurrency INTEGER, started TEXT, heartbeat TEXT, info TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, timeout=120, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(verifications)")}
    if "cat_text" not in cols:
        con.execute("ALTER TABLE verifications ADD COLUMN cat_text TEXT")
    return con


def add_candidates(con, urls, source: str, detail: str = "", priority: int = 0) -> int:
    """Insert candidate URLs (deduped by identity key). Returns number of new candidates."""
    ts = now()
    rows, srows = {}, {}
    for item in urls:
        if isinstance(item, tuple):
            u, pr = item
        else:
            u, pr = item, priority
        ident = identity(u)
        if not ident:
            continue
        k = ident["key"]
        if k not in rows or pr > rows[k][-1]:
            rows[k] = (k, ident["url"], ident["root_domain"], ident["platform_hint"], source, detail[:300], ts, pr)
        srows[k] = (k, source, detail[:300], ts)
    if not rows:
        return 0
    for _ in range(10):
        try:
            con.execute("BEGIN IMMEDIATE")
            before = con.total_changes
            con.executemany(
                "INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,first_source,source_detail,discovered_at,priority) VALUES (?,?,?,?,?,?,?,?)",
                list(rows.values()),
            )
            new = con.total_changes - before
            con.executemany(
                "UPDATE candidates SET priority=? WHERE key=? AND status='pending' AND priority<?",
                [(r[-1], r[0], r[-1]) for r in rows.values() if r[-1] > 0],
            )
            con.executemany("INSERT OR IGNORE INTO candidate_sources VALUES (?,?,?,?)", list(srows.values()))
            con.execute("COMMIT")
            return new
        except sqlite3.OperationalError:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            time.sleep(2)
    return 0


def register_source(con, source, type_, description, status="active", notes=""):
    con.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET status=excluded.status, notes=excluded.notes, ts=excluded.ts",
        (source, type_, description, status, notes, now()),
    )


def heartbeat(con, name, kind, concurrency, info=None):
    con.execute(
        "INSERT INTO workers VALUES (?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET heartbeat=excluded.heartbeat, info=excluded.info, concurrency=excluded.concurrency",
        (name, kind, concurrency, now(), now(), json.dumps(info or {}, ensure_ascii=False)),
    )


def job_done(con, kind, job):
    r = con.execute("SELECT status FROM jobs WHERE kind=? AND job=?", (kind, job)).fetchone()
    return bool(r and r[0] == "done")


def mark_job(con, kind, job, status, n=0, n_new=0, info=""):
    con.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?) ON CONFLICT(kind,job) DO UPDATE SET status=excluded.status,n=excluded.n,n_new=excluded.n_new,ts=excluded.ts,info=excluded.info",
        (kind, job, status, n, n_new, now(), info[:500]),
    )
