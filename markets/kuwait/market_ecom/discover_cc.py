"""Common Crawl CDX index discovery (resumable per crawl/pattern/page)."""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import random
import re

import httpx

from . import db
from .common import identity

ECOM_PATH = re.compile(
    r"/(?:products?|collections|cart|checkout|shop|store|category|categories|catalog|item|p/|"
    r"index\.php\?route=product|product-category|brand|offers|%D9%85%D9%86%D8%AA%D8%AC|منتج)|"
    r"/p\d{5,}|-p-\d+|\.html$",
    re.I,
)

PATTERNS = {
    # pattern: (matchType, base priority, max crawls)
    "kw": ("domain", 3, 24),
    "ordable.com": ("domain", 4, 12),
    "zyda.com": ("domain", 1, 6),
    "myshopify.com": ("domain", 0, 2),
    "expandcart.com": ("domain", 1, 4),
    "salla.sa": ("prefix", 0, 2),
    "zid.store": ("domain", 0, 3),
    "ecwid.com": ("domain", 0, 2),
    "company.site": ("domain", 0, 2),
}

UA = {"User-Agent": "market-ecom-directory-research/1.0 (+https://github.com; polite CDX client)"}


async def get_with_retry(client, url, params, tries=7):
    delay = 4
    for i in range(tries):
        try:
            r = await client.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return r
            if r.status_code in (400, 404):
                return r
        except (httpx.HTTPError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(delay + random.random() * 2)
        delay = min(delay * 2, 64)
    return None


def harvest(text, base_pr):
    hits = collections.defaultdict(int)
    urls = {}
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        u = rec.get("url", "")
        ident = identity(u)
        if not ident:
            continue
        k = ident["key"]
        urls.setdefault(k, u)
        if ECOM_PATH.search(u):
            hits[k] += 1
    out = []
    for k, u in urls.items():
        pr = base_pr
        if hits[k]:
            pr += 3 if hits[k] >= 3 else 2
        out.append((u, pr))
    return out


async def run_job(client, con, sem, crawl, api, pattern, mt, page, base_pr, stats):
    job = f"{crawl}|{pattern}|{page}"
    if db.job_done(con, "cc", job):
        return
    async with sem:
        r = await get_with_retry(client, api, {"url": pattern, "matchType": mt, "output": "json", "fl": "url", "page": str(page)})
    if r is None:
        db.mark_job(con, "cc", job, "failed")
        stats["failed"] += 1
        return
    if r.status_code in (400, 404):
        db.mark_job(con, "cc", job, "done", 0, 0, f"{r.status_code} no captures / page out of range")
        return
    items = harvest(r.text, base_pr)
    new = db.add_candidates(con, items, source=f"commoncrawl:{pattern}", detail=crawl)
    db.mark_job(con, "cc", job, "done", len(items), new)
    stats["jobs"] += 1
    stats["new"] += new
    print(f"[cc] {job} keys={len(items)} new={new} total_new={stats['new']}", flush=True)


async def num_pages(client, api, pattern, mt):
    r = await get_with_retry(client, api, {"url": pattern, "matchType": mt, "showNumPages": "true"}, tries=3)
    if r is None or r.status_code != 200:
        return None
    try:
        return int(r.json()["pages"])
    except Exception:
        return None


async def main(patterns, concurrency, max_crawls_override=None):
    con = db.connect()
    db.register_source(con, "commoncrawl", "index", "Common Crawl CDX index API (index.commoncrawl.org)")
    db.heartbeat(con, "discover_cc", "code-worker(asyncio)", concurrency, {"patterns": patterns})
    async with httpx.AsyncClient(headers=UA, follow_redirects=True) as client:
        r = None
        while r is None:
            r = await get_with_retry(client, "https://index.commoncrawl.org/collinfo.json", None)
            if r is None:
                await asyncio.sleep(120)
        crawls = r.json()
        sem = asyncio.Semaphore(concurrency)
        stats = collections.Counter()
        tasks = []
        for pattern in patterns:
            mt, pr, maxc = PATTERNS[pattern]
            if max_crawls_override:
                maxc = max_crawls_override
            for c in crawls[:maxc]:
                key = f"pages|{c['id']}|{pattern}"
                row = con.execute("SELECT info FROM jobs WHERE kind='ccpages' AND job=?", (key,)).fetchone()
                if row:
                    n = int(row[0])
                else:
                    async with sem:
                        n = await num_pages(client, c["cdx-api"], pattern, mt)
                    if n is None:
                        n = 12 if pattern == "kw" else None
                        print(f"[cc] could not size {c['id']} {pattern}; fallback pages={n}", flush=True)
                        if n is None:
                            continue
                    db.mark_job(con, "ccpages", key, "done", n, 0, str(n))
                await asyncio.gather(*[run_job(client, con, sem, c["id"], c["cdx-api"], pattern, mt, p, pr, stats) for p in range(n)])
            db.heartbeat(con, "discover_cc", "code-worker(asyncio)", concurrency, dict(stats))
        print("[cc] done", dict(stats), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patterns", default="kw,ordable.com")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--max-crawls", type=int, default=None)
    a = ap.parse_args()
    asyncio.run(main(a.patterns.split(","), a.concurrency, a.max_crawls))
