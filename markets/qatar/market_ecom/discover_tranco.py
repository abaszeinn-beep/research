"""Tranco top-1M discovery (resumable).

  cctld   every market-ccTLD domain in the list + domains whose label names the market (e.g. "qatar", "doha")
  probe   fetch the homepage of the top-N global domains (robots.txt respected) and harvest market storefront
          URLs from hreflang alternates, country selectors and links: locale paths (/en-qa/, /qatar-en/),
          market subdomains (qa.brand.com) and sibling market domains (brand.qa / brand.com.qa); a homepage that
          itself carries market signals (local currency, +phone code) is queued as well
  subdomains  DNS-probe <label>.<domain> market subdomains for the top-N domains (wildcard DNS filtered)

Each probed domain is recorded in the jobs table (kind='tranco_probe'), so restarts skip it.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

from . import db
from . import signals as S
from .common import identity, registrable_domain, NON_STORE_ROOTS, MARKETPLACE_ROOTS
from .market import M, WORK_DIR
from .verify import Fetcher

TRANCO = os.path.join(WORK_DIR, "data", "raw", "tranco.csv")
TRANCO_ID = "64VVX"
HREF = re.compile(r"""(?:href|data-href|data-url|value)\s*=\s*["']([^"'<>\s]{4,300})["']""", re.I)
HREFLANG = re.compile(r"""<link[^>]+hreflang\s*=\s*["']([a-z]{2}(?:[-_][a-z]{2})?)["'][^>]*>""", re.I)
NAME_RX = re.compile(r"qatar|doha|lusail|^qa[-.]|-qa\.|^q8", re.I)


def ranks():
    out = []
    with open(TRANCO) as fh:
        for line in fh:
            r, d = line.strip().split(",", 1)
            out.append((int(r), d.lower()))
    return out


def cctld(con):
    rows = ranks()
    items = []
    for r, d in rows:
        if M.is_cctld_host(d) or (NAME_RX.search(d.split(".")[0]) and "qa" in M.code):
            items.append((f"https://{d}/", 8 if r <= 200_000 else 6))
    db.register_source(con, "tranco:cctld", "ranking", f"Tranco list {TRANCO_ID}: all .{M.tld} domains + domains whose label names the market")
    n = db.add_candidates(con, items, "tranco:cctld", f"tranco {TRANCO_ID}")
    print(f"[tranco] cctld/name domains={len(items)} new={n}", flush=True)


def market_urls(html: str, page_url: str):
    """Market storefront URLs referenced by a global homepage."""
    root = registrable_domain(urlsplit(page_url).hostname or "")
    label = root.split(".")[0]
    found = {}
    for m in HREFLANG.finditer(html[:400_000]):
        tag = m.group(0)
        hm = re.search(r"""href\s*=\s*["']([^"']+)["']""", tag)
        if hm and m.group(1).lower().replace("_", "-").endswith("-" + M.code):
            found[urljoin(page_url, hm.group(1))] = "hreflang"
    for h in HREF.findall(html[:1_500_000]):
        if h.startswith(("data:", "javascript:", "mailto:", "tel:")):
            continue
        u = urljoin(page_url, h)
        sp = urlsplit(u)
        host = (sp.hostname or "").lower()
        if not host:
            continue
        r2 = registrable_domain(host)
        path = sp.path or "/"
        same_brand = r2 == root or (r2.split(".")[0] == label and len(label) >= 3)
        if not same_brand:
            if M.is_cctld_host(host) and r2 not in NON_STORE_ROOTS and r2 not in MARKETPLACE_ROOTS:
                found.setdefault(f"https://{host}/", "outbound_cctld")
            continue
        if M.is_cctld_host(host):
            found.setdefault(f"https://{host}/", "sibling_cctld")
        elif host.split(".")[0] in M.subdomain_labels:
            found.setdefault(f"https://{host}/", "market_subdomain")
        elif M.locale_re.search(path if path.endswith("/") else path + "/"):
            found.setdefault(u, "locale_path")
    return found


async def probe(con, top, concurrency, start):
    rows = [(r, d) for r, d in ranks() if start <= r <= top and not M.is_cctld_host(d)]
    done = {j for (j,) in con.execute("SELECT job FROM jobs WHERE kind='tranco_probe'")}
    rows = [(r, d) for r, d in rows if d not in done and registrable_domain(d) not in NON_STORE_ROOTS]
    print(f"[tranco] probe {len(rows)} domains (ranks {start}-{top}), {len(done)} done before", flush=True)
    db.register_source(con, "tranco:probe", "ranking", f"Tranco {TRANCO_ID} top-{top} homepages probed for {M.country} hreflang/locale/subdomain links")
    f = Fetcher(concurrency, 1)
    stats = {"done": 0, "hits": 0, "new": 0, "fail": 0}
    pend = []
    t0 = time.time()
    q: asyncio.Queue = asyncio.Queue()
    for r in rows:
        q.put_nowait(r)

    def flush():
        if not pend:
            return
        for _ in range(10):
            try:
                con.execute("BEGIN IMMEDIATE")
                con.executemany("INSERT OR REPLACE INTO jobs VALUES ('tranco_probe',?,?,?,?,?,?)", pend)
                con.execute("COMMIT")
                break
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                time.sleep(1)
        pend.clear()

    async def one(rank, d):
        try:
            st, final, html, _, err = await asyncio.wait_for(f.get(f"https://{d}/", tries=1), 40)
        except asyncio.TimeoutError:
            st, final, html, err = None, "", "", "timeout"
        if st is None and err not in ("robots_disallowed", "dns_not_resolved"):
            try:
                st, final, html, _, err = await asyncio.wait_for(f.get(f"https://www.{d}/", tries=1), 40)
            except asyncio.TimeoutError:
                st, final, html, err = None, "", "", "timeout"
        n_new, hits = 0, {}
        if st == 200 and html:
            hits = market_urls(html, final)
            text = S.visible_text(html[:400_000])
            local = len(S.PRICE_LOCAL.findall(text)) + (2 if S.LOCAL_CURRENCY_CODE.search(html[:600_000]) else 0) + (2 if S.LOCAL_PHONE.search(html[:600_000]) else 0)
            if local >= 2:
                hits.setdefault(final, "homepage_market_signals")
            if hits:
                pr = 9 if rank <= 100_000 else 7
                n_new = db.add_candidates(con, [(u, pr) for u in hits], "tranco:probe", f"rank {rank} {d}: " + ",".join(sorted(set(hits.values()))))
                stats["hits"] += 1
                stats["new"] += n_new
        else:
            stats["fail"] += 1
        for b in [b for b in list(f.robots) if b.endswith("//" + d) or b.endswith("." + d)]:
            f.robots.pop(b, None)
            f.robots_lock.pop(b, None)
        pend.append((d, "done", len(hits), n_new, db.now(), f"st={st} err={err}"[:200]))
        stats["done"] += 1
        if len(pend) >= 200:
            flush()
        if stats["done"] % 1000 == 0:
            el = time.time() - t0
            print(f"[tranco] {stats} rate={stats['done'] / el:.1f}/s rank~{rank}", flush=True)
            db.heartbeat(con, "tranco_probe", "code-worker(asyncio)", concurrency, stats)

    async def worker():
        while not q.empty():
            r, d = q.get_nowait()
            try:
                await one(r, d)
            except Exception as e:
                stats["fail"] += 1
                pend.append((d, "done", 0, 0, db.now(), f"error {type(e).__name__}"))

    await asyncio.gather(*[worker() for _ in range(concurrency)])
    flush()
    print(f"[tranco] probe finished {stats}", flush=True)


async def subdomains(con, top, concurrency):
    rows = [(r, d) for r, d in ranks() if r <= top and not M.is_cctld_host(d) and registrable_domain(d) == d]
    done = {j for (j,) in con.execute("SELECT job FROM jobs WHERE kind='tranco_sub'")}
    rows = [x for x in rows if x[1] not in done and x[1] not in NON_STORE_ROOTS]
    labels = [M.code] + list(M.path_words)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(concurrency)
    stats = {"done": 0, "hits": 0, "new": 0}
    print(f"[tranco-sub] {len(rows)} domains, labels={labels}", flush=True)

    async def resolves(h):
        async with sem:
            try:
                await asyncio.wait_for(loop.getaddrinfo(h, 443, type=socket.SOCK_STREAM), 8)
                return True
            except Exception:
                return False

    pend = []

    async def one(r, d):
        found = []
        for lab in labels:
            if await resolves(f"{lab}.{d}"):
                found.append(f"{lab}.{d}")
        if found and not await resolves(f"zz{random.randint(10**6, 10**7)}x.{d}"):
            n = db.add_candidates(con, [(f"https://{h}/", 7) for h in found], "tranco:subdomain", f"rank {r} DNS {','.join(found)}")
            stats["hits"] += 1
            stats["new"] += n
        pend.append(("tranco_sub", d, "done", len(found), 0, db.now(), ""))
        stats["done"] += 1
        if len(pend) >= 500:
            con.executemany("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)", pend)
            pend.clear()
            print(f"[tranco-sub] {stats}", flush=True)

    db.register_source(con, "tranco:subdomain", "ranking", f"DNS probe of {'/'.join(labels)}.<domain> for Tranco top-{top} (wildcard DNS filtered)")
    chunk = 2000
    for i in range(0, len(rows), chunk):
        await asyncio.gather(*[one(r, d) for r, d in rows[i:i + chunk]])
    if pend:
        con.executemany("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)", pend)
    print(f"[tranco-sub] finished {stats}", flush=True)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cctld", "probe", "subdomains"])
    ap.add_argument("--top", type=int, default=200_000)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=120)
    a = ap.parse_args()
    con = db.connect()
    if a.cmd == "cctld":
        cctld(con)
    elif a.cmd == "probe":
        asyncio.run(probe(con, a.top, a.concurrency, a.start))
    else:
        asyncio.run(subdomains(con, a.top, a.concurrency))
