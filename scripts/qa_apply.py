"""Apply the Sonnet QA review corrections to the live DB and write data/qa/sonnet_review_corrections.csv.

Inputs (reviewer working copies produced by re-running the fixed verifier on copies of the live DB):
  /tmp/work1.sqlite  service-typed Salla rejects re-verified with the shipped-goods rule
  /tmp/work2.sqlite  restaurant-name / charity rejects re-verified with the supply-catalogue rules
  /tmp/work3.sqlite  non-Salla/Zid/Shopify/Woo verified stores and rate-limited rows re-verified
  data/qa/corrections_work.jsonl  earlier manual corrections (majors, marketplaces)

  python3 scripts/qa_apply.py [--dry-run]
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
import sys

DRY = "--dry-run" in sys.argv
LIVE = "data/saudi_ecom.sqlite"
NOW = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
live = sqlite3.connect(LIVE)
live.row_factory = sqlite3.Row
VCOLS = [r[1] for r in live.execute("PRAGMA table_info(verifications)")]

W1_NOT_APPLIED = {  # flips the re-run produced that are wrong on live inspection (course/trading/cooking/repair services)
    "salla.sa/mrsultan": "trading-course bundles (digital/service), not goods",
    "salla.sa/thbayh-aatyh": "cooking/slaughter service orders, not goods",
    "salla.sa/omalbara2020": "catalogue is courses",
    "salla.sa/doubleqtech": "device repair services",
    "salla.sa/childhoodbox22": "reading-programme subscriptions",
}
W2_FLIPS = {
    "asantekitchens.com": ("wrong_exclusion_restaurant_equipment", "Restaurant/cafe equipment supplier (name contains 'Restaurant'), sells physical equipment with SAR prices and cart"),
    "salla.sa/storealfisal": ("wrong_exclusion_restaurant_equipment", "Restaurant-supplies store (name says restaurants), sells kitchen equipment"),
    "kitland.com.sa": ("wrong_exclusion_restaurant_equipment", "'Land of restaurants' kitchen-equipment supplier (KitchenAid, roasters, ovens) shipped goods"),
    "moodyul.com": ("wrong_exclusion_service_typed_physical", "Salla catalogue of IMOU cameras/accessories registered as type=service; shipped physical goods"),
    "rifaclothing.com": ("wrong_exclusion_service_typed_physical", "Salla abayas/dresses registered as type=service; shipped physical goods"),
    "salla.sa/ahsaic": ("wrong_exclusion_charity_shipped_goods", "Association's shop sells shipped goods (Qur'an stands, devices, books) with a normal catalogue"),
    "salla.sa/alsadw_maga": ("wrong_exclusion_charity_shipped_goods", "Heritage association sells garments/bags via a regular shipped catalogue"),
    "salla.sa/bin-baz-sales": ("wrong_exclusion_charity_shipped_goods", "Foundation bookshop sells printed books (28 products), no donation items"),
    "ubi.com.sa": ("wrong_exclusion_charity_false_match", "Jewellery store rejected on charity word match"),
    "okema.com.sa": ("wrong_exclusion_charity_false_match", "Beauty-device store rejected on charity word match"),
    "salla.sa/ecm77": ("wrong_exclusion_charity_false_match", "Car-accessories store rejected on charity word match"),
    "salla.sa/mhsol": ("wrong_exclusion_food_service_false_match", "Online fresh meat/produce grocer (food-type items shipped), not a restaurant"),
    "salla.sa/hareed": ("wrong_exclusion_food_service_false_match", "Fresh livestock/meat seller with delivery; sells goods"),
}
W3_KEEP = {  # re-run demoted these but live inspection shows a genuine store
    "bloomingdales.sa", "guess.sa", "techstore.com.sa", "mhzm.sa", "masdaronline.com",
}
TRANSIENT = ("rate_limited", "fetch_failed", "http_5", "http_429")

MANUAL = {
    # key: (corrected_status, category, reason)
    "syarah.com": ("rejected", "wrong_inclusion_marketplace", "Syarah is a used/new-car listings marketplace (listings of many dealers/sellers), like Carswitch and Motory"),
    "kayak.sa": ("rejected", "wrong_inclusion_marketplace", "KAYAK is a travel meta-search aggregator; sells no goods itself"),
    "soum.sa": ("rejected", "wrong_inclusion_marketplace", "Soum is a second-hand classifieds marketplace"),
    "tradeling.com|sa": ("rejected", "wrong_inclusion_marketplace", "Tradeling is a multi-seller B2B marketplace"),
    "kaf.com.sa": ("rejected", "wrong_inclusion_marketplace", "Live site is a freelancer-services marketplace ('hire the best freelancers'), no goods"),
    "salla.sa/biralmedina": ("rejected", "wrong_flip_charity_donations", "Charity-association shop: items are donations (winter clothing gifts, feeding, orphan sponsorship); keep rejected"),
    "boucheron.com|sa": ("unverified", "insufficient_secondary_evidence", "Only one proof (Wayback product page 2026-06-17, 120 days); no second current independent proof (no Saudi app, sitemap blocked, live site Access Denied)"),
    "versace.com|sa": ("unverified", "insufficient_secondary_evidence", "Only one proof (Wayback product page 2026-04-20, 178 days); no app or sitemap proof; live site Access Denied"),
    "barns.com.sa": ("unverified", "insufficient_secondary_evidence", "Only the App Store proof; no storefront-level proof (no archived product page or sitemap); a coffee-shop ordering site, not a catalogue"),
    "aloyoga.com|sa": ("unverified", "insufficient_secondary_evidence", "Only one proof (Wayback en-sa gift-card page 2026-04-24); the app cited is 'ALO Wellness Club' (class membership, not shopping); live aloyoga.com serves the global site"),
}
NONSTORE = {
    # key: (corrected_status, category, reason)  live homepage inspected 2026-10-17
    "adid.com.sa": "digital health solutions company (no shop)",
    "arminsol.com.sa": "drilling services company (Wix page, no catalogue)",
    "fairvalue.com.sa": "valuation/consulting firm",
    "afaaqservices.sa": "catering services company",
    "elnqaa.com.sa": "home cleaning services company",
    "hrc.com.sa": "cold-room manufacturer, no prices or checkout",
    "eagletech.sa": "CCTV installation services",
    "exahost.com.sa": "web-hosting/IT company",
    "salama.com.sa": "insurance company",
    "franchising.sa": "franchise advice portal",
    "naeem.com.sa": "booking-management software",
    "ncf.sa": "packaging manufacturer corporate site",
    "rockwood.sa": "steel-fabrication machines corporate site",
    "halsharq.com.sa": "air-conditioning contractor",
    "aldukheil.com.sa": "corporate group site",
    "mawtenrec.sa": "domestic-worker recruitment office",
    "almahera.sa": "domestic-worker recruitment office",
    "tafarrod.sa": "domestic-worker recruitment office",
    "ussusalenjaz.sa": "domestic-worker recruitment office",
    "moneymoon.sa": "financing/investment service",
    "kamcoinvest.com.sa": "investment company",
    "firstonerent.com.sa": "car-rental company",
    "xy.com.sa": "marketing agency",
    "alqasem.com.sa": "real-estate company",
    "maten.sa": "investment company",
    "najmat-alatlal.sa": "road-transport (moving) service",
    "zelz.sa": "site suspended for unpaid hosting",
    "abeel.sa": "cultural-content company, no shop",
    "laft.com.sa": "agency portfolio site (works/reports)",
    "gda.sa": "design agency",
    "naqleen.com.sa": "transport/logistics company",
    "zorinstechnologies.sa": "IT solutions company",
    "lovin.co|sa": "media/lifestyle app site",
    "thehub.sa": "office-space rental",
    "experts.com.sa": "e-learning platform (courses)",
    "sufrah.sa": "restaurant-ordering SaaS vendor",
    "syooltik.sa": "SaaS vendor",
    "tkana.sa": "AI customer-service SaaS",
    "vandi.com.sa": "IT company",
    "riyadhrehab.com.sa": "rehabilitation medical centre",
    "fuji.com.sa": "industrial company corporate site",
    "sesystems.com.sa": "enterprise systems integrator",
    "mpc.com.sa": "contracting company corporate site",
    "alraja.com.sa": "company corporate site, no shop",
    "newera.com.sa": "software/technology company",
    "makamen.sa": "contracting company (construction sectors)",
    "alshallal.com.sa": "theme park: ticket sales are services, not goods",
    "kleap.io": "cafe site built on a no-code builder, not a goods catalogue",
    "brioche.sa": "cafe / restaurant",
    "jamilsrestaurant.sa": "restaurant",
    "shawarmer.com": "restaurant chain ordering site",
    "castlefarms.sa": "date farm site with an events calendar, no shop",
    "ayca.com.sa": "accounting firm (Wix cart markers are template noise)",
    "adab.sa": "cultural/research foundation (Wix)",
    "adt.sa": "marketing/souvenir services company (Wix)",
    "artmood.com.sa": "interior-design company; commerce platform label was a false match",
    "daftar.sa": "buy-now-pay-later ledger app for neighbourhood shops, not a store",
    "alharbi-int.com.sa": "construction contractor (mosques, wells, shelters) quoting projects, not shipped goods",
    "faasgreen.com.sa": "measurement-equipment distributor with no ordering flow",
    "asdaworkshop.com.sa": "quick-services company",
    "cg.sa": "corporate site; commerce label false match",
    "adwc.sa": "site returns HTTP 500 (cannot be shown to sell goods)",
    "midea.com|sa": "brand catalogue site, no purchase path",
}
UNVER = {"daftar.sa", "alharbi-int.com.sa", "faasgreen.com.sa", "midea.com|sa", "adwc.sa"}


def row(db, key):
    return db.execute("SELECT * FROM verifications WHERE key=?", (key,)).fetchone()


def main():
    corr = []

    def add(key, cur, new, cat, pas, reason, ev, name=""):
        corr.append({"key": key, "store_name": name, "current_status": cur, "corrected_status": new, "category": cat,
                     "grok_pass": pas, "reason": reason, "evidence_url": ev, "reviewed_at_utc": NOW})

    work = {1: sqlite3.connect("/tmp/work1.sqlite"), 2: sqlite3.connect("/tmp/work2.sqlite"), 3: sqlite3.connect("/tmp/work3.sqlite")}
    for w in work.values():
        w.row_factory = sqlite3.Row
    updates = {}  # key -> dict of verification columns (full row copy) or partial

    # prior reviewer's manual corrections (majors, marketplaces)
    for line in open("data/qa/corrections_work.jsonl"):
        r = json.loads(line)
        cur = row(live, r["key"])
        pas = "pass1_majors"
        add(r["key"], r["current_status"], r["corrected_status"], r["category"], pas, r["reason"], r["evidence_url"], r["store_name"])
        updates[r["key"]] = {"status": r["corrected_status"], "reason": f"qa_review:{r['category']}: {r['reason'][:200]}", "evidence_url": r["evidence_url"] or None}

    # work1: service-typed Salla flips
    w1 = work[1]
    for key in json.load(open("/tmp/work1_keys.json")):
        a, b = row(live, key), row(w1, key)
        if not b or b["status"] != "verified" or a["status"] == "verified":
            continue
        if key in W1_NOT_APPLIED:
            continue
        add(key, a["status"], "verified", "wrong_exclusion_service_typed_physical", "pass1_rules",
            f"Merchant registered shipped goods as Salla type service/digital; storefront API is_require_shipping marks physical products; catalogue: "
            f"{b['category']}. Previously: {a['reason'][:60]}", b["evidence_url"] or a["final_url"], a["store_name"])
        updates[key] = dict(zip(VCOLS, tuple(b[c] for c in VCOLS))) | {"_copy": True}

    # work2 flips
    for key, (cat, reason) in W2_FLIPS.items():
        a, b = row(live, key), row(work[2], key)
        assert a and b and b["status"] == "verified", key
        add(key, a["status"], "verified", cat, "pass2_medium" if key in ("moodyul.com", "rifaclothing.com") else "pass1_rules", reason, b["evidence_url"] or a["final_url"], a["store_name"])
        updates[key] = dict(zip(VCOLS, tuple(b[c] for c in VCOLS))) | {"_copy": True}

    # work3 flips (verified -> not verified, unverified -> verified/rejected)
    w3 = work[3]
    for key in [x.strip() for x in open("/tmp/work3_keys.txt")]:
        a, b = row(live, key), row(w3, key)
        if key in updates or key in MANUAL or key in W3_KEEP:
            continue
        if a["status"] == b["status"]:
            continue
        if any((b["reason"] or "").startswith(t) for t in TRANSIENT):
            continue
        if a["status"] == "verified" and b["status"] != "verified":
            if key in NONSTORE and key not in {"adwc.sa", "midea.com|sa"}:
                pass
            add(key, a["status"], b["status"], "wrong_inclusion_non_store_or_weak_evidence", "pass1_rules",
                f"{NONSTORE.get(key, 'insufficient purchase/product evidence on live re-check')}; fixed verifier: {b['reason'][:90]}", a["final_url"], a["store_name"])
        elif a["status"] == "unverified":
            add(key, a["status"], b["status"], "retry_resolved_rate_limited" if b["status"] == "verified" else "retry_resolved_rejected", "pass1_rules",
                f"Previously rate-limited (HTTP 429); re-verified politely: {b['reason'][:90]}", b["evidence_url"] or a["final_url"], a["store_name"])
        updates[key] = dict(zip(VCOLS, tuple(b[c] for c in VCOLS))) | {"_copy": True}

    # manual
    for key, (new, cat, reason) in MANUAL.items():
        a = row(live, key)
        if key in updates or a is None:
            if a is None:
                print("MISSING", key)
            continue
        add(key, a["status"], new, cat, "pass1_majors" if "secondary" in cat or "marketplace" in cat else "pass1_rules", reason, a["final_url"], a["store_name"])
        updates[key] = {"status": new, "reason": f"qa_review:{cat}: {reason[:200]}"}
    for key, why in NONSTORE.items():
        a = row(live, key)
        if a is None:
            print("MISSING", key)
            continue
        if key in updates or a["status"] not in ("verified", "verified_secondary_evidence"):
            continue
        new = "unverified" if key in UNVER else "rejected"
        cat = "wrong_inclusion_non_store"
        add(key, a["status"], new, cat, "pass1_rules", f"Live homepage re-check 2026-10-17: {why}", a["final_url"], a["store_name"])
        updates[key] = {"status": new, "reason": f"qa_review:{cat}: {why}"}

    print("corrections", len(corr))
    if DRY:
        return
    con = live
    con.execute("BEGIN IMMEDIATE")
    for key, u in updates.items():
        if u.pop("_copy", False):
            cols = [c for c in VCOLS if c != "key"]
            con.execute(f"UPDATE verifications SET {', '.join(c + '=?' for c in cols)}, duplicate_of=NULL WHERE key=?", [u[c] for c in cols] + [key])
            st = u["status"]
        else:
            sets = ", ".join(f"{c}=?" for c in u)
            con.execute(f"UPDATE verifications SET {sets}, verified_at=?, method=COALESCE(method,'http'), duplicate_of=NULL WHERE key=?", list(u.values()) + [NOW, key])
            st = u["status"]
        con.execute("UPDATE candidates SET status=? WHERE key=?", ("verified" if st in ("verified", "verified_secondary_evidence") else st, key))
    con.execute("COMMIT")
    with open("data/qa/sonnet_review_corrections.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(corr[0]))
        wr.writeheader()
        wr.writerows(corr)


main()
