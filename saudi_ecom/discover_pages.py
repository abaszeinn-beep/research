"""Directory / showcase / listicle crawler: extract outbound store links from pages.

Modes:
  --sitemap URL [--include REGEX]   crawl pages listed in a sitemap (recursively) and harvest outbound links
  --pages URL...                    harvest outbound links from given pages
  --expand-queries FILE             run each query on Bing, then harvest outbound links from each result page
"""
from __future__ import annotations

import argparse
import asyncio
import re
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from .common import DEFAULT_HEADERS, identity, registrable_domain, clean_host
from .discover_search import Bing

HREF = re.compile(r'href=["\'](https?://[^"\'#\s>]+)', re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


async def fetch(client, sem, url):
    async with sem:
        for i in range(3):
            try:
                r = await client.get(url, timeout=30)
                if r.status_code == 200:
                    return r.text
                if r.status_code in (404, 403, 410):
                    return None
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2 * (i + 1))
    return None


def outbound(html, page_url):
    src_root = registrable_domain(clean_host(urlsplit(page_url).hostname or ""))
    out = set()
    for h in HREF.findall(html):
        host = clean_host(urlsplit(h).hostname or "")
        if not host or registrable_domain(host) == src_root:
            continue
        out.add(h)
    return out


async def harvest_pages(client, sem, con, pages, source, priority):
    total_new = 0

    async def one(p):
        nonlocal total_new
        if db.job_done(con, "page", p):
            return
        html = await fetch(client, sem, p)
        if not html:
            db.mark_job(con, "page", p, "failed")
            return
        links = outbound(html, p)
        new = db.add_candidates(con, [(u, priority) for u in links], source=source, detail=p)
        total_new += new
        db.mark_job(con, "page", p, "done", len(links), new)
        if new:
            print(f"[pages] {p} links={len(links)} new={new}", flush=True)

    await asyncio.gather(*[one(p) for p in pages])
    return total_new


async def sitemap_urls(client, sem, url, include, limit=3000, depth=0):
    xml = await fetch(client, sem, url)
    if not xml:
        return []
    locs = LOC.findall(xml)
    if "<sitemapindex" in xml[:2000] and depth < 3:
        out = []
        for child in locs:
            out += await sitemap_urls(client, sem, child, include, limit, depth + 1)
            if len(out) >= limit:
                break
        return out[:limit]
    return [l for l in locs if not include or re.search(include, l)][:limit]


async def main(a):
    con = db.connect()
    sem = asyncio.Semaphore(a.concurrency)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
        if a.sitemap:
            urls = await sitemap_urls(client, sem, a.sitemap, a.include)
            print(f"[pages] sitemap {a.sitemap}: {len(urls)} pages", flush=True)
            src = a.source or f"directory:{registrable_domain(clean_host(urlsplit(a.sitemap).hostname))}"
            db.register_source(con, src, "directory/showcase", f"outbound links from pages in {a.sitemap} ({a.include or 'all'})")
            n = await harvest_pages(client, sem, con, urls, src, a.priority)
            print(f"[pages] {src} new candidates: {n}", flush=True)
        if a.pages:
            src = a.source or "directory:manual_pages"
            db.register_source(con, src, "directory/showcase", "outbound links from manually chosen directory pages")
            n = await harvest_pages(client, sem, con, a.pages, src, a.priority)
            print(f"[pages] {src} new candidates: {n}", flush=True)
        if a.expand_queries:
            bing = Bing(client)
            db.register_source(con, "listicle:bing", "listicles/rankings", "Pages returned by Bing for 'best/top Saudi online stores' style queries; outbound links harvested")
            qs = [l.strip() for l in open(a.expand_queries, encoding="utf-8") if l.strip()]
            for q in qs:
                if db.job_done(con, "listicle_query", q):
                    continue
                res = []
                for p in range(2):
                    r = await bing.search(q, p)
                    if not r:
                        break
                    res += r
                pages = [u for u in dict.fromkeys(res) if identity(u) is None or True]
                n = await harvest_pages(client, sem, con, pages[:20], "listicle:bing", a.priority)
                db.mark_job(con, "listicle_query", q, "done", len(pages), n)
                print(f"[pages] listicle q={q!r} pages={len(pages)} new={n}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitemap")
    ap.add_argument("--include", default="")
    ap.add_argument("--pages", nargs="*")
    ap.add_argument("--expand-queries")
    ap.add_argument("--source", default="")
    ap.add_argument("--priority", type=int, default=7)
    ap.add_argument("--concurrency", type=int, default=4)
    asyncio.run(main(ap.parse_args()))
