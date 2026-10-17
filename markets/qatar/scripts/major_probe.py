"""Targeted Wayback product-page probe for reference brands (product-path CDX filter, newest captures, QAR + purchase control).
Usage: python3 scripts/major_probe.py name|prefix|product_regex [...]  -> prints JSON lines. Polite client, no live-site bypass."""
import asyncio, json, re, sys, datetime as dt
import httpx

CUR = re.compile(r'(?:QAR|QR|ر\.ق|ريال)\s?[\d,.]+|[\d,.]+\s?(?:QAR|QR|ر\.ق|ريال)|"priceCurrency"\s*:\s*"QAR"', re.I)
CART = re.compile(r'add[\s_-]?to[\s_-]?(?:cart|bag|basket)|addToCart|أضف إلى|اضف الى|buy now|"@type"\s*:\s*"Offer"', re.I)
H = {"User-Agent": "qatar-ecom-directory-research/1.0 (polite archive client)"}

async def cdx(c, prefix, rx, frm):
    for _ in range(3):
        try:
            r = await c.get("https://web.archive.org/cdx/search/cdx", params={"url": prefix, "matchType": "prefix", "filter": ["statuscode:200", f"original:{rx}"],
                            "from": frm, "limit": "60", "fl": "timestamp,original", "collapse": "urlkey"}, timeout=120)
            if r.status_code == 200:
                return [l.split(" ", 1) for l in r.text.splitlines() if " " in l]
        except httpx.HTTPError:
            pass
        await asyncio.sleep(5)
    return None

async def probe(c, name, prefix, rx):
    frm = (dt.date.today() - dt.timedelta(days=400)).strftime("%Y%m%d")
    caps = await cdx(c, prefix, rx, frm)
    out = {"name": name, "prefix": prefix, "captures": None if caps is None else len(caps), "ok": False}
    if not caps:
        return out
    caps.sort(reverse=True)
    for ts, orig in caps[:8]:
        u = f"https://web.archive.org/web/{ts}id_/{orig}"
        try:
            r = await c.get(u, timeout=90, follow_redirects=True)
        except httpx.HTTPError:
            continue
        t = r.text if r.status_code == 200 else ""
        n = len(CUR.findall(t)); cart = bool(CART.search(t))
        if n >= 1 and cart:
            out.update(ok=True, url=f"https://web.archive.org/web/{ts}/{orig}", date=ts[:8], qar_strings=n)
            return out
        await asyncio.sleep(1)
    out["sample"] = caps[0]
    return out

async def main():
    async with httpx.AsyncClient(headers=H) as c:
        res = await asyncio.gather(*(probe(c, *a.split("|", 2)) for a in sys.argv[1:]))
    for r in res:
        print(json.dumps(r, ensure_ascii=False), flush=True)
asyncio.run(main())
