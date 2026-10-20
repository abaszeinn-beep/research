"""Common Crawl discovery straight from the public index files on data.commoncrawl.org.

Used when the CDX API (index.commoncrawl.org) is unreachable. Each crawl's `cluster.idx` is sorted by
SURT key, so a binary search with HTTP range requests finds the region for a SURT prefix (e.g. `kw,`
for every .kw host, `com,ordable,` for Ordable shops) without downloading the whole file. Only the
compressed cdx blocks covering that region are fetched; a block whose first and next-block keys belong
to the same host holds only that host and is skipped. Resumable per crawl and prefix (jobs kind 'ccidx').

  python3 -m market_ecom.discover_ccidx --crawls 6 --prefixes kw,com,ordable,
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import gzip
import json
import random
import re

import httpx

from . import db
from .common import identity
from .discover_cc import ECOM_PATH

BASE = "https://data.commoncrawl.org"
UA = {"User-Agent": "market-ecom-directory-research/1.0 (polite Common Crawl index reader)"}
PREFIX_PRIORITY = {"kw,": 3, "com,ordable,": 4, "com,zyda,": 1, "com,expandcart,": 1, "store,zid,": 0, "com,mnasati,": 2}


async def get(client, url, rng=None, tries=6):
    delay = 3
    for _ in range(tries):
        try:
            r = await client.get(url, headers={"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else None, timeout=120)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (403, 404, 416):
                return None
        except httpx.HTTPError:
            pass
        await asyncio.sleep(delay + random.random() * 2)
        delay = min(delay * 2, 60)
    return None


def surt_host(key):
    h = key.split(")", 1)[0].split(",")
    host = ".".join(reversed([p for p in h if p]))
    return host[4:] if host.startswith("www.") else host


async def crawls_list(client, n):
    r = await get(client, f"{BASE}/crawl-data/index.html")
    ids = sorted(set(re.findall(r"CC-MAIN-20\d\d-\d\d", r.text)), reverse=True) if r else []
    return ids[:n]


async def idx_size(client, url):
    r = await client.head(url, timeout=60)
    return int(r.headers.get("content-length", 0)) if r.status_code == 200 else 0


async def first_key_at(client, url, pos, size):
    r = await get(client, url, (pos, min(pos + 8191, size - 1)))
    if r is None:
        return None
    lines = r.text.split("\n")
    if pos > 0:
        lines = lines[1:]
    return lines[0].split(" ", 1)[0] if lines and lines[0] else None


async def region(client, url, prefix):
    """Return the cluster.idx lines for blocks that may contain keys starting with prefix."""
    size = await idx_size(client, url)
    if not size:
        return None
    lo, hi = 0, size
    while hi - lo > 262144:
        mid = (lo + hi) // 2
        k = await first_key_at(client, url, mid, size)
        if k is None:
            return None
        if k < prefix:
            lo = mid
        else:
            hi = mid
    out, pos, prev = [], lo, None
    while pos < size:
        r = await get(client, url, (pos, min(pos + 1_048_575, size - 1)))
        if r is None:
            return None
        cut = r.content.rfind(b"\n")
        if cut < 0:
            break
        lines = r.content[:cut].decode("utf-8", "replace").split("\n")
        if pos == lo and lo > 0:
            lines = lines[1:]
        done = False
        for ln in lines:
            key = ln.split(" ", 1)[0]
            if key < prefix:
                prev = ln
                continue
            if prev is not None and not out:
                out.append(prev)
            out.append(ln)
            if not key.startswith(prefix):
                done = True
                break
        if done:
            break
        pos += cut + 1
    return out


async def harvest_block(client, crawl, line, sem, base_pr):
    _, fname, off, length = line.split("\t")[:4]
    async with sem:
        r = await get(client, f"{BASE}/cc-index/collections/{crawl}/indexes/{fname}", (int(off), int(off) + int(length) - 1))
    if r is None:
        return None
    try:
        text = gzip.decompress(r.content).decode("utf-8", "replace")
    except Exception:
        return None
    hits, urls = collections.Counter(), {}
    for ln in text.splitlines():
        parts = ln.split(" ", 2)
        if len(parts) < 3:
            continue
        try:
            rec = json.loads(parts[2])
        except ValueError:
            continue
        if rec.get("status") not in ("200", "301", "302", None):
            continue
        ident = identity(rec.get("url", ""))
        if not ident:
            continue
        urls.setdefault(ident["key"], rec["url"])
        if ECOM_PATH.search(rec["url"]):
            hits[ident["key"]] += 1
    return urls, hits


async def run(crawls_n, prefixes, concurrency):
    con = db.connect()
    db.register_source(con, "commoncrawl:idx", "index", "Common Crawl cluster.idx + cdx blocks read directly from data.commoncrawl.org (CDX API unreachable from this VM)")
    async with httpx.AsyncClient(headers=UA, follow_redirects=True, http2=False) as client:
        crawls = await crawls_list(client, crawls_n)
        print(f"[ccidx] crawls={crawls}", flush=True)
        sem = asyncio.Semaphore(concurrency)
        total_new = 0
        for crawl in crawls:
            for prefix in prefixes:
                job = f"{crawl}|{prefix}"
                if db.job_done(con, "ccidx", job):
                    continue
                base_pr = PREFIX_PRIORITY.get(prefix, 1)
                lines = await region(client, f"{BASE}/cc-index/collections/{crawl}/indexes/cluster.idx", prefix)
                if lines is None:
                    db.mark_job(con, "ccidx", job, "failed")
                    print(f"[ccidx] {job} cluster.idx unavailable", flush=True)
                    continue
                keys = [ln.split(" ", 1)[0] for ln in lines]
                fetch, direct = [], set()
                for i, ln in enumerate(lines[:-1]):
                    h, nh = surt_host(keys[i]), surt_host(keys[i + 1])
                    if h == nh and keys[i].startswith(prefix):
                        direct.add(h)
                    else:
                        fetch.append(ln)
                items = {}
                for h in direct:
                    ident = identity(f"https://{h}/")
                    if ident:
                        items[ident["key"]] = (f"https://{h}/", base_pr + 2)
                res = await asyncio.gather(*(harvest_block(client, crawl, ln, sem, base_pr) for ln in fetch))
                suffix = ".".join(reversed(prefix.rstrip(",").split(",")))
                failed = 0
                for x in res:
                    if x is None:
                        failed += 1
                        continue
                    urls, hits = x
                    for k, u in urls.items():
                        host = u.split("/")[2].split(":")[0].lower()
                        if host != suffix and not host.endswith("." + suffix):
                            continue
                        pr = base_pr + (3 if hits[k] >= 3 else 2 if hits[k] else 0)
                        if k not in items or items[k][1] < pr:
                            items[k] = (u, pr)
                new = db.add_candidates(con, list(items.values()), source=f"commoncrawl:{prefix.rstrip(',')}", detail=crawl)
                total_new += new
                status = "done" if failed <= max(2, len(fetch) // 20) else "partial"
                db.mark_job(con, "ccidx", job, status, len(items), new, f"blocks={len(lines)} fetched={len(fetch)} failed={failed}")
                print(f"[ccidx] {job} blocks={len(lines)} fetched={len(fetch)} failed={failed} keys={len(items)} new={new} total_new={total_new}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawls", type=int, default=6)
    ap.add_argument("--prefixes", default="kw,|com,ordable,|com,zyda,|com,expandcart,|com,mnasati,")
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    asyncio.run(run(a.crawls, [p for p in a.prefixes.split("|") if p], a.concurrency))
