"""Record the evidence collected for named major references (deep live check, Wayback product probes, App Store, sitemaps).

Rule (unchanged): primary = live storefront with product + AED + purchase control (deep_check).
secondary = >=2 independent evidence types incl. >=1 storefront-level (Wayback product page w/ AED + cart, robots-allowed sitemap
with UAE product URLs). Evidence dicts come from wb_batch*.jsonl, deep_check and App Store; nothing is hand-asserted.

  python3 -m mkt_ecom.majors_resolve
"""
from __future__ import annotations

import asyncio
import json
import re

import httpx

from . import db
from .common import identity
from .reference import connect
from .secondary import UA_BROWSER, UA_RESEARCH, app_store, cc_product, save
from .deep_check import deep

# name -> (ref_id, storefront URL, domains, wayback result names, extra sitemap proofs (url, regex), skip_app)
CONF = {
    "Adidas": (145, "https://www.adidas.ae/en/", ["adidas.ae"], ["Adidas"], [], False),
    "Babyshop": (14, "https://www.babyshopstores.com/ae/en/", ["babyshopstores.com"], ["Babyshop"], [], False),
    "Carrefour UAE": (1, "https://www.carrefouruae.com/mafuae/en/", ["carrefouruae.com"], ["Carrefour"], [], False),
    "Dubai Duty Free": (158, "https://www.dubaidutyfree.com/", ["dubaidutyfree.com"], ["Dubai Duty Free", "Dubai Duty Free2"],
                        [("https://www.dubaidutyfree.com/productSitemap.xml", r"dubaidutyfree\.com/[^/]+/product/\d+")], True),
    "H&M": (22, "https://ae.hm.com/", ["ae.hm.com", "hm.com"], ["H&M", "H&M2"], [], False),
    "Huda Beauty": (213, "https://hudabeauty.com/", ["hudabeauty.com"], ["Huda Beauty"], [], True),
    "Boots": (31, "https://ae.boots.com/en/", ["ae.boots.com", "boots.ae"], ["Boots"],
              [("https://ae.boots.com/product-sitemap-ae.xml", r"ae\.boots\.com/en/buy-")], False),
    "Joyalukkas": (174, "https://www.joyalukkas.com/ae/", ["joyalukkas.com"], ["Joyalukkas"], [], False),
    "Lulu Hypermarket": (2, "https://www.luluhypermarket.com/en-ae", ["luluhypermarket.com"], ["Lulu"], [], False),
    "Malabar Gold & Diamonds": (175, "https://www.malabargoldanddiamonds.com/ae/", ["malabargoldanddiamonds.com"], ["Malabar"], [], False),
    "Namshi": (8, "https://www.namshi.com/uae-en/", ["namshi.com"], ["Namshi"], [], False),
    "Sharaf DG": (3, "https://uae.sharafdg.com/", ["sharafdg.com", "uae.sharafdg.com"], ["Sharaf DG"], [], False),
    "Shoemart": (17, "https://www.shoemartstores.com/ae/en/", ["shoemartstores.com"], ["Shoemart"], [], False),
    "Styli": (20, "https://stylishop.com/ae/en/", ["stylishop.com"], ["Styli", "Styli2"],
              [("https://images.stylishop.com/mulin_sitemaps/sitemap-listing-ae-en-0.xml", r"stylishop\.com/ae/en/product-")], False),
    "du shop": (139, "https://shop.du.ae/en/personal", ["du.ae"], ["du"], [], True),
}


def load_wb():
    out = {}
    for f in ("data/wb_batch.jsonl", "data/wb_batch2.jsonl", "data/wb_batch3.jsonl"):
        try:
            for l in open(f):
                d = json.loads(l)
                if d.get("ok") or d["name"] not in out:
                    out[d["name"]] = d
        except FileNotFoundError:
            pass
    return out


async def sitemap_proof(client, url, rx):
    try:
        r = await client.get(url, timeout=40)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    locs = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", r.text)
    hits = [l for l in locs if re.search(rx, l)]
    if len(hits) < 5:
        return None
    return {"type": "sitemap", "ok": True, "url": url, "date": db.now()[:10].replace("-", ""),
            "detail": f"{len(hits)} UAE product URLs in public sitemap, e.g. {hits[0]}", "sample": hits[:3]}


CC_PREFIX = {"du shop": "shop.du.ae/en/", "H&M": "ae.hm.com/", "Boots": "ae.boots.com/en/", "Lulu Hypermarket": "luluhypermarket.com/en-ae/",
             "Joyalukkas": "joyalukkas.com/ae/", "Dubai Duty Free": "dubaidutyfree.com/", "Sharaf DG": "uae.sharafdg.com/"}


async def main():
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS secondary_evidence(key TEXT PRIMARY KEY, prefix TEXT, verdict TEXT, evidence TEXT, ts TEXT)")
    wb = load_wb()
    report = []
    async with httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True) as c:
        for name, (ref_id, url, domains, wbnames, sitemaps, skip_app) in CONF.items():
            evs = []
            for wn in wbnames:
                d = wb.get(wn)
                if d and d.get("ok"):
                    o = d["ok"]
                    evs.append({"type": "wayback_product", "ok": True, "url": o["url"], "date": o["date"],
                                "detail": f"archived UAE product page with {o['aed']} AED price strings, ordering control, Offer JSON-LD={o['ld_aed']}"})
                    break
            if not skip_app:
                a = await app_store(c, name, domains)
                if a.get("ok"):
                    evs.append(a)
            if name in CC_PREFIX:
                async with httpx.AsyncClient(headers=UA_RESEARCH, follow_redirects=True) as ac:
                    try:
                        cc = await cc_product(ac, CC_PREFIX[name])
                    except Exception:
                        cc = None
                if cc and cc.get("ok"):
                    evs.append(cc)
            for su, rx in sitemaps:
                s = await sitemap_proof(c, su, rx)
                if s:
                    evs.append(s)
            types = {e["type"] for e in evs}
            verdict = "verified_secondary_evidence" if len(types) >= 2 and types & {"wayback_product", "commoncrawl_product", "sitemap"} else "insufficient_secondary_evidence"
            ident = identity(url)
            key = ident["key"] if ident else None
            if key:
                db.add_candidates(con, [(url, 20)], "reference:majors_resolve", f"ref {ref_id}", 20)
                con.execute("INSERT OR IGNORE INTO reference_urls(ref_id,url,key,via,ts) VALUES(?,?,?,?,?)", (ref_id, url, key, "majors_resolve", db.now()))
                con.commit()
                item = {"key": key, "url": url, "name": name, "domains": domains}
                save(con, item, {"key": key, "prefix": url, "verdict": verdict, "evidence": evs}, name)
            report.append((name, key, verdict, sorted(types)))
            print(name, key, verdict, sorted(types), flush=True)
    return report


if __name__ == "__main__":
    asyncio.run(main())
