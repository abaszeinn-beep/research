"""Second secondary-evidence pass for unresolved brand references: the Wayback leg uses permissive product-path CDX filters
(see wb_probe) instead of the stricter product-URL heuristics; the other legs (Common Crawl, sitemap, App Store) are unchanged.

  python3 -m mkt_ecom.secondary2 [--limit N] [--concurrency N]
"""
import argparse
import asyncio

from . import secondary as S
from .reference import connect
from .wb_probe import probe

RX = r".*(/p/|/pd/|/product|/buy|/dp/|\.html|-[0-9]{5,}|/item/|/shop/).*"


async def wb2(client, prefix):
    r = await probe(prefix, RX, 4, months=14)
    if r.get("error"):
        return {"type": "wayback_product", "ok": False, "detail": "wayback_offline"}
    o = r.get("ok")
    out = {"type": "wayback_product", "ok": bool(o), "captures": r["captures"], "product_captures": r["captures"]}
    if o:
        out.update({"url": o["url"], "date": o["date"], "detail": f"archived product page with {o['aed']} AED price strings and ordering control (Offer JSON-LD={o['ld_aed']})"})
    else:
        out["detail"] = "no archived product page with AED price and ordering control"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    S.wayback_product = wb2
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS secondary_evidence(key TEXT PRIMARY KEY, prefix TEXT, verdict TEXT, evidence TEXT, ts TEXT)")
    con.execute("""DELETE FROM secondary_evidence WHERE verdict!='verified_secondary_evidence' AND key IN
                   (SELECT c.key FROM candidates c, reference_stores r WHERE r.kind='brand' AND r.status='unresolved' AND r.tier IN ('medium','gcc_seed')
                    AND (c.root_domain IN (SELECT value FROM json_each('["' || replace(r.domains,' ','","') || '"]')) OR c.key IN (SELECT value FROM json_each('["' || replace(r.domains,' ','","') || '"]'))))""")
    con.commit()
    asyncio.run(S.main([], a.limit, a.concurrency))
