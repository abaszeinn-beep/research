"""Deep live check for named reference storefronts whose homepage is JS/thin: follow robots-allowed internal links
(category -> product) with a normal browser User-Agent, no challenge solving. A 403/challenge response is final (-> secondary evidence).

  python3 -m mkt_ecom.deep_check name=https://url [name=https://url ...]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from .market import M
from .secondary import CART, SAR, UA_BROWSER

PRODUCT_LD = re.compile(r'"@type"\s*:\s*"Product"', re.I)
CUR_LD = re.compile(r'"priceCurrency"\s*:\s*"%s"' % M.currency, re.I)
CHALLENGE = re.compile(r"captcha|are you a human|access denied|px-captcha|cf-chl|just a moment|attention required", re.I)
PRODUCTISH = re.compile(r"/p/|/product|/products/|-p-?\d{4,}|/pd/|/dp/|\d{5,}\.html|-[a-z0-9]{5,8}\.html$|/buy-|/item/|/prd/|\.html$", re.I)
CATEGORYISH = re.compile(r"/c/|/category|/collections?/|/shop|/women|/men|/new|/jewel|/gold|/diamond|/electronics|/mobile|/phones|/grocery|/offers", re.I)


async def robots_ok(client, base):
    rp = robotparser.RobotFileParser()
    try:
        r = await client.get(base + "/robots.txt", timeout=20)
        if r.status_code != 200:
            return None, []
        rp.parse(r.text.splitlines())
        sm = re.findall(r"(?im)^sitemap:\s*(\S+)", r.text)
        return rp, sm
    except httpx.HTTPError:
        return None, []


async def get(client, url, rp):
    if rp is not None and not rp.can_fetch(UA_BROWSER["User-Agent"], url):
        return None, "robots_disallowed"
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
    except httpx.HTTPError as e:
        return None, type(e).__name__
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    if len(r.text) < 20000 and CHALLENGE.search(r.text):
        return None, "challenge_page"
    return r, "ok"


async def deep(name, url):
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    out = {"name": name, "url": url, "pages": [], "ok": False}
    async with httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True) as c:
        rp, sitemaps = await robots_ok(c, base)
        out["sitemaps"] = sitemaps[:3]
        r, why = await get(c, url, rp)
        out["home"] = why
        if not r:
            return out
        home = r.text
        out["home_final"] = str(r.url)
        links = []
        for h in re.findall(r'href="([^"#]+)"', home) + re.findall(r'href=\\"([^"\\#]+)\\"', home):
            u = urljoin(str(r.url), h)
            if urlsplit(u).netloc == urlsplit(str(r.url)).netloc and u not in links:
                links.append(u)
        scope = parts.path.rstrip("/")
        cats = [u for u in links if CATEGORYISH.search(urlsplit(u).path)][:4]
        prods = [u for u in links if PRODUCTISH.search(urlsplit(u).path) and u not in cats][:4]
        seen = set()
        queue = prods + cats
        evidence = {"aed_price_page": None, "cart": None, "product_ld": None, "ld_currency": None}
        i = 0
        while queue and i < 14:
            u = queue.pop(0)
            if u in seen:
                continue
            seen.add(u)
            i += 1
            pr, why = await get(c, u, rp)
            if not pr:
                out["pages"].append({"url": u, "result": why})
                continue
            t = pr.text
            n_price = len(SAR.findall(t))
            info = {"url": str(pr.url), "result": "ok", "aed": n_price, "cart": bool(CART.search(t)),
                    "product_ld": bool(PRODUCT_LD.search(t)), "ld_aed": bool(CUR_LD.search(t))}
            out["pages"].append(info)
            if n_price and not evidence["aed_price_page"]:
                evidence["aed_price_page"] = str(pr.url)
            if info["cart"] and not evidence["cart"]:
                evidence["cart"] = str(pr.url)
            if info["product_ld"] and info["ld_aed"]:
                evidence["product_ld"] = str(pr.url)
            if len(queue) < 6:
                for h in re.findall(r'href="([^"#]+)"', t):
                    nu = urljoin(str(pr.url), h)
                    if urlsplit(nu).netloc == urlsplit(str(r.url)).netloc and PRODUCTISH.search(urlsplit(nu).path) and nu not in seen:
                        queue.append(nu)
            await asyncio.sleep(1)
        out["evidence"] = evidence
        out["ok"] = bool(evidence["aed_price_page"] and (evidence["cart"] or evidence["product_ld"]))
    return out


async def main(items):
    res = await asyncio.gather(*(deep(n, u) for n, u in items))
    for r in res:
        print(json.dumps(r, ensure_ascii=False)[:1500], flush=True)
    return res


if __name__ == "__main__":
    asyncio.run(main([a.split("=", 1) for a in sys.argv[1:]]))
