"""Mall tenant directories: tenant names -> data/mall_tenants.tsv (reference universe) and tenant-page outbound
website links -> candidates (source mall:<mall>). Resumable per tenant page (jobs kind='mall_page')."""
from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from .common import DEFAULT_HEADERS, NON_STORE_ROOTS, registrable_domain, clean_host
from .market import HERE

MALLS = [
    # (mall name, listing pages, tenant-link regex)
    ("Villaggio Mall", ["https://villaggioqatar.com/en/shops", "https://villaggioqatar.com/en/shop", "https://villaggioqatar.com/en"], r"/en/shop/[a-z0-9\-]+"),
    ("Place Vendome", ["https://placevendomeqatar.com/shop", "https://placevendomeqatar.com/"], r"/shop/[a-z0-9\-]+"),
    ("City Center Doha", ["https://citycenterdoha.com/shops/"], r"citycenterdoha\.com/(?:shops?|stores?)/[a-z0-9\-]+/?"),
    ("Lagoona Mall", ["https://lagoonamall.com/shopping-dining/", "https://lagoonamall.com/about-us/retailers-e-services/"], r"lagoonamall\.com/(?:mall_management|stores?|shop)/[a-z0-9\-]+/?"),
    ("Tawar Mall", ["https://www.tawarmall.qa/shop-category/shoping/"], r"tawarmall\.qa/(?:shop|stores?|shops)/[a-z0-9\-]+/?"),
    ("The Pearl Qatar", ["https://thepearlqatar.com/en/Shop-and-Dine", "https://thepearlqatar.com/en/Inside-the-Island/Shopping"], r"/en/(?:Shop-and-Dine|Inside-the-Island/Shopping)/[A-Za-z0-9\-]+"),
    ("Landmark Mall", ["https://landmarkdoha.com/stores.html"], r"stores?/[a-z0-9\-]+\.html"),
    ("Mall of Qatar", ["https://mallofqatar.com.qa/en/shopping-list", "https://mallofqatar.com.qa/en/shop"], r"/en/(?:shop|store|brand)s?/[A-Za-z0-9\-]+"),
    ("Doha Festival City", ["https://www.dohafestivalcity.com/en/shop", "https://www.dohafestivalcity.com/en/stores"], r"/en/(?:shop|store)s?/[a-z0-9\-]+"),
    ("Hyatt Plaza", ["https://hyattplaza.com/stores", "https://hyattplaza.com/"], r"/stores?/[a-z0-9\-]+"),
    ("Gulf Mall", ["https://gulfmallqatar.com/stores", "https://www.gulfmall.qa/stores"], r"/stores?/[a-z0-9\-]+"),
]
SOCIAL = re.compile(r"facebook|instagram|twitter|x\.com|tiktok|snapchat|youtube|linkedin|whatsapp|wa\.me|google\.|apple\.com|play\.google|pinterest", re.I)
DINING = re.compile(r"cafe|caffe|coffee|restaurant|burger|grill|pizza|kitchen|bakery|sushi|shawarma|juice|dining|food|cinema|novo|entertain|gym|salon|spa|clinic|bank|exchange", re.I)
TSV = os.path.join(HERE, "data", "mall_tenants.tsv")


async def fetch(client, sem, url):
    async with sem:
        for i in range(3):
            try:
                r = await client.get(url, timeout=30)
                if r.status_code == 200:
                    return str(r.url), r.text
                if r.status_code in (403, 404, 410):
                    return None, None
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2 * (i + 1))
    return None, None


def slug_name(path):
    s = path.rstrip("/").split("/")[-1]
    s = re.sub(r"\.html?$", "", s)
    return re.sub(r"[-_]+", " ", s).strip().title(), s.lower()


async def main():
    con = db.connect()
    sem = asyncio.Semaphore(4)
    tenants = {}
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, verify=False) as client:
        for mall, pages, rx in MALLS:
            src = f"mall:{mall}"
            db.register_source(con, src, "mall_directory", f"{mall} tenant directory ({pages[0]}); tenant pages' outbound website links")
            links = set()
            for p in pages:
                final, html = await fetch(client, sem, p)
                if not html:
                    continue
                for m in re.finditer(r"""href=["']([^"'#\s]+)["']""", html):
                    u = urljoin(final, m.group(1))
                    if re.search(rx, u, re.I) and urlsplit(u).netloc == urlsplit(final).netloc:
                        links.add(u.split("?")[0])
            links = sorted(links)
            print(f"[malls] {mall}: {len(links)} tenant pages", flush=True)
            found_out = 0

            async def one(u):
                nonlocal found_out
                name, slug = slug_name(urlsplit(u).path)
                if DINING.search(slug):
                    return
                tenants.setdefault(slug, (name, src))
                final, html = await fetch(client, sem, u)
                outs = []
                if html:
                    t = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
                    if t:
                        nm = re.sub(r"<[^>]+>|\s+", " ", t.group(1)).strip()
                        if 1 < len(nm) < 60:
                            tenants[slug] = (nm, src)
                    src_root = registrable_domain(clean_host(urlsplit(final).hostname or ""))
                    for h in re.findall(r"""href=["'](https?://[^"'#\s>]+)""", html):
                        host = clean_host(urlsplit(h).hostname or "")
                        r2 = registrable_domain(host)
                        if not host or r2 == src_root or SOCIAL.search(host) or r2 in NON_STORE_ROOTS:
                            continue
                        outs.append(h)
                n = db.add_candidates(con, [(o, 8) for o in outs], src, f"tenant page {u}") if outs else 0
                found_out += len(set(outs))
                db.mark_job(con, "mall_page", u, "done", len(outs), n)

            await asyncio.gather(*(one(u) for u in links))
            print(f"[malls] {mall}: outbound links {found_out}", flush=True)
    with open(TSV, "w", encoding="utf-8") as fh:
        fh.write("# slug\tname\tmall category\tsource(s) ; domains guessed from tenant name unless the tenant page linked a site (then queued as candidates)\n")
        for slug, (name, src) in sorted(tenants.items()):
            fh.write(f"{slug}\t{name}\t\t{src} (fetched {db.now()[:10]})\n")
    print(f"[malls] tenants written: {len(tenants)}", flush=True)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    asyncio.run(main())
