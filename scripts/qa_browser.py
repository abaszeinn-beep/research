"""Read-only headless-Chromium probe for JS-rendered storefronts (robots respected, no challenge solving).

  python3 scripts/qa_browser.py URL [URL...]
"""
import asyncio, json, re, sys
from playwright.async_api import async_playwright
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from qa_probe import SAR, CART, VAT, PHONE, allowed, strip
import httpx


async def main():
    urls = sys.argv[1:]
    async with httpx.AsyncClient(verify=False, headers={"User-Agent": "Mozilla/5.0"}) as hc, async_playwright() as pw:
        br = await pw.chromium.launch()
        for url in urls:
            if not await allowed(hc, url):
                print(json.dumps({"url": url, "robots": "disallowed"})); continue
            ctx = await br.new_context(locale="ar-SA", timezone_id="Asia/Riyadh", viewport={"width": 1366, "height": 900})
            page = await ctx.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                html = await page.content()
                body = strip(html)
                links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                prod = [l for l in links if re.search(r"/p/|/products?/|/product-|/buy-|/item/|/pdp/|/shop/|-p\d+|\.html$|/dp/", l, re.I)]
                print(json.dumps({"url": url, "final": page.url, "http": resp.status if resp else None, "title": (await page.title())[:80],
                                  "sar": len(SAR.findall(html)), "cart": len(CART.findall(html)), "prod_links": len(prod), "sample": prod[:2],
                                  "vat": bool(VAT.search(html)), "body": body[:200]}, ensure_ascii=False))
            except Exception as e:
                print(json.dumps({"url": url, "error": type(e).__name__ + str(e)[:80]}))
            finally:
                await ctx.close()
        await br.close()
asyncio.run(main())
