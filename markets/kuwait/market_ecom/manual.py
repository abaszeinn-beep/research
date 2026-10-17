"""Hand-curated resolutions for reference stores the automated checks could not settle.

  python3 -m market_ecom.manual

Primary verifications record live checks done with a plain browser-like HTTP client or Chromium (no challenge bypass).
Overrides (excluded / unresolved with a specific reason) are stored in `manual_resolutions` and applied by `reference audit`.
"""
import json

from . import db

NOW = db.now


def pe(url, note):
    return json.dumps({"url": url, "note": note}, ensure_ascii=False)


VERIFIED_LIVE = [
    dict(key="abyat.com|kw", url="https://www.abyat.com/kw/en/", name="Abyat", platform="custom/unknown", category="Home & Furniture",
         ev="https://www.abyat.com/kw/en/products/spacers-cross-shaped-white/101327",
         note="live product page: schema.org Offer priceCurrency=KWD, availability InStock, add-to-cart; 1,592 Kuwait product URLs in robots-listed sitemap https://www.abyat.com/public/sitemaps/products_0.xml; /kw redirects to /sa/ar only for the bare path, /kw/en and /kw/ar serve Kuwait"),
    dict(key="xcite.com", url="https://www.xcite.com/", name="X-cite (Alghanim Electronics)", platform="custom/unknown", category="Electronics & Appliances",
         ev="https://www.xcite.com/keychron-k1-max-qmk-wireless-mechanical-gaming-keyboard-k1m-h1-ar-grey/p",
         note="live product page priced in KD (39.900 KD), schema.org InStock, add-to-cart; product sitemap https://www.xcite.com/sitemaps/sitemap-pdps.xml; +965 phone; App Store kw listing by YOUSUF A. AL GHANIM & SONS"),
    dict(key="ooredoo.com.kw", url="https://store.ooredoo.com.kw/", name="Ooredoo Kuwait Online Store", platform="magento", category="Telecom Devices & Electronics",
         ev="https://store.ooredoo.com.kw/airpods-5.html",
         note="live device product page (AirPods 5, KD 42.00, Add to Cart); store has smartphones, tablets, smartwatches, accessories categories; robots allow catalogue"),
    dict(key="sultan-center.com", url="https://www.sultan-center.com/", name="The Sultan Center (TSC)", platform="custom/unknown", category="Supermarket & Grocery",
         ev="https://www.sultan-center.com/product/al-ain-bottled-drinking-water-6-x-1-5-l",
         note="JS storefront rendered in Chromium (ar-KW/Asia-Kuwait): KD prices, 580+ add-to-cart controls, /product/ pages; robots.txt allows all; App Store kw listing 'Sultan: Grocery & More' by The Sultan Center General Trading & Contracting Co WLL"),
]

RENAME = {"zara.com|kw": "Zara Kuwait", "namshi.com|kw": "Namshi Kuwait", "babyshopstores.com|kw": "Babyshop Kuwait",
          "kw.hm.com": "H&M Kuwait", "abyat.com|kw": "Abyat"}

OVERRIDES = {
    "Alshaya Group (corporate)": ("excluded", "excluded: corporate group, not a store (its brands are separate entries)", ""),
    "Apple Kuwait": ("excluded", "excluded: no Apple online store in Kuwait - https://www.apple.com/kw/buy/ ('Where to shop': buy online or in store from an Apple reseller); apple.com/kw/shop returns 404",
                     "https://www.apple.com/kw/buy/ checked 2026-10-17"),
    "Shein Kuwait": ("unresolved", "unresolved: global multi-country storefront; shein.com geo-redirects this VM to us.shein.com (/kw 404), ar.shein.com defaults to SAR with KWD only in the currency list; only one current Kuwait proof (App Store kw listing, updated 2026-10-17)",
                     "https://apps.apple.com/kw/app/shein-shopping-online/id878577184"),
    "Faces (Chalhoub)": ("unresolved", "unresolved: faces.com geo-redirects to faces.ae from this VM (faces.com/en-kw 404); only one current Kuwait proof (App Store kw listing 'FACES Beauty', updated 2026-09-23); no Kuwait product page found in Common Crawl/Wayback",
                         "https://apps.apple.com/kw/app/faces-beauty-%D9%81%D9%8A%D8%B3%D8%B2/id1531855095"),
    "Zain Kuwait eShop": ("unresolved", "unresolved: Liferay Commerce shop at https://www.kw.zain.com/en/shop/devices is rendered client-side and exposes no prices/product URLs to the verifier (page timed out in Chromium); no archive/Common Crawl product captures; App Store 'Zain KW' is an account app, not a shop",
                          "https://www.kw.zain.com/en/shop/devices"),
    "stc Kuwait shop": ("unresolved", "unresolved: www.stc.com.kw returns HTTP 403 bot wall (not bypassed); no archive, Common Crawl or sitemap proof of a device shop; App Store 'mystc KW' is an account app",
                        "https://www.stc.com.kw/"),
    "Pottery Barn Kuwait (Alshaya)": ("unresolved", "unresolved: potterybarn.com.kw returns HTTP 503 (maintenance/bot wall) and robots/sitemap unreachable; no Wayback or Common Crawl product captures in the last 12 months; no Kuwait app listing",
                                      "https://www.potterybarn.com.kw/"),
    "West Elm Kuwait (Alshaya)": ("unresolved", "unresolved: westelm.com.kw returns HTTP 503 (maintenance/bot wall) and robots/sitemap unreachable; no Wayback or Common Crawl product captures in the last 12 months; no Kuwait app listing",
                                  "https://www.westelm.com.kw/"),
}


def main():
    con = db.connect()
    con.execute("CREATE TABLE IF NOT EXISTS manual_resolutions(name TEXT PRIMARY KEY, status TEXT, reason TEXT, evidence TEXT, ts TEXT)")
    ts = NOW()
    for v in VERIFIED_LIVE:
        note = "verified_live: " + v["note"]
        n = con.execute("""UPDATE verifications SET status='verified', method='manual_live', reason=?, product_evidence=?, evidence_url=?, verified_at=?,
                           store_name=?, platform=?, category=?, final_url=?, final_key=? WHERE key=?""",
                        (note, v["ev"], v["ev"], ts, v["name"], v["platform"], v["category"], v["url"], v["key"], v["key"])).rowcount
        if not n:
            con.execute("INSERT INTO verifications(key, final_url, final_key, store_name, platform, category, status, reason, product_evidence, evidence_url, verified_at, method) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (v["key"], v["url"], v["key"], v["name"], v["platform"], v["category"], "verified", note, v["ev"], v["ev"], ts, "manual_live"))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (v["key"],))
        print("verified", v["key"])
    for k, nm in RENAME.items():
        con.execute("UPDATE verifications SET store_name=? WHERE key=?", (nm, k))
    for name, (st, reason, ev) in OVERRIDES.items():
        con.execute("INSERT OR REPLACE INTO manual_resolutions VALUES(?,?,?,?,?)", (name, st, reason, ev, ts))
    con.commit()


if __name__ == "__main__":
    main()
