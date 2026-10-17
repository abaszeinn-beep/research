"""Independent QA probe used by the Sonnet review (read-only: never writes to the DB).

Fetches public pages politely (robots.txt respected, no challenge bypass) and prints compact observations that a
reviewer can judge by eye. Deliberately does not import the pipeline's verification rules.

  python3 scripts/qa_probe.py live URL [URL...]
  python3 scripts/qa_probe.py wayback WAYBACK_URL [...]
  python3 scripts/qa_probe.py app APPSTORE_ID_OR_URL [...]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"}
SAR = re.compile(r'(?:SAR|SR|ر\.?\s?س|ريال|﷼)(?:\s|&nbsp;|<[^<>]{0,120}>){0,6}\d|\d[\d,.]*(?:\s|&nbsp;|<[^<>]{0,120}>){0,6}(?:SAR|SR\b|ر\.?\s?س|ريال|﷼)|"(?:priceCurrency|currency|currencyCode|currency_code)"\s*:\s*"SAR"', re.I)
CART = re.compile(r"add[\s_-]?to[\s_-]?(?:cart|bag|basket)|addToCart|أضف (?:إلى|الى|ل|لل)?\s?(?:السلة|الحقيبة|سلة)|اضف (?:إلى|الى|ل|لل)?\s?(?:السلة|سلة)|إضافة (?:إلى|الى)\s?(?:السلة|سلة)|اضافة (?:إلى|الى|لل)\s?(?:السلة|سلة)|اشتر[يِ]? الآن|buy now", re.I)
CLOSED = re.compile(r"المتجر مغلق|store is (?:currently )?closed|temporarily closed|maintenance|قريب[اً]|coming soon|opening soon|under construction|تحت (?:الصيانة|الإنشاء)", re.I)
VAT = re.compile(r"\b3\d{13}3\b")
PHONE = re.compile(r"\+?966[\s-]?\d|\b05\d{8}\b|\b920\d{6}\b")
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
PLAT = [("salla", r"cdn\.salla|salla\.network|twilight|salla-add-product"), ("zid", r"zid\.store|zidcdn|media\.zid"),
        ("shopify", r"cdn\.shopify\.com|myshopify"), ("woocommerce", r"woocommerce|wc-ajax"), ("magento", r"Magento_|text/x-magento-init"),
        ("sfcc", r"demandware"), ("odoo", r"website_sale|odoo"), ("next", r"/_next/static"), ("wix", r"wixstatic")]

_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


async def allowed(client, url):
    sp = urlsplit(url)
    base = f"{sp.scheme}://{sp.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = await client.get(base + "/robots.txt", timeout=15)
            if r.status_code == 200 and "<html" not in r.text[:300].lower():
                rp.parse(r.text.splitlines())
                _robots[base] = rp
            else:
                _robots[base] = None
        except httpx.HTTPError:
            _robots[base] = None
    rp = _robots[base]
    return True if rp is None else rp.can_fetch("*", url)


def strip(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def summarize(url, r, text):
    t = TITLE.search(text)
    title = re.sub(r"\s+", " ", t.group(1)).strip()[:90] if t else ""
    plats = [n for n, p in PLAT if re.search(p, text, re.I)]
    body = strip(text)
    links = re.findall(r'href="([^"]+)"', text)
    prod_links = [l for l in links if re.search(r"/p/|/products?/|/product-|/buy-|/item/|\.html$|/dp/|-p\d+|/pdp/", l, re.I)]
    return {
        "url": url, "final": str(r.url), "http": r.status_code, "title": title, "plat": plats[:3],
        "sar": len(SAR.findall(text)), "cart": len(CART.findall(text)), "prodlinks": len(prod_links),
        "closed": CLOSED.findall(body[:6000])[:2], "vat": bool(VAT.search(text)), "phone": bool(PHONE.search(text)),
        "len": len(text), "body": body[:260],
    }


async def live(client, url):
    try:
        if not await allowed(client, url):
            return {"url": url, "robots": "disallowed"}
        r = await client.get(url, timeout=30, follow_redirects=True)
        return summarize(url, r, r.text)
    except Exception as e:
        return {"url": url, "error": type(e).__name__ + ":" + str(e)[:80]}


async def wayback(client, url):
    m = re.match(r"https?://web\.archive\.org/web/(\d{14})(?:id_)?/(.*)", url)
    if not m:
        return {"url": url, "error": "not a wayback url"}
    ts, orig = m.groups()
    raw = f"https://web.archive.org/web/{ts}id_/{orig}"
    try:
        r = await client.get(raw, timeout=60, follow_redirects=True)
    except Exception as e:
        return {"url": url, "error": type(e).__name__}
    s = summarize(orig, r, r.text)
    s["ts"] = ts
    s["jsonld_product"] = bool(re.search(r'"@type"\s*:\s*"Product"', r.text))
    s["offer"] = bool(re.search(r'"@type"\s*:\s*"Offer"', r.text))
    s["og_type"] = (re.search(r'og:type"\s+content="([^"]+)', r.text) or [None, ""])[1]
    s["price_ctx"] = [re.sub(r"\s+", " ", strip(m.group(0)))[:60] for m in SAR.finditer(r.text)][:3]
    return s


async def app(client, ref):
    m = re.search(r"id(\d{5,})", ref)
    appid = m.group(1) if m else ref
    try:
        r = await client.get("https://itunes.apple.com/lookup", params={"id": appid, "country": "sa"}, timeout=30)
        j = r.json()["results"]
    except Exception as e:
        return {"app": appid, "error": type(e).__name__}
    if not j:
        return {"app": appid, "error": "not in SA store"}
    a = j[0]
    return {"app": appid, "name": a.get("trackName"), "seller": a.get("sellerName"), "sellerUrl": a.get("sellerUrl"),
            "genre": a.get("primaryGenreName"), "updated": (a.get("currentVersionReleaseDate") or "")[:10],
            "cur": a.get("currency"), "langs": (a.get("languageCodesISO2A") or [])[:5], "countries_hint": a.get("supportedDevices") and "devices"}


async def main():
    mode, items = sys.argv[1], sys.argv[2:]
    sem = asyncio.Semaphore(int(__import__("os").environ.get("QA_CONC","8")))
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        fn = {"live": live, "wayback": wayback, "app": app}[mode]

        async def one(i):
            async with sem:
                return await fn(client, i)
        for res in await asyncio.gather(*[one(i) for i in items]):
            print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
