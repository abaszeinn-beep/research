"""Official App Store (iTunes Search API, market storefront) discovery: seller websites of shopping-type apps.

Each search term is recorded in the queries table (engine='itunes'), so restarts skip finished terms.
  python3 -m market_ecom.discover_appstore
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

import httpx

from . import db
from . import market as MK
from .common import MARKETPLACE_ROOTS, NON_STORE_ROOTS, identity, registrable_domain
from .queries import NICHES

GENRES = {"Shopping", "Food & Drink", "Lifestyle", "Health & Fitness", "Medical", "Books", "Sports"}
EXTRA_TERMS = ["Kuwait shopping", "Kuwait online store", "تسوق الكويت", "متجر الكويت", "Kuwait delivery shop", "Kuwait perfume",
               "Kuwait abaya", "Kuwait grocery", "Kuwait electronics", "Kuwait flowers", "Kuwait gifts", "Kuwait pharmacy",
               "Kuwait coop", "جمعية تعاونية", "Kuwait furniture", "Kuwait sweets", "Kuwait chocolate", "Kuwait dates",
               "Kuwait coffee", "Kuwait toys", "Kuwait baby", "Kuwait pets", "Kuwait fashion", "Kuwait shoes", "Kuwait bags",
               "Kuwait jewelry", "Kuwait watches", "Kuwait beauty", "Kuwait makeup", "Kuwait sports", "Kuwait auto parts",
               "Kuwait mobile", "Kuwait gaming", "Kuwait books", "Kuwait stationery", "Kuwait hardware", "Kuwait lighting",
               "Kuwait home decor", "Kuwait kitchen", "Kuwait bedding", "Kuwait honey", "Kuwait spices", "Kuwait meat",
               "Kuwait fish", "Kuwait vegetables", "Kuwait bakery", "Kuwait oud", "Kuwait incense", "Kuwait cosmetics",
               "Kuwait optical", "Kuwait contact lenses", "Kuwait supplements", "Kuwait medical supplies", "Kuwait wholesale"]


def terms():
    out = list(EXTRA_TERMS)
    for cat, ar, en in NICHES:
        out += [f"{t} Kuwait" for t in en[:6]] + [f"{t} الكويت" for t in ar[:4]]
    return list(dict.fromkeys(out))


def main():
    con = db.connect()
    db.register_source(con, "appstore:" + MK.ISO2, "app_store", f"Apple App Store ({MK.NAME} storefront, iTunes Search API): sellerUrl of shopping/lifestyle apps")
    done = {r[0] for r in con.execute("SELECT query FROM queries WHERE engine='itunes' AND status='done'")}
    todo = [t for t in terms() if t not in done]
    print(f"[appstore] {len(todo)} terms", flush=True)
    seen_apps = set()
    total_new = 0
    with httpx.Client(timeout=30) as client:
        for i, term in enumerate(todo):
            r = None
            for attempt in range(4):
                try:
                    r = client.get("https://itunes.apple.com/search", params={"term": term, "country": MK.ISO2, "entity": "software", "limit": 50})
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(20 * (attempt + 1))
            if r is None or r.status_code != 200:
                continue
            urls = []
            for app in r.json().get("results", []):
                if app.get("trackId") in seen_apps:
                    continue
                seen_apps.add(app.get("trackId"))
                if app.get("primaryGenreName") not in GENRES or not app.get("sellerUrl"):
                    continue
                host = (urlsplit(app["sellerUrl"]).hostname or "").lower()
                root = registrable_domain(host)
                if not root or root in NON_STORE_ROOTS or root in MARKETPLACE_ROOTS:
                    continue
                ident = identity(app["sellerUrl"])
                if ident:
                    urls.append((app["sellerUrl"], 7))
                    con.execute("CREATE TABLE IF NOT EXISTS appstore_apps(track_id INTEGER PRIMARY KEY, name TEXT, seller TEXT, seller_url TEXT, genre TEXT, updated TEXT, key TEXT, term TEXT)")
                    con.execute("INSERT OR REPLACE INTO appstore_apps VALUES(?,?,?,?,?,?,?,?)",
                                (app.get("trackId"), app.get("trackName"), app.get("sellerName"), app["sellerUrl"], app.get("primaryGenreName"),
                                 (app.get("currentVersionReleaseDate") or "")[:10], ident["key"], term))
            new = db.add_candidates(con, urls, "appstore:" + MK.ISO2, f"term={term}")
            total_new += new
            con.execute("INSERT OR REPLACE INTO queries VALUES (?,?,?,?,?,?,?)", ("itunes", term, "done", len(urls), new, db.now(), "appstore"))
            if i % 10 == 0:
                print(f"[appstore] {i}/{len(todo)} term={term!r} urls={len(urls)} new={new} total_new={total_new}", flush=True)
                db.heartbeat(con, "discover_appstore", "code-worker", 1, {"done": i, "total_new": total_new})
            time.sleep(3.2)
    print(f"[appstore] done total_new={total_new}", flush=True)


if __name__ == "__main__":
    main()
