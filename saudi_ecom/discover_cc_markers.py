"""Common Crawl pass for Saudi storefront paths on non-.sa hosts.

The earlier harvest paged the CDX index for *.sa, salla.sa, *.zid.store and
*.myshopify.com. This module asks the same index whether recent crawls captured
a Saudi locale path (/en-sa, /sa-en, /ar-sa) on the top of the current Tranco
list, and pages two extra shared-platform suffixes (youcan.shop, wuilt.com)
that were not in that harvest. Captured URLs are queued as candidates; the
live verifier decides them. Robots and bot walls are not involved (CDX only).
"""
from __future__ import annotations

import argparse
import asyncio
import os

import httpx

from . import db
from .common import NON_STORE_ROOTS, identity
from .discover_cc import get_with_retry, harvest
from .discover_tranco import load_list

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
UA = {"User-Agent": "saudi-ecom-directory-research/1.0 (polite CDX client)"}
PATHS = ("en-sa", "sa-en", "ar-sa")
PLATFORMS = ("youcan.shop", "wuilt.com")


async def platform_pages(client, con, sem, crawls, max_crawls):
    new = 0
    for pattern in PLATFORMS:
        for crawl in crawls[:max_crawls]:
            key = f"pages|{crawl['id']}|{pattern}"
            row = con.execute("SELECT info FROM jobs WHERE kind='ccpages' AND job=?", (key,)).fetchone()
            if row:
                n = int(row[0])
            else:
                async with sem:
                    r = await get_with_retry(client, crawl["cdx-api"], {"url": pattern, "matchType": "domain", "showNumPages": "true"})
                if r is None or r.status_code != 200:
                    print(f"[cc-marker] no size {crawl['id']} {pattern}", flush=True)
                    continue
                try:
                    n = int(r.json()["pages"])
                except Exception:
                    continue
                db.mark_job(con, "ccpages", key, "done", n, 0, str(n))
            # one page is enough to see whether the zone has stores; cap at 3 pages
            for page in range(min(n, 3)):
                job = f"{crawl['id']}|{pattern}|{page}"
                if db.job_done(con, "cc", job):
                    continue
                async with sem:
                    r = await get_with_retry(client, crawl["cdx-api"], {
                        "url": pattern, "matchType": "domain", "output": "json", "fl": "url", "page": str(page),
                    })
                if r is None or r.status_code != 200:
                    db.mark_job(con, "cc", job, "failed")
                    continue
                items = harvest(r.text, 4)
                added = db.add_candidates(con, items, source=f"cc_marker:{pattern}", detail=crawl["id"])
                db.mark_job(con, "cc", job, "done", len(items), added)
                new += added
                print(f"[cc-marker] {job} keys={len(items)} new={added}", flush=True)
    return new


async def saudi_paths(client, con, sem, crawl, domains):
    """Prefix-query /en-sa, /sa-en, /ar-sa on each domain in one recent crawl."""
    api = crawl["cdx-api"]
    cid = crawl["id"]
    new = 0
    done = 0

    async def one(domain):
        nonlocal new, done
        job = f"{cid}|{domain}|sa-paths"
        if db.job_done(con, "cc_marker", job):
            return
        found = []
        for path in PATHS:
            async with sem:
                r = await get_with_retry(client, api, {
                    "url": f"{domain}/{path}", "matchType": "prefix", "output": "json",
                    "fl": "url,status", "filter": "status:200", "limit": "3",
                }, tries=4)
                await asyncio.sleep(0.2)
            if r is None or r.status_code != 200:
                continue
            for line in r.text.splitlines():
                if "http" in line and identity(line if line.startswith("http") else ""):
                    found.append(line)
                else:
                    # json objects
                    if '"url"' in line:
                        try:
                            import json
                            found.append(json.loads(line)["url"])
                        except Exception:
                            pass
            if found:
                break
        urls = []
        for u in found:
            if identity(u):
                urls.append((u, 7))
        added = db.add_candidates(con, urls, source="cc_marker:sa-path", detail=cid) if urls else 0
        db.mark_job(con, "cc_marker", job, "done", len(urls), added, cid)
        new += added
        done += 1
        if urls:
            print(f"[cc-marker] {domain} -> {urls[0][0]}", flush=True)
        if done % 100 == 0:
            print(f"[cc-marker] paths {done}/{len(domains)} new={new}", flush=True)

    await asyncio.gather(*(one(d) for d in domains))
    print(f"[cc-marker] path scan done new={new}", flush=True)
    return new


async def main(rank_limit, concurrency, platform_crawls):
    con = db.connect()
    db.register_source(con, "cc_marker", "index", "Common Crawl CDX: Saudi locale paths on top Tranco domains, plus youcan.shop and wuilt.com")
    async with httpx.AsyncClient(headers=UA, follow_redirects=True, timeout=60) as client:
        r = await get_with_retry(client, "https://index.commoncrawl.org/collinfo.json", None)
        if r is None:
            print("[cc-marker] collinfo failed", flush=True)
            return
        crawls = r.json()
        sem = asyncio.Semaphore(concurrency)
        await platform_pages(client, con, sem, crawls, platform_crawls)
        path = os.path.join(RAW, "tranco_latest.csv")
        if not os.path.exists(path):
            print("[cc-marker] no tranco list", flush=True)
            return
        domains = []
        for rank, dom in load_list(path):
            if rank > rank_limit or dom.endswith(".sa") or dom in NON_STORE_ROOTS:
                continue
            domains.append(dom)
        print(f"[cc-marker] {len(domains)} domains against {crawls[0]['id']}", flush=True)
        await saudi_paths(client, con, sem, crawls[0], domains)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank-limit", type=int, default=8000)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--platform-crawls", type=int, default=4)
    a = ap.parse_args()
    asyncio.run(main(a.rank_limit, a.concurrency, a.platform_crawls))
