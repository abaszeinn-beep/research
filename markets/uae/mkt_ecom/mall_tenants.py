"""Build data/mall_tenants.tsv from public mall store directories (sitemaps of tenant pages).

Tenant names become reference rows (kind=mall) via `reference load-malls`; their domains are guessed from the
name and resolved like every other reference. Dining / services tenants are skipped where the mall labels them.

  python3 -m mkt_ecom.mall_tenants
"""
from __future__ import annotations

import asyncio
import html as htmlmod
import os
import re

import httpx

from .common import DEFAULT_HEADERS

OUT = os.path.join(os.path.dirname(__file__), "data", "mall_tenants.tsv")
FOOD = re.compile(r"restaurant|cafe|caf[eé]|coffee shop|burger|pizza|grill|kitchen|bakery|sushi|shawarma|starbucks|costa|tim hortons|"
                  r"mcdonald|kfc|subway|dining|food|eatery|bistro|lounge|juice|ice cream|creamery|gelato|donut|chicken|steak|"
                  r"bank|exchange|atm|salon|spa\b|clinic|medical centre|dental|laundry|car wash|cinema|vox|kidzania|aquarium|"
                  r"payment machine|money|travel|tours|real estate|telecom kiosk|parking|prayer|toilet|customer service", re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


async def get(client, url):
    for i in range(3):
        try:
            r = await client.get(url, timeout=40)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 404):
                return None
        except httpx.HTTPError:
            pass
        await asyncio.sleep(3 * (i + 1))
    return None


def slug_name(slug):
    slug = re.sub(r"-\d+$", "", slug.strip("/"))
    return " ".join(w.capitalize() if len(w) > 2 else w.upper() for w in slug.split("-")), slug


async def dubai_mall(client, sem):
    xml = await get(client, "https://thedubaimall.com/sitemap.xml") or ""
    urls = sorted({u for u in LOC.findall(xml) if re.search(r"/en/shop/[^/]+$", u)})
    out = []

    async def one(u):
        async with sem:
            h = await get(client, u)
            await asyncio.sleep(0.5)
        name, slug = slug_name(u.rsplit("/", 1)[-1])
        tags = []
        if h:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
            if m:
                t = htmlmod.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(1))).strip()
                if 1 < len(t) < 60:
                    name = t
            tags = re.findall(r"store-tag/([a-z0-9-]+)", h)
        if any(re.search(r"dining|restaurant|cafe|food", t) for t in tags) or FOOD.search(name):
            return
        cat = next((t for t in tags if t in ("fashion", "beauty", "electronics", "jewellery", "watches", "kids", "home", "sports", "shoes", "fragrances", "luxury")), "")
        out.append((slug, name, cat, "mall:The Dubai Mall (thedubaimall.com sitemap /en/shop/, fetched 2026-10-17)"))
    await asyncio.gather(*(one(u) for u in urls))
    return out


async def simple(client, sitemap, pattern, label):
    xml = await get(client, sitemap) or ""
    out = []
    for u in sorted(set(LOC.findall(xml))):
        m = re.search(pattern, u)
        if not m:
            continue
        name, slug = slug_name(m.group(1))
        if FOOD.search(name) or not slug:
            continue
        out.append((slug, name, "", label))
    return out


async def main():
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
        res = await asyncio.gather(
            dubai_mall(client, sem),
            simple(client, "https://www.malloftheemirates.com/sitemap/sitemap.xml", r"/en/find-a-store/([^/?#]+)/?$",
                   "mall:Mall of the Emirates (malloftheemirates.com sitemap /en/find-a-store/, fetched 2026-10-17)"),
            simple(client, "https://www.wafi.com/brands-sitemap.xml", r"wafi\.com/shop/([^/?#]+)/?$",
                   "mall:Wafi Mall (wafi.com brands-sitemap, fetched 2026-10-17)"),
            simple(client, "https://www.dubaioutletmall.com/wp-sitemap-posts-shop-1.xml", r"/shop/([^/?#]+)/?$",
                   "mall:Dubai Outlet Mall (dubaioutletmall.com shop sitemap, fetched 2026-10-17)"),
        )
    rows = {}
    for part in res:
        print(len(part))
        for slug, name, cat, src in part:
            k = re.sub(r"[^a-z0-9]", "", slug)
            if k in rows:
                if src not in rows[k][3]:
                    rows[k] = (rows[k][0], rows[k][1], rows[k][2] or cat, rows[k][3] + " | " + src)
            else:
                rows[k] = (slug, name, cat, src)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("# slug\tname\tmall category\tsource(s) ; domains are NOT known: resolved from name guesses + App Store sellerUrl, then live verification\n")
        for slug, name, cat, src in sorted(rows.values()):
            fh.write(f"{slug}\t{name}\t{cat}\t{src}\n")
    print("tenants", len(rows), "->", OUT)


if __name__ == "__main__":
    asyncio.run(main())
