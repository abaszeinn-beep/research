"""Manual acceptance of well-known major US retailers whose two-proof verification was blocked (bot wall / browser failure / JS-only page).

  python3 -m mktecom.manual_major

Accepted rows get status `verified_manual_major` (sheet label "Known major retailer – manually accepted"). Rejected rows stay out of the
directory and are recorded in `major_decisions` as `manual_reject` so the Major Retailer Coverage Audit shows them as excluded.
Evidence is taken from the stored secondary-evidence proofs plus the Wayback availability lookups saved in qa/manual_major_wayback.json.
"""
from __future__ import annotations

import json
import os
import re

from . import db

LABEL = "Known major retailer – manually accepted"
WAYBACK = os.path.join(os.path.dirname(__file__), "..", "qa", "manual_major_wayback.json")

# reference name -> (display name, storefront URL)
ACCEPT = {
    "Ahold Delhaize USA (Stop & Shop)": ("Stop & Shop", "https://stopandshop.com/"),
    "Bass Pro Shops": ("Bass Pro Shops", "https://www.basspro.com/"),
    "Fanatics": ("Fanatics", "https://www.fanatics.com/"),
    "H&M US": ("H&M", "https://www.hm.com/en_us/"),
    "Meijer": ("Meijer", "https://www.meijer.com/"),
    "Zara US": ("Zara", "https://www.zara.com/us/"),
    "JCPenney": ("JCPenney", "https://www.jcpenney.com/"),
    "REI": ("REI", "https://www.rei.com/"),
    "Ann Taylor": ("Ann Taylor", "https://www.anntaylor.com/"),
    "Summit Racing": ("Summit Racing", "https://www.summitracing.com/"),
    "1-800 Contacts": ("1-800 Contacts", "https://www.1800contacts.com/"),
    "B&H Photo Video": ("B&H Photo Video", "https://www.bhphotovideo.com/"),
    "Bergdorf Goodman": ("Bergdorf Goodman", "https://www.bergdorfgoodman.com/"),
    "Cabela's": ("Cabela's", "https://www.cabelas.com/"),
    "Converse": ("Converse", "https://www.converse.com/"),
    "Crutchfield": ("Crutchfield", "https://www.crutchfield.com/"),
    "DigiKey": ("DigiKey", "https://www.digikey.com/"),
    "Estée Lauder": ("Estée Lauder", "https://www.esteelauder.com/"),
    "Finish Line": ("Finish Line", "https://www.finishline.com/"),
    "Hermès US": ("Hermès", "https://www.hermes.com/us/en/"),
    "Lancôme US": ("Lancôme", "https://www.lancome-usa.com/"),
    "Lids": ("Lids", "https://www.lids.com/"),
    "MLB Shop": ("MLB Shop", "https://www.mlbshop.com/"),
    "Micro Center": ("Micro Center", "https://www.microcenter.com/"),
    "Mouser Electronics": ("Mouser Electronics", "https://www.mouser.com/"),
    "NAPA Auto Parts": ("NAPA Auto Parts", "https://www.napaonline.com/"),
    "NBA Store": ("NBA Store", "https://store.nba.com/"),
    "NFL Shop": ("NFL Shop", "https://www.nflshop.com/"),
    "Neiman Marcus": ("Neiman Marcus", "https://www.neimanmarcus.com/"),
    "Net-a-Porter US": ("Net-a-Porter", "https://www.net-a-porter.com/en-us/"),
    "New Balance": ("New Balance", "https://www.newbalance.com/"),
    "Pep Boys": ("Pep Boys", "https://www.pepboys.com/"),
    "RH": ("RH", "https://rh.com/"),
    "Ray-Ban US": ("Ray-Ban", "https://www.ray-ban.com/usa"),
    "Saks Fifth Avenue": ("Saks Fifth Avenue", "https://www.saksfifthavenue.com/"),
    "Southeastern Grocers (Winn-Dixie)": ("Winn-Dixie", "https://www.winndixie.com/"),
    "Sunglass Hut": ("Sunglass Hut", "https://www.sunglasshut.com/"),
    "Vans": ("Vans", "https://www.vans.com/"),
    "Zoro": ("Zoro", "https://www.zoro.com/"),
    "iHerb": ("iHerb", "https://www.iherb.com/"),
    "Gucci US": ("Gucci", "https://www.gucci.com/us/en/"),
    "Men's Wearhouse": ("Men's Wearhouse", "https://www.menswearhouse.com/"),
    "LG US": ("LG Electronics USA", "https://www.lg.com/us"),
    "Madewell": ("Madewell", "https://www.madewell.com/"),
    "Mattress Firm": ("Mattress Firm", "https://www.mattressfirm.com/"),
    "RockAuto": ("RockAuto", "https://www.rockauto.com/"),
    "Backcountry": ("Backcountry", "https://www.backcountry.com/"),
    "Container Store": ("The Container Store", "https://www.containerstore.com/"),
}

REJECT = {
    "WinCo Foods": "no online ordering: WinCo Foods does not offer online grocery ordering, delivery or pickup; wincofoods.com is a store-locator/corporate site (the archived 'ordering control' is not a purchase path)",
    "Ford Motor Company": "manufacturer corporate site: ford.com sells vehicles through dealers and has no consumer product store (parts/accessories sit on separate hosts); same treatment as GM and Toyota",
    "T-ZONE": "not a recognisable major retailer: only a small Shopify gift shop (tzonegifts.myshopify.com) matched this reference name; partial evidence only, left out",
    "Fastenal": "B2B industrial distributor: online ordering requires a business customer account; no consumer storefront evidenced",
    "Arrow Electronics": "B2B electronic-components distributor aimed at engineers and procurement; no consumer storefront evidenced (DigiKey and Mouser, which sell to individuals, are accepted)",
    "McKesson Medical-Surgical": "B2B medical-supply distributor: ordering requires a provider account; no consumer storefront",
    "US Foods": "B2B foodservice distributor: ordering requires a business account; no consumer storefront",
}

BLOCK_TEXT = [
    (r"blocked_or_challenge_http_200", "a bot-protection interstitial on the live homepage (not bypassed)"),
    (r"blocked_or_challenge|http_403|http_429|rate_limited", "an HTTP 403/429 bot wall on the live storefront (not bypassed)"),
    (r"fetch_failed|browser_error|timeout", "browser fetch failures/timeouts on the live storefront"),
    (r"js_rendered|insufficient_ecommerce|partial_ecommerce|thin_page", "a JavaScript-rendered storefront with no product/purchase evidence in static HTML"),
]


def blocked_reason(reason):
    for rx, txt in BLOCK_TEXT:
        if re.search(rx, reason or ""):
            return txt
    return "bot protection / rendering limits on the live storefront"


def proofs(con, key, wb):
    out = []
    row = con.execute("SELECT evidence FROM secondary_evidence WHERE key=?", (key,)).fetchone()
    if row:
        for e in json.loads(row[0]):
            if e.get("ok"):
                bits = [e.get("detail") or e["type"]]
                if e.get("url"):
                    bits.append(e["url"])
                out.append(f"{e['type']}: " + " ".join(bits))
    if wb and wb.get("timestamp"):
        out.append(f"Wayback capture of the storefront {wb['timestamp'][:8]} ({wb.get('url')})")
    return out


def main():
    con = db.connect()
    wbs = json.load(open(WAYBACK, encoding="utf-8"))
    con.execute("""CREATE TABLE IF NOT EXISTS major_decisions(key TEXT PRIMARY KEY, name TEXT, tier TEXT, before_status TEXT, decision TEXT, rule TEXT,
                   reason TEXT, evidence TEXT, decided_at TEXT)""")
    now = db.now()
    for ref, (disp, url) in ACCEPT.items():
        r = con.execute("SELECT key, tier, category FROM reference_stores WHERE name=? AND kind='brand'", (ref,)).fetchone()
        key, tier, cat = r
        old = con.execute("SELECT status, reason FROM verifications WHERE key=?", (key,)).fetchone()
        before, oldreason = (old or ("unverified", ""))
        ps = proofs(con, key, (wbs.get(ref) or {}).get("wayback"))
        blocked = blocked_reason(oldreason)
        ev = "; ".join(ps) if ps else "known major US retailer (reference universe: NRF/Wikidata chain list)"
        note = f"{LABEL}: manually accepted as known major retailer; automated two-proof verification blocked by {blocked}. Evidence: {ev}"[:1800]
        con.execute("INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,first_source,source_detail,discovered_at,status,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, url, key.split("|")[0], "independent", "reference:manual_major", disp, now, "verified", 10))
        con.execute("INSERT OR IGNORE INTO verifications(key, status) VALUES(?, 'unverified')", (key,))
        con.execute("""UPDATE verifications SET status='verified_manual_major', method='manual_major', reason=?, category=?, store_name=?,
                       final_url=?, final_key=?, verified_at=?, duplicate_of=NULL, platform=COALESCE(NULLIF(platform,''), 'unknown (manual major)') WHERE key=?""",
                    (note, cat, disp, url, key, now, key))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (key,))
        con.execute("INSERT OR REPLACE INTO major_decisions VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, ref, tier, before, "manual_accept", "manual_major",
                     f"manually accepted as known major retailer; automated two-proof verification blocked by {blocked}", ev[:1500], now))
    for ref, reason in REJECT.items():
        r = con.execute("SELECT key, tier FROM reference_stores WHERE name=?", (ref,)).fetchone()
        key, tier = r
        old = con.execute("SELECT status FROM verifications WHERE key=?", (key,)).fetchone()
        con.execute("INSERT OR REPLACE INTO major_decisions VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, ref, tier, old[0] if old else "unverified", "manual_reject", "manual_major", reason, "", now))
    con.commit()
    print("accepted", len(ACCEPT), "rejected", len(REJECT))


if __name__ == "__main__":
    main()
