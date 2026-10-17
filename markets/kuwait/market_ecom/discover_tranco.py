"""Tranco top-1M discovery.

1. Every market-ccTLD domain in the list becomes a candidate.
2. Global domains (by rank) get one homepage fetch; hreflang alternates and same-site links pointing at a
   market storefront (locale path or market subdomain) become candidates. Progress is checkpointed per
   chunk of ranks in the jobs table, so restarts skip finished chunks.

  python3 -m market_ecom.discover_tranco --top 200000 --concurrency 96
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from . import market as MK
from .common import DEFAULT_HEADERS, NON_STORE_ROOTS, MARKETPLACE_ROOTS, identity, registrable_domain, clean_host

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "tranco.csv")
TRANCO_ID = "64VVX"
HREFLANG = re.compile(r"<link[^>]+hreflang=[\"']([a-zA-Z_-]+)[\"'][^>]*>", re.I)
HREF_ATTR = re.compile(r"href=[\"']([^\"'#\s>]{1,400})[\"']", re.I)
NON_COMMERCE_TLD = re.compile(r"\.(?:gov|edu|mil|int)(?:\.[a-z]{2})?$|\.ac\.[a-z]{2}$")
SKIP_LABEL = re.compile(r"(?:cdn|api|static|img|analytics|tracking|ads?|pixel|metrics|telemetry|dns|cloud|edge|akamai|azure|aws)", re.I)


def ranks(top):
    out = []
    with open(RAW) as fh:
        for line in fh:
            r, d = line.strip().split(",", 1)
            r = int(r)
            if r > top and not MK.on_market_tld(d):
                continue
            out.append((r, d.strip().lower()))
    return out


def market_links(html, base_url, root):
    found = set()
    head = html[:600_000]
    for m in HREFLANG.finditer(head):
        tag = m.group(0)
        lang = m.group(1).lower().replace("_", "-")
        if lang.endswith("-" + MK.ISO2) or lang == MK.ISO2:
            h = re.search(r"href=[\"']([^\"']+)", tag)
            if h:
                found.add(urljoin(base_url, h.group(1)))
    for m in HREF_ATTR.finditer(head):
        u = urljoin(base_url, m.group(1))
        host = (urlsplit(u).hostname or "").lower()
        if not host or registrable_domain(clean_host(host)) != root:
            continue
        if MK.MKT_GEO.search(u):
            found.add(u)
    return found


async def probe(client, sem, rank, domain):
    async with sem:
        try:
            res = await asyncio.wait_for(_probe(client, rank, domain), 30)
            if res[2] is None and not domain.startswith("www."):
                res = await asyncio.wait_for(_probe(client, rank, domain, "www."), 25)
            return res
        except Exception:
            return rank, domain, None, []


async def _probe(client, rank, domain, sub=""):
    if True:
        try:
            async with client.stream("GET", f"https://{sub}{domain}/") as r:
                chunks, size = [], 0
                async for ch in r.aiter_bytes():
                    chunks.append(ch)
                    size += len(ch)
                    if size > 600_000:
                        break
                body = b"".join(chunks).decode(r.encoding or "utf-8", "replace")
                final = str(r.url)
                status = r.status_code
        except Exception:
            return rank, domain, None, []
    root = registrable_domain(domain)
    links = market_links(body, final, root) if status < 400 else set()
    if MK.MKT_GEO.search(final):
        links.add(final)
    return rank, domain, status, sorted(links)


async def main(top, concurrency, chunk, start=1):
    con = db.connect()
    db.register_source(con, f"tranco:{TRANCO_ID}", "ranking", f"Tranco top-1M list {TRANCO_ID}: all .{'/.'.join(MK.TLDS)} domains + homepage probe of top {top} global domains for {MK.NAME} locale links/hreflang")
    rows = ranks(top)
    cc = [(r, d) for r, d in rows if MK.on_market_tld(d)]
    n = db.add_candidates(con, [(f"https://{d}/", 8 if r <= 200_000 else 6) for r, d in cc], f"tranco:{MK.ISO2}tld", f"list {TRANCO_ID}")
    print(f"[tranco] {len(cc)} market-ccTLD domains -> {n} new candidates", flush=True)
    glob = [(r, d) for r, d in rows if not MK.on_market_tld(d) and start <= r <= top]
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=0)
    hdrs = dict(DEFAULT_HEADERS)
    async with httpx.AsyncClient(headers=hdrs, follow_redirects=True, limits=limits, verify=False,
                                 timeout=httpx.Timeout(12.0, connect=6.0)) as client:
        sem = asyncio.Semaphore(concurrency)
        total_new = 0
        for i in range(0, len(glob), chunk):
            part = glob[i:i + chunk]
            job = f"{TRANCO_ID}|{part[0][0]}-{part[-1][0]}"
            if db.job_done(con, "tranco_probe", job):
                continue
            todo = []
            for r, d in part:
                root = registrable_domain(d)
                if root in NON_STORE_ROOTS or NON_COMMERCE_TLD.search(d) or SKIP_LABEL.search(d.split(".")[0]):
                    continue
                todo.append((r, d))
            t0 = time.time()
            res = await asyncio.gather(*(probe(client, sem, r, d) for r, d in todo), return_exceptions=True)
            hits, ok = [], 0
            for x in res:
                if isinstance(x, Exception):
                    continue
                r, d, st, links = x
                if st is not None:
                    ok += 1
                for u in links[:3]:
                    ident = identity(u)
                    if ident and ident["root_domain"] not in MARKETPLACE_ROOTS:
                        hits.append((u, 9 if r <= 50_000 else 7))
            new = db.add_candidates(con, hits, f"tranco:{MK.ISO2}_locale_probe", f"list {TRANCO_ID} ranks {part[0][0]}-{part[-1][0]}")
            total_new += new
            db.mark_job(con, "tranco_probe", job, "done", len(todo), new, f"ok={ok} hits={len(hits)}")
            db.heartbeat(con, "discover_tranco", "code-worker(asyncio)", concurrency, {"chunk": job, "total_new": total_new})
            print(f"[tranco] {job} probed={len(todo)} ok={ok} hits={len(hits)} new={new} total_new={total_new} {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200_000)
    ap.add_argument("--concurrency", type=int, default=96)
    ap.add_argument("--chunk", type=int, default=2000)
    ap.add_argument("--start", type=int, default=1)
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    asyncio.run(main(a.top, a.concurrency, a.chunk, a.start))
