"""Official App Store shopping apps in the market storefront: their seller websites become candidates.

iTunes Search API (country=<market>), generated category terms in English and Arabic. Only apps in
shopping-type genres are used; the seller URL is a lead, verified like any other candidate.
Resumable per term (jobs table); ~20 requests/minute.
"""
from __future__ import annotations

import argparse
import time
from urllib.parse import urlsplit

import httpx

from . import db
from .common import identity, registrable_domain, NON_STORE_ROOTS, MARKETPLACE_ROOTS
from .market import M
from .queries import NICHES

GENRES = {"Shopping", "Food & Drink", "Lifestyle", "Health & Fitness", "Medical", "Sports", "Books"}
EXTRA = ["online shopping", "shop", "store", "mall", "fashion", "perfume", "oud", "abaya", "electronics", "grocery",
         "supermarket", "pharmacy", "furniture", "home", "beauty", "makeup", "jewellery", "gold", "watches", "toys",
         "baby", "kids", "shoes", "sports", "flowers", "gifts", "coffee", "dates", "chocolate", "pets", "books",
         "optical", "eyewear", "car parts", "tyres", "hypermarket", "cooperative", "coop", "outlet", "deals",
         "تسوق", "متجر", "عطور", "عبايات", "إلكترونيات", "هايبر ماركت", "صيدلية", "أثاث", "مجوهرات", "ألعاب",
         "ورد", "هدايا", "قهوة", "تمور", "حلويات", "ملابس", "أحذية", "مكياج", "نظارات", "تعاونية"]
EXTRA += [c for _, c in M.city_pairs] + [f"{c} shopping" for _, c in M.city_pairs]


def terms():
    out = list(EXTRA)
    for _, ar, en in NICHES:
        out += en[:6] + ar[:3]
    return list(dict.fromkeys(out))


def main(limit, pause):
    con = db.connect()
    src = f"appstore:{M.itunes_country}"
    db.register_source(con, src, "app_store", f"Apple App Store ({M.iso2} storefront) shopping-type apps; sellerUrl domains")
    total_new = 0
    with httpx.Client(timeout=30, headers={"User-Agent": "mkt-ecom-directory-research/1.0"}) as client:
        for i, t in enumerate(terms()[:limit]):
            if db.job_done(con, "appstore", t):
                continue
            r = None
            for attempt in range(4):
                try:
                    r = client.get("https://itunes.apple.com/search", params={"term": t, "country": M.itunes_country, "entity": "software", "limit": 50})
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(min(60, 8 * 2 ** attempt))
            if r is None or r.status_code != 200:
                db.mark_job(con, "appstore", t, "failed")
                continue
            items = []
            for app in r.json().get("results", []):
                if app.get("primaryGenreName") not in GENRES or not app.get("sellerUrl"):
                    continue
                host = (urlsplit(app["sellerUrl"]).hostname or "").lower()
                root = registrable_domain(host)
                if not root or root in NON_STORE_ROOTS or root in MARKETPLACE_ROOTS:
                    continue
                if identity(app["sellerUrl"]):
                    items.append((app["sellerUrl"], 7))
            new = db.add_candidates(con, items, src, f"term={t}")
            total_new += new
            db.mark_job(con, "appstore", t, "done", len(items), new)
            print(f"[appstore] {i} {t!r} urls={len(items)} new={new} total_new={total_new}", flush=True)
            time.sleep(pause)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--pause", type=float, default=3.2)
    a = ap.parse_args()
    main(a.limit, a.pause)
