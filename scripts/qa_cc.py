"""Read-only Common Crawl re-check: fetch the WARC record of a URL in a given crawl and test SAR/cart markers.
  python3 scripts/qa_cc.py CRAWL URL [CRAWL URL ...]"""
import asyncio, gzip, json, sys
import httpx
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from qa_probe import SAR, CART, TITLE, strip

async def one(c, crawl, url):
    for attempt in range(3):
        try:
            r = await c.get(f"https://index.commoncrawl.org/{crawl}-index", params={"url": url, "output": "json", "limit": "1"}, timeout=60)
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(5)
    else:
        return {"url": url, "error": "index_unavailable"}
    lines = [l for l in r.text.splitlines() if l.startswith("{")]
    if not lines:
        return {"url": url, "error": "not_in_index", "crawl": crawl}
    j = json.loads(lines[0])
    off, ln = int(j["offset"]), int(j["length"])
    w = await c.get("https://data.commoncrawl.org/" + j["filename"], headers={"Range": f"bytes={off}-{off+ln-1}"}, timeout=60)
    body = gzip.decompress(w.content).decode("utf-8", "replace")
    t = TITLE.search(body)
    return {"url": url, "crawl": crawl, "ts": j["timestamp"], "status": j.get("status"), "sar": len(SAR.findall(body)), "cart": len(CART.findall(body)),
            "offer": '"Offer"' in body, "title": (t.group(1).strip()[:70] if t else "")}

async def main():
    args = sys.argv[1:]
    async with httpx.AsyncClient(headers={"User-Agent": "saudi-ecom-qa-review/1.0"}) as c:
        for i in range(0, len(args), 2):
            print(json.dumps(await one(c, args[i], args[i+1]), ensure_ascii=False))
            await asyncio.sleep(1)
asyncio.run(main())
