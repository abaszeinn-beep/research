"""Tranco top-1M discovery for the market.

  local    every ccTLD domain and every domain whose label names the market (uae, dubai, ...) -> candidates
  probe    homepage of each global domain in rank order (top N): hreflang alternates and links pointing at a
           market locale path (/en-ae/, /ae/en/ ...) or market subdomain (ae.brand.com) or brand ccTLD (brand.ae)
  dns      DNS lookups of market subdomains (ae.<d>, uae.<d>) for the top N, with a wildcard-DNS control label

All steps are resumable per chunk of ranks (jobs table).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import string
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from .common import DEFAULT_HEADERS, NON_STORE_ROOTS, MARKETPLACE_ROOTS, registrable_domain, clean_host
from .market import M, on_cctld

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
HREFLANG = re.compile(r"<link[^>]+hreflang=[\"']([a-z]{2}[-_][a-z]{2})[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"'#<>\s]{1,400})[\"']", re.I)
SKIP_ROOTS = NON_STORE_ROOTS | set(MARKETPLACE_ROOTS)


def ranks(limit=None):
    out = []
    with open(os.path.join(RAW, "tranco.csv")) as fh:
        for line in fh:
            r, d = line.strip().split(",", 1)
            out.append((int(r), d))
            if limit and len(out) >= limit:
                break
    return out


def local(con):
    lab = re.compile(M.domain_label_re, re.I)
    items = []
    for r, d in ranks():
        if on_cctld(d) or lab.search(d.split(".")[0]):
            items.append((f"https://{d}/", 6 if r <= 200_000 else 4))
    db.register_source(con, "tranco:local", "ranking", f"Tranco top-1M: all .{M.cctld} domains and domains naming the market")
    n = db.add_candidates(con, items, "tranco:local", "tranco ccTLD/market-named")
    print(f"[tranco] local domains={len(items)} new={n}", flush=True)


def market_links(html, page_url, root):
    found = set()
    for m in HREFLANG.finditer(html[:400_000]):
        tag = m.group(0)
        if m.group(1).lower().replace("_", "-").endswith("-" + M.cctld):
            h = re.search(r"href=[\"']([^\"']+)[\"']", tag, re.I)
            if h:
                found.add(urljoin(page_url, h.group(1)))
    for m in HREF.finditer(html[:600_000]):
        u = urljoin(page_url, m.group(1))
        sp = urlsplit(u)
        host = (sp.hostname or "").lower()
        if not host:
            continue
        hroot = registrable_domain(clean_host(host))
        same_brand = hroot == root or hroot.split(".")[0] == root.split(".")[0]
        if not same_brand:
            continue
        if on_cctld(hroot) and hroot != root:
            found.add(f"https://{host}/")
        elif host.split(".")[0] in M.sub_labels:
            found.add(f"https://{host}/")
        elif M.LOCALE_RE.search((sp.path or "/") + "/"):
            found.add(u)
    return found


async def probe(con, top, concurrency, chunk):
    db.register_source(con, "tranco:global_probe", "ranking", f"Tranco top-{top} homepages: hreflang/links to {M.iso2} storefronts")
    doms = [(r, d) for r, d in ranks(top) if not on_cctld(d) and d not in SKIP_ROOTS]
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency + 20, max_keepalive_connections=0)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, verify=False, limits=limits,
                                 timeout=httpx.Timeout(15.0, connect=12.0)) as client:
        async def one(d):
            async with sem:
                for url in (f"https://www.{d}/", f"https://{d}/"):
                    try:
                        async with client.stream("GET", url) as r:
                            if "html" not in r.headers.get("content-type", "html"):
                                return set()
                            buf = b""
                            async for ch in r.aiter_bytes():
                                buf += ch
                                if len(buf) > 500_000:
                                    break
                            html = buf.decode(r.encoding or "utf-8", "replace")
                            return market_links(html, str(r.url), d)
                    except Exception:
                        continue
                return set()

        for i in range(0, len(doms), chunk):
            job = f"probe|{doms[i][0]}"
            if db.job_done(con, "tranco", job):
                continue
            part = doms[i:i + chunk]
            res = await asyncio.gather(*(asyncio.wait_for(one(d), 40) for _, d in part), return_exceptions=True)
            items = []
            for (r, d), links in zip(part, res):
                if isinstance(links, set):
                    items += [(u, 9 if r <= 50_000 else 7) for u in links]
            new = db.add_candidates(con, items, "tranco:global_probe", f"ranks {part[0][0]}-{part[-1][0]}")
            db.mark_job(con, "tranco", job, "done", len(items), new)
            print(f"[tranco] probe ranks {part[0][0]}-{part[-1][0]} links={len(items)} new={new}", flush=True)
            db.heartbeat(con, "tranco_probe", "code-worker(asyncio)", concurrency, {"last_rank": part[-1][0]})


async def dns(con, top, concurrency, chunk):
    import aiodns
    db.register_source(con, "tranco:dns_subdomain", "dns", f"DNS lookups of {'/'.join(sorted(M.host_variants))} for Tranco top-{top}")
    resolver = aiodns.DNSResolver(nameservers=["1.1.1.1", "8.8.8.8"], timeout=4, tries=2)
    sem = asyncio.Semaphore(concurrency)
    labels = [h.split(".")[0] for h in M.host_variants]

    async def resolves(h):
        async with sem:
            try:
                await resolver.query_dns(h, "A")
                return True
            except Exception:
                return False

    doms = [(r, d) for r, d in ranks(top) if not on_cctld(d) and d not in SKIP_ROOTS]
    for i in range(0, len(doms), chunk):
        job = f"dns|{doms[i][0]}"
        if db.job_done(con, "tranco", job):
            continue
        part = doms[i:i + chunk]
        tasks = [(r, d, l) for r, d in part for l in labels]
        ok = await asyncio.gather(*(resolves(f"{l}.{d}") for _, d, l in tasks))
        hits = [(r, d, l) for (r, d, l), o in zip(tasks, ok) if o]
        ctrl_doms = sorted({d for _, d, _ in hits})
        rnd = "".join(random.choice(string.ascii_lowercase) for _ in range(10))
        wild = await asyncio.gather(*(resolves(f"{rnd}.{d}") for d in ctrl_doms))
        wildcard = {d for d, w in zip(ctrl_doms, wild) if w}
        items = [(f"https://{l}.{d}/", 4 if r <= 50_000 else 2) for r, d, l in hits if d not in wildcard]
        new = db.add_candidates(con, items, "tranco:dns_subdomain", f"ranks {part[0][0]}-{part[-1][0]}")
        db.mark_job(con, "tranco", job, "done", len(items), new, f"wildcard={len(wildcard)}")
        print(f"[tranco] dns ranks {part[0][0]}-{part[-1][0]} hits={len(hits)} wildcard={len(wildcard)} new={new}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["local", "probe", "dns"])
    ap.add_argument("--top", type=int, default=200_000)
    ap.add_argument("--concurrency", type=int, default=150)
    ap.add_argument("--chunk", type=int, default=1000)
    a = ap.parse_args()
    con = db.connect()
    if a.cmd == "local":
        local(con)
    elif a.cmd == "probe":
        asyncio.run(probe(con, a.top, a.concurrency, a.chunk))
    else:
        asyncio.run(dns(con, a.top, a.concurrency, a.chunk))
