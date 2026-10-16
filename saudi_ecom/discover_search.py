"""Search-engine discovery worker (Bing with SA market; DuckDuckGo html as slow secondary).

Completed queries are cached in the `queries` table so restarts skip them.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import html as htmlmod
import random
import re
import time
import urllib.parse

import httpx

from . import db
from .common import DEFAULT_HEADERS
from .queries import generate

BING_HREF = re.compile(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"', re.I)
BING_CITE = re.compile(r"<cite[^>]*>(.*?)</cite>", re.I | re.S)
DDG_HREF = re.compile(r'uddg=([^&"]+)')


def bing_decode(href: str):
    href = htmlmod.unescape(href)
    m = re.search(r"[?&]u=a1([^&]+)", href)
    if m:
        s = m.group(1)
        s += "=" * (-len(s) % 4)
        try:
            return base64.urlsafe_b64decode(s).decode("utf-8", "replace")
        except Exception:
            return None
    if href.startswith("http") and "bing.com" not in href:
        return href
    return None


class Engine:
    name = ""
    min_gap = 4.0

    def __init__(self, client):
        self.client = client
        self.last = 0.0
        self.blocked_until = 0.0
        self.consecutive_blocks = 0

    async def wait(self):
        now = time.monotonic()
        if now < self.blocked_until:
            await asyncio.sleep(self.blocked_until - now)
        gap = time.monotonic() - self.last
        if gap < self.min_gap:
            await asyncio.sleep(self.min_gap - gap + random.random() * 2)
        self.last = time.monotonic()

    def block(self):
        self.consecutive_blocks += 1
        backoff = min(60 * 2 ** (self.consecutive_blocks - 1), 1800)
        self.blocked_until = time.monotonic() + backoff
        print(f"[search:{self.name}] blocked, backing off {backoff}s", flush=True)


class Bing(Engine):
    name = "bing"
    min_gap = 3.0

    async def search(self, q, page=0):
        await self.wait()
        params = {"q": q, "cc": "SA", "setlang": "ar", "first": str(page * 10 + 1)}
        try:
            r = await self.client.get("https://www.bing.com/search", params=params, timeout=30)
        except httpx.HTTPError:
            return None
        if r.status_code != 200 or "captcha" in r.text[:20000].lower() and "b_algo" not in r.text:
            self.block()
            return None
        self.consecutive_blocks = 0
        urls = [bing_decode(h) for h in BING_HREF.findall(r.text)]
        return [u for u in urls if u]


class DDG(Engine):
    name = "ddg"
    min_gap = 25.0

    async def search(self, q, page=0):
        if page:
            return []
        await self.wait()
        try:
            r = await self.client.get("https://lite.duckduckgo.com/lite/", params={"q": q, "kl": "xa-ar"}, timeout=30)
        except httpx.HTTPError:
            return None
        low = r.text.lower()
        if r.status_code != 200 or "anomaly" in low or "bots use duckduckgo" in low or "challenge" in low[:5000]:
            self.block()
            return None
        self.consecutive_blocks = 0
        return [urllib.parse.unquote(u) for u in DDG_HREF.findall(r.text)]


async def run_engine(engine, con, queries, pages_for_site, stats, limit):
    done = {r[0] for r in con.execute("SELECT query FROM queries WHERE engine=? AND status='done'", (engine.name,))}
    todo = [(ws, q) for ws, q in queries if q not in done]
    print(f"[search:{engine.name}] {len(todo)} queries pending ({len(done)} cached)", flush=True)
    for i, (ws, q) in enumerate(todo[:limit] if limit else todo):
        npages = pages_for_site if q.startswith("site:") or "inurl:" in q else 2
        total, new = 0, 0
        ok = True
        for p in range(npages):
            res = await engine.search(q, p)
            if res is None:
                ok = False
                break
            total += len(res)
            n = db.add_candidates(con, [(u, 6) for u in res], source=f"search:{engine.name}", detail=q)
            new += n
            if len(res) < 5:
                break
            if p >= 1 and n == 0:
                break
        con.execute("INSERT OR REPLACE INTO queries VALUES (?,?,?,?,?,?,?)",
                    (engine.name, q, "done" if ok else "failed", total, new, db.now(), ws))
        stats[engine.name + "_queries"] = stats.get(engine.name + "_queries", 0) + 1
        stats[engine.name + "_new"] = stats.get(engine.name + "_new", 0) + new
        if i % 10 == 0:
            print(f"[search:{engine.name}] {i}/{len(todo)} q={q!r} results={total} new={new} stats={stats}", flush=True)
            db.heartbeat(con, f"search:{engine.name}", "code-worker(asyncio)", 1, stats)


async def main(engines, pages_for_site, limit, extra_file):
    con = db.connect()
    db.register_source(con, "search:bing", "search_engine", "Bing web search, cc=SA setlang=ar, HTML results")
    db.register_source(con, "search:ddg", "search_engine", "DuckDuckGo HTML endpoint (rate-limited heavily; slow secondary)")
    queries = generate()
    if extra_file:
        with open(extra_file, encoding="utf-8") as fh:
            queries = [("extra", l.strip()) for l in fh if l.strip()] + queries
    stats = {}
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
        objs = {"bing": Bing(client), "ddg": DDG(client)}
        await asyncio.gather(*[run_engine(objs[e], con, queries if e == "bing" else queries[::-1], pages_for_site, stats, limit) for e in engines])
    print("[search] done", stats, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="bing,ddg")
    ap.add_argument("--pages-for-site", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--extra", default="")
    a = ap.parse_args()
    asyncio.run(main(a.engines.split(","), a.pages_for_site, a.limit, a.extra))
