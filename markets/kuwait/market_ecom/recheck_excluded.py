"""Deeper Kuwait-storefront discovery for brand references excluded as 'no Kuwait storefront found'.

For every domain of such a reference: robots.txt sitemaps (kw/kuwait locale URLs, hreflang), homepage hreflang and
country-selector links, Shopify /meta.json, plus the Kuwait App Store listing seller URL. New Kuwait URLs are added as
candidates (source reference:deep_recheck) for the normal verifier. No bot-wall bypass; robots.txt is only read.

  python3 -m market_ecom.recheck_excluded
"""
import asyncio
import json
import re
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from .common import DEFAULT_HEADERS, identity, registrable_domain
from . import market as MK

KW_URL = re.compile(r"(?:^|[/._-])(?:kw|kuwait|q8)(?:[/._?-]|$)|[_-]kw(?:[/._?]|$)|/(?:en|ar)[-_]kw(?:/|$)|/kw[-_](?:en|ar)(?:/|$)", re.I)
HREFLANG = re.compile(r"<link[^>]+hreflang=[\"']([a-zA-Z_-]+)[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"'#\s>]{1,300})[\"']", re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


async def get(c, url, **kw):
    try:
        return await c.get(url, **kw)
    except Exception:
        return None


async def one(c, sem, ref_id, name, domains):
    found = {}
    async with sem:
        for d in domains:
            for host in (f"www.{d}", d):
                base = f"https://{host}"
                r = await get(c, base + "/robots.txt")
                if r is None:
                    continue
                if r.status_code == 200 and "text" in r.headers.get("content-type", "text/plain"):
                    sms = re.findall(r"(?im)^sitemap:\s*(\S+)", r.text)[:4]
                    for sm in sms:
                        s = await get(c, sm)
                        if s is None or s.status_code != 200:
                            continue
                        locs = LOC.findall(s.text)
                        subs = [u for u in locs if u.endswith(".xml") or ".xml?" in u or u.endswith(".xml.gz")]
                        for u in locs:
                            if KW_URL.search(u) and not u.endswith(".xml"):
                                found.setdefault(u, "sitemap")
                        for u in [x for x in subs if KW_URL.search(x)][:2]:
                            s2 = await get(c, u)
                            if s2 is not None and s2.status_code == 200:
                                for x in LOC.findall(s2.text)[:2000]:
                                    if KW_URL.search(x) or "KWD" in x:
                                        found.setdefault(x, "sitemap_kw")
                                        break
                r = await get(c, base + "/")
                if r is not None and r.status_code == 200:
                    t = r.text[:700_000]
                    for m in HREFLANG.finditer(t):
                        lang = m.group(1).lower().replace("_", "-")
                        if lang.endswith("-kw") or lang == "kw":
                            h = re.search(r"href=[\"']([^\"']+)", m.group(0))
                            if h:
                                found.setdefault(urljoin(str(r.url), h.group(1)), "hreflang")
                    for m in HREF.finditer(t):
                        u = urljoin(str(r.url), m.group(1))
                        h = (urlsplit(u).hostname or "").lower()
                        if h and KW_URL.search(u) and registrable_domain(h) == registrable_domain(host) and len(found) < 12:
                            found.setdefault(u.split("?")[0], "home_link")
                    if re.search(r'"(?:country(?:Code)?|iso_?code)"\s*:\s*"KW"|data-country(?:-code)?=["\']KW', t):
                        found.setdefault(str(r.url), "country_selector_json")
                if found:
                    break
            if found:
                break
    return ref_id, name, found


async def appstore_sellers(c, names):
    out = {}
    for ref_id, name in names:
        q = re.sub(r"\s*\(.*?\)|\s+Kuwait", "", name).strip()
        r = await get(c, "https://itunes.apple.com/search", params={"term": q, "country": "kw", "entity": "software", "limit": 3})
        await asyncio.sleep(2.5)
        if r is None or r.status_code != 200:
            continue
        for a in r.json().get("results", []):
            su = a.get("sellerUrl") or ""
            key = re.sub(r"[^a-z0-9]", "", q.lower())
            if su and key and key in re.sub(r"[^a-z0-9]", "", (a["trackName"] + su).lower()):
                out[ref_id] = (su, a["trackName"], a.get("currentVersionReleaseDate", "")[:10], a["trackViewUrl"])
                break
    return out


async def main():
    con = db.connect()
    rows = con.execute("SELECT ref_id, name, domains FROM reference_stores WHERE kind='brand' AND status IN ('excluded','unresolved') "
                       "AND reason LIKE 'excluded: no%Kuwait storefront found%'").fetchall()
    print(f"[recheck] {len(rows)} refs", flush=True)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20, verify=False) as c:
        sem = asyncio.Semaphore(6)
        res = await asyncio.gather(*[one(c, sem, r, n, [d for d in dm.split() if not d.endswith(".org")]) for r, n, dm in rows])
        added = 0
        for ref_id, name, found in res:
            if found:
                urls = list(found)[:6]
                added += db.add_candidates(con, [(u, 6) for u in urls], "reference:deep_recheck", f"ref {ref_id} {name}: {sorted(set(found.values()))}", 6)
                print(f"[recheck] {name}: {len(found)} kw urls via {sorted(set(found.values()))} e.g. {urls[0]}", flush=True)
        con.commit()
        print(f"[recheck] added {added} candidates", flush=True)
        sellers = await appstore_sellers(c, [(r, n) for r, n, _ in rows])
        for ref_id, (su, tn, dt, tv) in sellers.items():
            ident = identity(su)
            if ident:
                n = db.add_candidates(con, [(su, 6)], "reference:appstore_seller", f"ref {ref_id}: {tn} {dt} {tv}", 6)
                print(f"[recheck] app store seller {su} ({tn}, {dt}) new={n}", flush=True)
        con.commit()


if __name__ == "__main__":
    asyncio.run(main())
