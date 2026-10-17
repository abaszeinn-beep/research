"""Shared state + helpers for the usa_shopify shard (SQLite, normalization, identity)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import tldextract

HERE = os.path.dirname(os.path.abspath(__file__))
SHARD_DIR = os.path.dirname(HERE)
WORK = os.path.join(SHARD_DIR, "work")
DB_PATH = os.environ.get("USA_SHOPIFY_DB", os.path.join(WORK, "usa_shopify.sqlite"))

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": "usa-ecom-directory-research/1.0 (+https://github.com/abaszeinn-beep/research; store verification)",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
           "Accept-Language": "en-US,en;q=0.9"}
INDEX_UA = {"User-Agent": "usa-ecom-directory-research/1.0 (polite index client)"}

NON_STORE_ROOTS = {
    "shopify.com", "shopifycdn.com", "shopifysvc.com", "shopifyapps.com", "shopifycloud.com", "shop.app",
    "myshopify.io", "google.com", "facebook.com", "instagram.com", "youtube.com", "twitter.com", "x.com",
    "tiktok.com", "pinterest.com", "linkedin.com", "wikipedia.org", "apple.com", "microsoft.com",
    "github.com", "reddit.com", "medium.com", "wordpress.com", "blogspot.com", "cloudflare.com",
    "amazonaws.com", "cloudfront.net", "archive.org", "commoncrawl.org", "w3.org", "schema.org",
    "linktr.ee", "bit.ly", "squarespace.com", "wix.com", "godaddy.com", "bigcommerce.com",
}
MARKETPLACE_ROOTS = {
    "amazon.com", "ebay.com", "etsy.com", "temu.com", "aliexpress.com", "alibaba.com", "poshmark.com",
    "mercari.com", "walmart.com", "wish.com", "shein.com", "depop.com", "faire.com", "wayfair.com",
    "target.com", "bestbuy.com", "newegg.com", "overstock.com", "rakuten.com", "grailed.com",
    "therealreal.com", "stockx.com", "goat.com", "offerup.com", "craigslist.org", "reverb.com",
}
# Country-code TLDs that essentially never host a US storefront; queued at much lower priority.
FOREIGN_CC = {
    "uk", "ca", "au", "nz", "de", "fr", "es", "it", "nl", "be", "ch", "at", "se", "no", "dk", "fi", "ie",
    "pl", "pt", "cz", "sk", "hu", "ro", "bg", "gr", "tr", "ru", "ua", "il", "ae", "sa", "qa", "kw", "eg",
    "za", "ng", "ke", "in", "pk", "bd", "lk", "jp", "kr", "cn", "tw", "hk", "sg", "my", "id", "th", "vn",
    "ph", "br", "ar", "cl", "mx", "pe", "uy", "lt", "lv", "ee", "si", "hr", "rs", "is", "lu", "cy", "mt",
    "eu", "co.uk", "com.au",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def registrable(host: str) -> str:
    ext = _TLD(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return host.lower()


def suffix(host: str) -> str:
    return _TLD(host).suffix.lower()


def is_foreign_tld(host: str) -> bool:
    return suffix(host).split(".")[-1] in FOREIGN_CC


def clean_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".").split("@")[-1].split(":")[0]
    if re.match(r"^www\d?\.", host):
        host = host.split(".", 1)[1]
    return host


def host_of(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


MYSHOPIFY_RESERVED = {"www", "admin", "partners", "checkout", "shop", "accounts", "help", "cdn", "api", "apps",
                      "community", "themes", "app", "status"}


def candidate_key(url_or_host: str):
    """Return (key, kind, fetch_host) or None.

    myshopify hosts keep `<x>.myshopify.com`; custom domains keep the host without `www.`
    (export merges by myshopify_domain / registrable domain)."""
    raw = host_of(url_or_host) if ("/" in url_or_host or ":" in url_or_host) else url_or_host.strip().lower()
    raw = (raw or "").lower().rstrip(".")
    if not raw or "." not in raw or re.match(r"^\d+\.\d+\.\d+\.\d+$", raw):
        return None
    if not re.match(r"^[a-z0-9.-]+$", raw):
        return None
    if raw.endswith(".myshopify.com"):
        sub = raw[: -len(".myshopify.com")]
        if not sub or "." in sub or sub in MYSHOPIFY_RESERVED:
            return None
        return raw, "myshopify", raw
    host = clean_host(raw)
    root = registrable(host)
    if root in NON_STORE_ROOTS or root in MARKETPLACE_ROOTS or "." not in root:
        return None
    if not suffix(host):
        return None
    return host, "custom", raw


SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
  key TEXT PRIMARY KEY, kind TEXT, fetch_host TEXT, priority REAL DEFAULT 0, sources TEXT DEFAULT '',
  hint TEXT DEFAULT '', state TEXT DEFAULT 'pending', added_utc TEXT
);
CREATE INDEX IF NOT EXISTS cand_state ON candidates(state, priority);
CREATE TABLE IF NOT EXISTS results (
  key TEXT PRIMARY KEY, status TEXT, reason TEXT, store_name TEXT, canonical_url TEXT, root_domain TEXT,
  myshopify_domain TEXT, platform TEXT, category TEXT, us_evidence TEXT, verification_url TEXT,
  verification_utc TEXT, currency TEXT, country TEXT, extra TEXT
);
CREATE INDEX IF NOT EXISTS res_myshop ON results(myshopify_domain);
CREATE INDEX IF NOT EXISTS res_root ON results(root_domain);
CREATE TABLE IF NOT EXISTS jobs (
  kind TEXT, job TEXT, status TEXT, n INTEGER, n_new INTEGER, info TEXT, utc TEXT, PRIMARY KEY (kind, job)
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=120, isolation_level=None)
    for attempt in range(30):
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(SCHEMA)
            return con
        except sqlite3.OperationalError:
            time.sleep(1 + attempt)
    raise RuntimeError("database stays locked")


def add_candidates(con, items, source: str) -> int:
    """items: iterable of (url_or_host, priority, hint). Returns number of new keys.

    Custom domains on foreign country-code TLDs are demoted so likely-US hosts are verified first."""
    rows = {}
    for u, pr, hint in items:
        ck = candidate_key(u)
        if not ck:
            continue
        key, kind, fh = ck
        if kind == "custom" and is_foreign_tld(key):
            pr -= 4
        if key in rows:
            if pr > rows[key][3]:
                rows[key] = (key, kind, fh, pr, hint or rows[key][4])
            continue
        rows[key] = (key, kind, fh, pr, hint or "")
    if not rows:
        return 0
    now = utcnow()
    for attempt in range(20):
        new = 0
        try:
            con.execute("BEGIN IMMEDIATE")
            for key, kind, fh, pr, hint in rows.values():
                cur = con.execute("INSERT OR IGNORE INTO candidates(key, kind, fetch_host, priority, sources, hint, added_utc) "
                                  "VALUES (?,?,?,?,?,?,?)", (key, kind, fh, pr, source, hint[:300], now))
                if cur.rowcount:
                    new += 1
                else:
                    con.execute("UPDATE candidates SET priority=MAX(priority, ?), "
                                "sources=CASE WHEN instr(','||sources||',', ','||?||',')>0 THEN sources ELSE sources||','||? END "
                                "WHERE key=?", (pr, source, source, key))
            con.execute("COMMIT")
            return new
        except sqlite3.OperationalError:
            try:
                con.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            time.sleep(1 + attempt)
    raise RuntimeError("could not write candidates")


def job_done(con, kind, job) -> bool:
    r = con.execute("SELECT status FROM jobs WHERE kind=? AND job=?", (kind, job)).fetchone()
    return bool(r and r[0] == "done")


def mark_job(con, kind, job, status, n=0, n_new=0, info=""):
    con.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)", (kind, job, status, n, n_new, info, utcnow()))


def set_meta(con, k, v):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))


def get_meta(con, k, default=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default
