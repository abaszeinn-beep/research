"""Independent live re-check of sampled stores for the Sonnet QA review (read-only, robots.txt respected).

Input: TSV lines `key<TAB>url`. Output: JSONL, one observation per store, with platform-endpoint facts (Salla
storefront API, Shopify meta/products.json, WooCommerce Store API), product names, currency, closed/demo markers.
It does not apply the pipeline's verification rules; a human (the reviewer) judges each observation.

  python3 scripts/qa_store_check.py in.tsv out.jsonl
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections import Counter
from urllib.parse import urljoin, urlsplit

import httpx

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from qa_probe import CART, CLOSED, PHONE, SAR, TITLE, VAT, allowed, strip  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HDR = {"User-Agent": UA, "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"}
PLAT = [("salla", r"cdn\.salla|salla\.network|twilight|salla-add-product|salla\.sa"), ("zid", r"zid\.store|zidcdn|media\.zid|zid-"),
        ("shopify", r"cdn\.shopify\.com|myshopify|Shopify\.theme"), ("woocommerce", r"woocommerce|wc-ajax"),
        ("magento", r"Magento_|text/x-magento-init"), ("wix", r"wixstatic|wixstores"), ("opencart", r"catalog/view/theme"),
        ("odoo", r"website_sale|odoo")]
gap: dict[str, float] = {}


async def throttle(host):
    last = gap.get(host, 0)
    wait = last + 0.35 - time.time()
    gap[host] = max(time.time(), last) + 0.35
    if wait > 0:
        await asyncio.sleep(wait)


async def get(client, url, **kw):
    await throttle(urlsplit(url).netloc)
    for attempt in range(2):
        try:
            r = await client.get(url, timeout=25, follow_redirects=True, **kw)
            if r.status_code == 429 and attempt == 0:
                await asyncio.sleep(float(r.headers.get("retry-after", "4")) if r.headers.get("retry-after", "4").isdigit() else 4)
                continue
            return r
        except Exception as e:
            err = type(e).__name__
    return err


async def check(client, key, url):
    out = {"key": key, "url": url}
    if not await allowed(client, url):
        out["robots"] = "disallowed"
        return out
    r = await get(client, url)
    if isinstance(r, str):
        out["error"] = r
        return out
    html = r.text
    out.update({"http": r.status_code, "final": str(r.url)})
    t = TITLE.search(html)
    out["title"] = re.sub(r"\s+", " ", t.group(1)).strip()[:80] if t else ""
    body = strip(html)
    out["plat"] = next((n for n, p in PLAT if re.search(p, html, re.I)), "")
    out["sar"] = len(SAR.findall(html))
    out["cart"] = len(CART.findall(html))
    out["closed"] = CLOSED.findall(body[:5000])[:2]
    out["phone"] = bool(PHONE.search(html))
    out["vat"] = bool(VAT.search(html))
    out["body"] = body[:160]
    base = f"{urlsplit(str(r.url)).scheme}://{urlsplit(str(r.url)).netloc}"
    names, extra = [], {}
    m = re.search(r'"store":\{"id":(\d+)', html)
    if m:
        a = await get(client, "https://api.salla.dev/store/v1/products?per_page=30",
                      headers={"Store-Identifier": m.group(1), "Accept": "application/json", "Referer": str(r.url)})
        if not isinstance(a, str) and a.status_code == 200:
            try:
                data = json.loads(a.text).get("data") or []
                extra["salla_types"] = dict(Counter((p.get("type") or "product") for p in data))
                extra["salla_n"] = len(data)
                names = [p.get("name") or "" for p in data][:8]
                extra["salla_cur"] = sorted(set(re.findall(r'"currency"\s*:\s*"([A-Z]{3})"', a.text)))
            except ValueError:
                pass
        elif not isinstance(a, str):
            extra["salla_http"] = a.status_code
    if out["plat"] == "shopify" or "myshopify" in html:
        mj = await get(client, urljoin(base, "/meta.json"))
        if not isinstance(mj, str) and mj.status_code == 200 and mj.text.strip().startswith("{"):
            j = json.loads(mj.text)
            extra["shop"] = {k: j.get(k) for k in ("country", "currency", "city")}
        pj = await get(client, urljoin(base, "/products.json?limit=30"))
        if not isinstance(pj, str) and pj.status_code == 200 and pj.text.strip().startswith("{"):
            try:
                prods = json.loads(pj.text).get("products") or []
                extra["shopify_n"] = len(prods)
                extra["shopify_ship"] = sum(1 for p in prods if any(v.get("requires_shipping") for v in p.get("variants", [])))
                names = [p.get("title") or "" for p in prods][:8]
            except ValueError:
                pass
    if out["plat"] == "woocommerce":
        wj = await get(client, urljoin(base, "/wp-json/wc/store/v1/products?per_page=20"))
        if not isinstance(wj, str) and wj.status_code == 200 and wj.text.strip().startswith("["):
            try:
                prods = json.loads(wj.text)
                extra["woo_n"] = len(prods)
                extra["woo_cur"] = sorted({(p.get("prices") or {}).get("currency_code") for p in prods if p.get("prices")} - {None})
                names = [re.sub(r"\s+", " ", p.get("name") or "").strip() for p in prods][:8]
            except ValueError:
                pass
    if not names:
        anchors = re.findall(r'<a[^>]+href="[^"]*(?:/p\d{4,}|/products?/|/product-|/item/|/pdp/)[^"]*"[^>]*>(.*?)</a>', html, re.I | re.S)
        names = [re.sub(r"\s+", " ", strip(a))[:60] for a in anchors if len(strip(a)) > 3][:8]
    out["names"] = names
    out.update(extra)
    return out


async def main():
    inp, outp = sys.argv[1], sys.argv[2]
    rows = [l.rstrip("\n").split("\t") for l in open(inp) if l.strip()]
    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(headers=HDR, verify=False) as client:
        async def one(k, u):
            async with sem:
                try:
                    return await asyncio.wait_for(check(client, k, u), timeout=120)
                except Exception as e:
                    return {"key": k, "url": u, "error": type(e).__name__}
        res = await asyncio.gather(*[one(k, u) for k, u in rows])
    with open(outp, "w") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
