"""Manual acceptance of well-known major retailers whose two-proof verification was blocked (bot wall / geo-block / JS-only / timeout)."""
from . import db

LABEL = "Known major retailer – manually accepted"
ACCEPT = [
    dict(key="monoprix.qa", name="Monoprix Qatar", category="Grocery & Supermarket", url="https://www.monoprix.qa/",
         blocked="a captcha challenge (sgcaptcha, not bypassed) on monoprix.qa; the sibling host monoprix-qatar.com is JS-only",
         evidence="Qatar App Store app 'Monoprix Qatar - M Loyalty' by The Market Hall updated 2026-03-31; Wayback capture of monoprix.qa 2026-02-14; .qa storefront domain",
         evidence_url="https://web.archive.org/web/20260214013524/https://www.monoprix.qa/"),
    dict(key="maxfashion.com|qa", name="Max Fashion", category="Fashion & Apparel", url="https://www.maxfashion.com/qa/en/",
         blocked="HTTP 403 to non-browser clients on maxfashion.com/qa; newest archived Qatar product pages date from 2025-08-19 (outside the 12-month window)",
         evidence="Qatar App Store app 'Max Fashion' by Landmark Retail Limited updated 2026-10-05; Wayback captures of maxfashion.com/qa/en/ (2025-07-06) and Qatar product pages (2025-08-19); known /qa/en/ country storefront",
         evidence_url="https://web.archive.org/web/20250706160300/https://www.maxfashion.com/qa/en/"),
    dict(key="shein.com", name="SHEIN", category="Fashion & Apparel", url="https://ar.shein.com/",
         blocked="geo-redirect of shein.com to other country storefronts and no dedicated Qatar path; the Middle East storefront ar.shein.com serves GCC countries via country selection",
         evidence="ar.shein.com (Middle East storefront, HTTP 200) lists the Qatar Riyal (QAR) among its supported currencies; Qatar App Store app 'SHEIN-Shopping Online' by ROADGET BUSINESS PTE. LTD. updated 2026-10-17",
         evidence_url="https://apps.apple.com/qa/app/shein-shopping-online/id878577184"),
]

REJECT = [
    dict(ref="Malabar Gold & Diamonds",
         reason="excluded (manual review): malabargoldanddiamonds.com has country storefronts for in, ae, uk and us only; the Qatar pages are a physical store locator and /qa/ returns HTTP 400. The Qatar App Store listing (genre Lifestyle) is not proof of a Qatar online store or delivery.",
         url="https://www.malabargoldanddiamonds.com/"),
]


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
