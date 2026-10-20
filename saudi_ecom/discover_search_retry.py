"""One short retry of Bing, DuckDuckGo, Mojeek and Brave.

Each engine gets a handful of brand/category/city queries. An engine that
returns a block, a captcha or an empty shell is stopped and recorded; its
queries are not retried in a loop. Working engines insert candidates through
db.add_candidates. Completed queries are stored under engine names
bing_retry / ddg_retry / mojeek / brave so they do not collide with the
Phase-1 cache.
"""
from __future__ import annotations

import asyncio

import httpx

from . import db
from .common import DEFAULT_HEADERS
from .discover_search import Bing, DDG

QUERIES = [
    "متجر إلكتروني سعودي عطور",
    "متجر ملابس اونلاين الرياض",
    "Saudi online store electronics Riyadh",
    "أفضل متجر عبايات سعودي",
    "Salla store Saudi perfumes",
    "متجر أثاث اونلاين جدة",
    "Saudi pharmacy online store",
    "متجر إلكترونيات السعودية توصيل",
]


class HtmlEngine:
    name = ""
    url = ""
    min_gap = 8.0

    def __init__(self, client):
        self.client = client
        self.blocked = False

    async def search(self, q):
        if self.blocked:
            return None
        try:
            r = await self.client.get(self.url, params={"q": q}, timeout=25)
        except httpx.HTTPError as e:
            print(f"[search:{self.name}] error {type(e).__name__}", flush=True)
            self.blocked = True
            return None
        low = r.text.lower()
        if r.status_code != 200 or "captcha" in low[:4000] or "challenge" in low[:2500] or "anomaly" in low:
            print(f"[search:{self.name}] blocked status={r.status_code}", flush=True)
            self.blocked = True
            return None
        return self.links(r.text)


class Mojeek(HtmlEngine):
    name = "mojeek"
    url = "https://www.mojeek.com/search"

    def links(self, text):
        import re
        from urllib.parse import urlsplit
        out = []
        for href in re.findall(r'href=["\'](https?://[^"\']+)', text):
            host = urlsplit(href).hostname or ""
            if "mojeek.com" in host:
                continue
            out.append(href)
        return out[:10]


class Brave(HtmlEngine):
    name = "brave"
    url = "https://search.brave.com/search"

    def links(self, text):
        import re
        from urllib.parse import urlsplit
        out = []
        for href in re.findall(r'href=["\'](https?://[^"\']+)', text):
            host = urlsplit(href).hostname or ""
            if "brave.com" in host or "brave.search" in host:
                continue
            out.append(href)
        return out[:10]


async def run(engine, con, queries):
    new = 0
    tried = 0
    for q in queries:
        row = con.execute("SELECT status FROM queries WHERE engine=? AND query=?", (engine.name, q)).fetchone()
        if row and row[0] == "done":
            continue
        res = await engine.search(q)
        tried += 1
        if res is None:
            db_status = "blocked"
            con.execute(
                "INSERT INTO queries VALUES (?,?,?,?,?,?,?) ON CONFLICT(engine,query) DO UPDATE SET status=excluded.status, ts=excluded.ts",
                (engine.name, q, db_status, 0, 0, db.now(), "coverage_retry"),
            )
            print(f"[search:{engine.name}] stopped after {tried} queries", flush=True)
            return new, "blocked"
        added = db.add_candidates(con, [(u, 4) for u in res], source=f"search_retry:{engine.name}", detail=q[:160])
        new += added
        con.execute(
            "INSERT INTO queries VALUES (?,?,?,?,?,?,?) ON CONFLICT(engine,query) DO UPDATE SET status=excluded.status, n_results=excluded.n_results, n_new=excluded.n_new, ts=excluded.ts",
            (engine.name, q, "done", len(res), added, db.now(), "coverage_retry"),
        )
        print(f"[search:{engine.name}] {q[:40]!r} results={len(res)} new={added}", flush=True)
        await asyncio.sleep(engine.min_gap if hasattr(engine, "min_gap") else 6)
    return new, "ok"


async def main():
    con = db.connect()
    headers = {**DEFAULT_HEADERS, "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.7"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=25) as client:
        engines = [Bing(client), DDG(client), Mojeek(client), Brave(client)]
        # tag the cached engine names so this retry is visible in the queries table
        Bing.name = "bing_retry"
        DDG.name = "ddg_retry"
        for eng in engines:
            try:
                new, status = await run(eng, con, QUERIES)
            except Exception as e:
                print(f"[search:{eng.name}] crash {type(e).__name__}: {e}", flush=True)
                status, new = "error", 0
            db.register_source(con, f"search_retry:{eng.name}", "search", f"Coverage-round retry of {eng.name}", status=status, notes=f"new={new}")
            print(f"[search:{eng.name}] {status} new={new}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
