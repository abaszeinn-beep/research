"""Wayback diagnostic/evidence probe for one storefront prefix (product-path CDX filters, last ~14 months).

  python3 -m mkt_ecom.wb_probe <prefix> [<url-regex>] [--max N]
Prints captures and, for fetched archived pages, AED price / cart / Offer JSON-LD flags. Archive replays only; no live access.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re

import httpx

from .market import M
from .secondary import CART, SAR, UA_RESEARCH

LD_CUR = re.compile(r'"priceCurrency"\s*:\s*"%s"' % M.currency, re.I)
NEXT_CUR = re.compile(r'%s' % M.currency)


async def cdx(c, prefix, regex, since, limit=300):
    params = {"url": prefix, "matchType": "prefix", "from": since, "filter": ["statuscode:200", "mimetype:text/html"],
              "collapse": "urlkey", "fl": "timestamp,original,length", "limit": str(limit)}
    if regex:
        params["filter"].append("original:" + regex)
    for _ in range(8):
        try:
            r = await c.get("https://web.archive.org/cdx/search/cdx", params=params, timeout=90)
            if r.status_code == 200 and "Temporarily Offline" not in r.text[:600]:
                return [l.split(" ") for l in r.text.splitlines() if l.count(" ") >= 2]
        except httpx.HTTPError:
            pass
        await asyncio.sleep(45)
    return None


async def probe(prefix, regex, maxn, months=14):
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)).strftime("%Y%m%d")
    out = {"prefix": prefix, "captures": 0, "pages": [], "ok": None}
    async with httpx.AsyncClient(headers=UA_RESEARCH, follow_redirects=True) as c:
        rows = await cdx(c, prefix, regex, since)
        if rows is None:
            out["error"] = "wayback_offline"
            return out
        rows = [r for r in rows if "Mozilla" not in r[1] and (not r[2].isdigit() or int(r[2]) > 3500)]
        out["captures"] = len(rows)
        rows.sort(key=lambda r: r[0], reverse=True)
        for ts, orig, ln in rows[: maxn * 3]:
            if len(out["pages"]) >= maxn:
                break
            try:
                s = await c.get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=60)
            except httpx.HTTPError:
                continue
            await asyncio.sleep(1.2)
            if s.status_code != 200:
                continue
            t = s.text[:3_000_000]
            info = {"url": f"https://web.archive.org/web/{ts}/{orig}", "date": ts[:8], "aed": len(SAR.findall(t)), "cart": bool(CART.search(t)),
                    "ld_aed": bool(LD_CUR.search(t)), "bytes": len(t)}
            out["pages"].append(info)
            if (info["aed"] or info["ld_aed"]) and info["cart"]:
                out["ok"] = info
                break
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("regex", nargs="?", default="")
    ap.add_argument("--max", type=int, default=6)
    a = ap.parse_args()
    print(json.dumps(asyncio.run(probe(a.prefix, a.regex, a.max)), indent=1))
