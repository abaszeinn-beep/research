"""Read-only Wayback CDX lookup: newest 200/html captures under a URL prefix (polite, sequential)."""
import asyncio, sys, httpx

async def main():
    async with httpx.AsyncClient(headers={"User-Agent": "saudi-ecom-qa-review/1.0 (polite archive client)"}, timeout=90) as c:
        for prefix in sys.argv[1:]:
            for attempt in range(3):
                try:
                    r = await c.get("https://web.archive.org/cdx/search/cdx", params={
                        "url": prefix, "matchType": "prefix", "from": "20250101", "filter": ["statuscode:200", "mimetype:text/html"],
                        "collapse": "urlkey", "fl": "timestamp,original,length", "limit": __import__("os").environ.get("QA_LIMIT","-25")})
                    break
                except httpx.HTTPError as e:
                    await asyncio.sleep(6)
            else:
                print(prefix, "ERR"); continue
            if r.status_code != 200:
                print(f"## {prefix}: HTTP {r.status_code}"); continue
            rows = [l.split(" ") for l in r.text.splitlines() if len(l.split(" ")) >= 3]
            print(f"## {prefix}: status {r.status_code}, {len(rows)} rows")
            for row in rows[-int(__import__("os").environ.get("QA_ROWS","8")):]:
                print("  ", row[0], row[2] if len(row) > 2 else "", row[1][:130])
            await asyncio.sleep(3)

asyncio.run(main())
