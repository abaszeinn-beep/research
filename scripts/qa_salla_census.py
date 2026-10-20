"""QA census of Salla stores rejected on product-type rules: re-reads the public storefront API and records is_require_shipping.

  python3 scripts/qa_salla_census.py keys.txt out.jsonl     # keys.txt: one salla.sa/<slug> key per line
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter

import httpx

HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0"}


async def one(client, sem, key):
    slug = key.split("/", 1)[1]
    async with sem:
        await asyncio.sleep(0.15)
        try:
            r = await client.get("https://api.salla.dev/store/v1/products?per_page=30", headers={**HEADERS, "Store-Identifier": slug}, timeout=30)
            if r.status_code != 200:
                return {"key": key, "http": r.status_code}
            data = r.json().get("data") or []
        except Exception as e:
            return {"key": key, "error": type(e).__name__}
    ship = sum(1 for p in data if p.get("is_require_shipping"))
    return {"key": key, "n": len(data), "ship": ship, "types": dict(Counter(p.get("type") or "product" for p in data)),
            "names": [(p.get("name") or "")[:50] for p in data[:6]], "prices": [p.get("price") for p in data[:3]],
            "cur": sorted({p.get("currency") for p in data if p.get("currency")}), "ex": next((p.get("url") for p in data if p.get("url")), None)}


async def main():
    keys = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(follow_redirects=True) as c:
        res = await asyncio.gather(*(one(c, sem, k) for k in keys))
    with open(sys.argv[2], "w") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

asyncio.run(main())
