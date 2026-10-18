"""Reference universe of huge/large/medium/recognized retailers and brands, and the coverage audit.

  python3 -m mktecom.reference load     # data/reference_brands.tsv + data/raw/wd/*.json (Wikidata) + Tranco ranks
  python3 -m mktecom.reference link     # queue each reference storefront URL as a candidate (priority 10)
  python3 -m mktecom.reference audit    # print coverage summary (export writes the sheet)
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from collections import Counter

from . import db
from .common import identity, registrable_domain, MARKETPLACE_ROOTS
from .market import M

HERE = os.path.dirname(__file__)
BRANDS_TSV = os.path.join(HERE, "data", "reference_brands.tsv")
WD_GLOB = os.path.join(HERE, "..", "data", "raw", "wd", "*.json")
TRANCO = os.path.join(HERE, "..", "data", "raw", "top-1m.csv")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_stores (
  ref_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, tier TEXT, category TEXT, sources TEXT, url TEXT, key TEXT,
  root_domain TEXT, tranco_rank INTEGER, kind TEXT, note TEXT, UNIQUE(key)
);
"""

NON_US_NOTE = re.compile(r"Canada \(non-US\)|non-US", re.I)
DEFUNCT_NOTE = re.compile(r"defunct|closed 20\d\d", re.I)
SERVICE_NOTE = re.compile(r"\((?:service|food service|telehealth|delivery app)\)|Restaurant|Rental|Meal kit|Prepared meals|Convenience|Subscription box|Styling subscription|Print services", re.I)


def connect():
    con = db.connect()
    con.executescript(SCHEMA)
    return con


def tranco_ranks():
    out = {}
    if os.path.exists(TRANCO):
        with open(TRANCO) as fh:
            for r, d in csv.reader(fh):
                out.setdefault(d.strip().lower(), int(r))
    return out


def tier_from_rank(rank):
    if rank and rank <= 5_000:
        return "large"
    if rank and rank <= 100_000:
        return "medium"
    return "recognized"


def load(con):
    ranks = tranco_ranks()
    rows = []
    with open(BRANDS_TSV, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            name, dom, tier, cat, src = parts[:5]
            rows.append((name, dom, tier, cat, src, "brand"))
    seen_wd = 0
    for fn in sorted(glob.glob(WD_GLOB)):
        try:
            b = json.load(open(fn))["results"]["bindings"]
        except Exception:
            continue
        for x in b:
            web = x["website"]["value"]
            name = x.get("itemLabel", {}).get("value", "")
            if re.match(r"^Q\d+$", name):
                continue
            rows.append((name, web, None, "", f"Wikidata ({os.path.basename(fn)[:-5]}): {x['item']['value'].rsplit('/', 1)[-1]}", "wikidata"))
            seen_wd += 1
    n_new = 0
    for name, dom, tier, cat, src, kind in rows:
        ident = identity(dom if "://" in dom else "https://" + dom)
        if not ident:
            continue
        key = ident["key"]
        rank = ranks.get(ident["root_domain"]) or ranks.get(re.sub(r"^www\.", "", (dom.split("://")[-1]).split("/")[0]))
        if tier is None:
            tier = tier_from_rank(rank)
        url = dom if "://" in dom else "https://" + dom
        r = con.execute("SELECT ref_id, sources, tier, kind FROM reference_stores WHERE key=?", (key,)).fetchone()
        if r:
            srcs = r[1] if src in r[1] else r[1] + "; " + src
            better = r[2] if kind == "wikidata" else tier
            con.execute("UPDATE reference_stores SET sources=?, tier=?, kind=CASE WHEN kind='brand' THEN 'brand' ELSE ? END WHERE ref_id=?",
                        (srcs[:600], better, kind, r[0]))
            continue
        note = ""
        if NON_US_NOTE.search(src):
            note = "non_us"
        elif DEFUNCT_NOTE.search(src):
            note = "defunct"
        elif SERVICE_NOTE.search(src):
            note = "service_or_food"
        elif cat == "Marketplace" or ident["root_domain"] in MARKETPLACE_ROOTS:
            note = "marketplace"
        con.execute("INSERT OR IGNORE INTO reference_stores(name,tier,category,sources,url,key,root_domain,tranco_rank,kind,note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (name, tier, cat, src, url, key, ident["root_domain"], rank, kind, note))
        n_new += 1
    print(f"reference load: {len(rows)} rows ({seen_wd} Wikidata), {n_new} new refs; total "
          f"{con.execute('SELECT count(*) FROM reference_stores').fetchone()[0]}")


def link(con):
    refs = con.execute("SELECT name, url, tier, sources, kind FROM reference_stores").fetchall()
    n = 0
    for name, url, tier, src, kind in refs:
        pr = {"huge": 12, "large": 11, "medium": 10}.get(tier, 8)
        n += db.add_candidates(con, [(url, pr)], source="reference:" + ("curated" if kind == "brand" else "wikidata"), detail=f"{name} [{tier}]")
    print("linked refs, new candidates:", n)


def resolve_status(con, key):
    """Follow duplicate_of links. Returns (status, url, reason, evidence_url, verified_at)."""
    seen = set()
    k = key
    while k and k not in seen:
        seen.add(k)
        v = con.execute("SELECT status, final_url, reason, evidence_url, verified_at, duplicate_of FROM verifications WHERE key=?", (k,)).fetchone()
        if not v:
            c = con.execute("SELECT status FROM candidates WHERE key=?", (k,)).fetchone()
            return (c[0] if c else "not_queued"), None, "", None, None
        if v[5]:
            k = v[5]
            continue
        return v[0], v[1], v[2] or "", v[3], v[4]
    return "unknown", None, "", None, None


def audit(con):
    out = []
    finals = {}
    for k, fk, st in con.execute("SELECT key, final_key, status FROM verifications WHERE status IN ('verified','verified_secondary_evidence') AND duplicate_of IS NULL"):
        if fk:
            finals.setdefault(fk, k)
    for ref_id, name, tier, cat, src, url, key, root, rank, kind, note in con.execute(
            "SELECT ref_id,name,tier,category,sources,url,key,root_domain,tranco_rank,kind,note FROM reference_stores"):
        st, furl, reason, ev, ts = resolve_status(con, key)
        if st not in ("verified", "verified_secondary_evidence") and key in finals:
            st, furl, reason, ev, ts = resolve_status(con, finals[key])
        if st not in ("verified", "verified_secondary_evidence"):
            # another candidate on the same root domain (e.g. brand.com|usa) may be the verified US storefront
            alt = con.execute("""SELECT v.key FROM verifications v JOIN candidates c USING(key) WHERE c.root_domain=? AND v.status IN ('verified','verified_secondary_evidence')
                                 AND v.duplicate_of IS NULL LIMIT 1""", (root,)).fetchone()
            if alt and root not in ("myshopify.com",):
                st, furl, reason, ev, ts = resolve_status(con, alt[0])
        if st == "verified":
            status = "in_directory (primary)"
        elif st == "verified_secondary_evidence":
            status = "in_directory (secondary evidence)"
        elif key.split("|")[0] in NOT_A_STORE and st not in ("verified", "verified_secondary_evidence"):
            status = "excluded: " + NOT_A_STORE[key.split("|")[0]]
        elif key.split("|")[0] in NO_ONLINE_STORE:
            status = "excluded: no online ordering (confirmed: " + NO_ONLINE_STORE[key.split("|")[0]] + ")"
        elif note == "marketplace" or reason.startswith(("excluded_marketplace", "redirects_to_marketplace")):
            status = "excluded: marketplace/aggregator"
        elif note == "non_us":
            status = "excluded: non-US storefront"
        elif note == "defunct" and st in ("rejected", "unverified"):
            status = "excluded: defunct/closed"
        elif note == "service_or_food" and st in ("rejected", "unverified"):
            status = "excluded: service/food-service/subscription (not a physical-goods store)"
        elif st == "rejected":
            if reason.startswith(("not_market", "redirects_to_non_market")):
                status = "excluded: non-US storefront"
            elif reason.startswith(("dns_not_resolved", "parked", "http_404", "http_410", "store_closed")):
                status = "excluded: defunct/closed"
            elif reason.startswith(("saas", "likely_services", "services", "restaurant", "likely_restaurant", "mostly_services", "no_shippable", "likely_digital", "digital")):
                status = "excluded: not a physical-goods store"
            elif reason.startswith(("no_ecommerce", "insufficient_ecommerce")):
                status = "excluded: no online ordering found"
            else:
                status = "excluded: " + reason.split(" ")[0][:40]
        elif st in ("pending", "in_progress", "not_queued"):
            status = "unresolved: not yet checked"
        else:
            status = "unresolved: " + (reason.split(" ")[0][:50] or st)
        out.append({"ref_id": ref_id, "name": name, "tier": tier, "category": cat, "sources": src, "kind": kind,
                    "tranco_rank": rank, "status": status, "url": furl or url, "reason": reason[:200],
                    "evidence": f"{ev or ''} @ {ts or ''}".strip(" @"), "domains": root})
    return out


NOT_A_STORE = {
    "gm.com": "manufacturer corporate site; no consumer web store found (live check: no cart/products; no shop subdomain located)",
    "toyota.com": "vehicle-manufacturer corporate site; no consumer web store (live check: no purchase path)",
    "honeywell.com": "industrial manufacturer corporate site; store.honeywell.com does not resolve; no online store found",
    "delta.com": "airline lounge/travel service, not a physical-goods store", "aa.com": "airline lounge/travel service, not a physical-goods store",
    "united.com": "airline lounge/travel service, not a physical-goods store", "ihg.com": "hotel/vacation-club service, not a physical-goods store",
    "hilton.com": "hotel brand, not a physical-goods store", "hyatt.com": "hotel brand, not a physical-goods store",
    "worldbank.org": "publications/organisation site, not a physical-goods store", "audible.com": "digital audiobooks (not physical goods)",
    "fedex.com": "shipping/print services (not a physical-goods retailer)",
}
NO_ONLINE_STORE = {
    "rossstores.com": "Ross Dress for Less sells in stores only; rossstores.com is a corporate/store-locator site (live check: no cart, no products)",
    "traderjoes.com": "Trader Joe's states it does not sell groceries online; traderjoes.com has no cart or checkout (live check: no purchase path)",
}


def main():
    con = connect()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "audit"
    if cmd == "load":
        load(con)
    elif cmd == "link":
        link(con)
    elif cmd == "audit":
        rows = audit(con)
        c = Counter((r["tier"], r["status"].split(":")[0].split(" (")[0]) for r in rows if r["kind"] == "brand")
        for k in sorted(c):
            print(k, c[k])
        un = [r["name"] for r in rows if r["kind"] == "brand" and r["tier"] in ("huge", "large") and r["status"].startswith("unresolved")]
        print("unresolved huge/large:", len(un), un[:80])


if __name__ == "__main__":
    main()
