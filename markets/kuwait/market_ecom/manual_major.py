"""Manual acceptance of well-known major retailers whose two-proof verification was blocked (bot wall / geo-block / JS-only / timeout)."""
from . import db

LABEL = "Known major retailer – manually accepted"
ACCEPT = [
    dict(key="potterybarn.com.kw", name="Pottery Barn Kuwait", category="Home & Furniture", url="https://www.potterybarn.com.kw/",
         blocked="a site-wide HTTP 503 'maintenance' page (Alshaya Magento Cloud) on every path including robots.txt, re-checked repeatedly; this is a maintenance state, not evidence of closure",
         evidence="Alshaya-operated Kuwait storefront on the brand's .com.kw country domain; Wayback capture of potterybarn.com.kw 2025-02-17; sibling Alshaya Kuwait storefronts verified in this directory",
         evidence_url="https://web.archive.org/web/20250217113705/https://www.potterybarn.com.kw/"),
    dict(key="westelm.com.kw", name="West Elm Kuwait", category="Home & Furniture", url="https://www.westelm.com.kw/",
         blocked="a site-wide HTTP 503 'maintenance' page (Alshaya Magento Cloud) on every path including robots.txt, re-checked repeatedly; this is a maintenance state, not evidence of closure",
         evidence="Alshaya-operated Kuwait storefront on the brand's .com.kw country domain; Wayback capture of westelm.com.kw 2025-04-16",
         evidence_url="https://web.archive.org/web/20250416074412/https://www.westelm.com.kw/"),
    dict(key="zain.com", name="Zain Kuwait eShop", category="Telecom Devices & Electronics", url="https://www.kw.zain.com/en/shop",
         blocked="a client-side rendered Liferay Commerce shop whose catalogue API sits behind a WAF (not bypassed) and renders an empty body in headless Chromium",
         evidence="kw.zain.com/en/shop loads (HTTP 200) with KWD channel currency; Wayback capture of kw.zain.com/en/shop 2026-09-05; Common Crawl CC-MAIN-2026-39 capture of a Zain business-shop devices page with a KWD price",
         evidence_url="https://web.archive.org/web/20260905173048/https://www.kw.zain.com/en/shop"),
    dict(key="faces.com|kw", name="Faces", category="Beauty & Cosmetics", url="https://www.faces.com/",
         blocked="faces.com geo-redirecting this VM to the UAE site faces.ae (faces.com/en-kw returns 404 from here) and no Kuwait product page in archives",
         evidence="Kuwait App Store Shopping app 'FACES Beauty' by Allied Enterprises LLC (Chalhoub Group) updated 2026-09-23; Faces serves Kuwait through its country-selector storefront",
         evidence_url="https://apps.apple.com/kw/app/faces-beauty-%D9%81%D9%8A%D8%B3%D8%B2/id1531855095"),
    dict(key="shein.com", name="SHEIN", category="Fashion & Apparel", url="https://ar.shein.com/",
         blocked="geo-redirect of shein.com to other country storefronts and no dedicated Kuwait path; the Middle East storefront ar.shein.com serves GCC countries via country selection",
         evidence="ar.shein.com (Middle East storefront, HTTP 200) lists the Kuwaiti Dinar (KWD) among its supported currencies; Kuwait App Store listing for the SHEIN shopping app updated 2026-10-17",
         evidence_url="https://apps.apple.com/kw/app/shein-shopping-online/id878577184"),
    dict(key="stc.com.kw", name="stc Kuwait", category="Telecom Devices & Electronics", url="https://www.stc.com.kw/",
         blocked="an HTTP 403 bot wall on stc.com.kw (not bypassed) and no recent archive capture",
         evidence="known Kuwait country domain of stc Kuwait (Kuwait Communication Company) with an online device shop; Kuwait App Store app 'mystc KW' updated 2026-10-06 is an account app only, so this acceptance rests on known-brand status",
         evidence_url="https://apps.apple.com/kw/app/mystc-kw/id511293831"),
]

REJECT = []


def main():
    con = db.connect()
    for a in ACCEPT:
        note = (f"{LABEL}: manually accepted as known major retailer; automated two-proof verification blocked by {a['blocked']}. "
                f"Evidence: {a['evidence']}")
        root = a.get("root") or a["key"].split("|")[0]
        con.execute("INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,first_source,source_detail,discovered_at,status,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                    (a["key"], a["url"], root, "independent", "reference:manual_major", "manual major acceptance", db.now(), "verified", 10))
        con.execute("INSERT OR IGNORE INTO verifications(key, status) VALUES(?, 'unverified')", (a["key"],))
        con.execute("""UPDATE verifications SET status='verified_manual_major', method='manual_major', reason=?, category=?, store_name=?,
                       final_url=?, final_key=?, verified_at=?, duplicate_of=NULL, evidence_url=COALESCE(?, evidence_url) WHERE key=?""",
                    (note, a["category"], a["name"], a["url"], a["key"], db.now(), a.get("evidence_url"), a["key"]))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (a["key"],))
    con.execute("CREATE TABLE IF NOT EXISTS ref_overrides(ref_id INTEGER PRIMARY KEY, status TEXT, reason TEXT, evidence TEXT, url TEXT, key TEXT, ts TEXT)")
    for r in REJECT:
        row = con.execute("SELECT ref_id FROM reference_stores WHERE name=? AND kind IN ('brand','mall')", (r["ref"],)).fetchone()
        if row:
            con.execute("INSERT OR REPLACE INTO ref_overrides VALUES(?,?,?,?,?,?,?)",
                        (row[0], "excluded", r["reason"], r.get("evidence", ""), r.get("url", ""), r.get("key"), db.now()))
    con.commit()


if __name__ == "__main__":
    main()
