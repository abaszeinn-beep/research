"""Manual acceptance of well-known major retailers whose two-proof verification was blocked (bot wall / geo-block / JS-only / timeout)."""
from . import db

LABEL = "Known major retailer – manually accepted"
ACCEPT = [
    dict(key="luluhypermarket.com|ae", name="Lulu Hypermarket", category="Grocery & Food", url="https://www.luluhypermarket.com/en-ae/",
         blocked="an Akamai/Cloudflare-style HTTP 403 bot wall on the live storefront (robots.txt returns 522)",
         evidence="UAE App Store Shopping app 'LuLu Hypermarket' by Lulu Group International updated 2026-10-08; Wayback capture of luluhypermarket.com/en-ae 2024-12-01; known country storefront /en-ae",
         evidence_url="https://apps.apple.com/ae/app/lulu-hypermarket/id6739010114"),
    dict(key="emaxme.com", name="Emax", category="Computers & Electronics", url="https://uae.emaxme.com/",
         blocked="HTTP 403 bot wall on emaxme.com / uae.emaxme.com (robots.txt 403)",
         evidence="UAE App Store Shopping app 'Emax - Electronics Online' by Landmark Retail Limited updated 2026-10-05; Wayback capture of uae.emaxme.com 2026-02-28; UAE subdomain recorded as the redirect target of emax.ae",
         evidence_url="https://web.archive.org/web/20260228222229/https://uae.emaxme.com/"),
    dict(key="lifestylestores.com|ae", name="Lifestyle", category="Fashion & Apparel", url="https://www.lifestyleshops.com/ae/",
         blocked="HTTP 403 bot wall on the live storefront and no recent archive capture",
         evidence="Landmark Group's Lifestyle department-store online shop for the UAE (/ae/); sister Landmark apps Max Fashion, Emax, Splash and Centrepoint listed in the UAE App Store (updated 2026-10-02..05); no dedicated Lifestyle app or recent archive proof found, so this acceptance rests on known-brand status",
         evidence_url="https://apps.apple.com/ae/app/centrepoint-online-shopping/id1235099347"),
    dict(key="ajmalperfume.com", name="Ajmal Perfumes", category="Perfumes & Oud", url="https://www.ajmalperfume.com/",
         blocked="HTTP 403 bot wall on the live storefront; Wayback captures date from 2022 (outside the 12-month window)",
         evidence="UAE App Store Shopping app 'Ajmal Perfume Online(Official)' by Ajmal International Trading Co LLC updated 2026-10-15; Wayback capture of ajmalperfume.com 2022-05-22",
         evidence_url="https://apps.apple.com/ae/app/ajmal-perfume-online-official/id1451387539"),
    dict(key="joyalukkas.com|ae", name="Joyalukkas", category="Jewelry & Watches", url="https://www.joyalukkas.com/ae/",
         blocked="a JavaScript-only storefront with no server-rendered AED price or add-to-cart in static HTML",
         evidence="UAE App Store Shopping app 'Joyalukkas Jewellery Shopping' by Joyalukkas India Limited updated 2026-09-29; 1,363 product URLs in the sitemap; /ae/ page loads (HTTP 200) and was captured by Wayback 2026-06-17",
         evidence_url="https://apps.apple.com/ae/app/joyalukkas-jewellery-shopping/id1667259209"),
    dict(key="dubaidutyfree.com", name="Dubai Duty Free", category="General / Unclassified", url="https://www.dubaidutyfree.com/",
         blocked="Akamai HTTP 403 for scripted clients and live fetch timeouts, leaving one automated proof",
         evidence="Wayback product page with AED price, ordering control and Offer JSON-LD (2026-10-12); Wayback home page capture 2026-10-05",
         evidence_url="https://web.archive.org/web/20261012202055/https://www.dubaidutyfree.com/the-botanist-hebridean-strength-islay-dry-gin-700ml/product/114156317"),
]


def main():
    con = db.connect()
    for a in ACCEPT:
        note = (f"{LABEL}: manually accepted as known major retailer; automated two-proof verification blocked by {a['blocked']}. "
                f"Evidence: {a['evidence']}")
        con.execute("""UPDATE verifications SET status='verified_manual_major', method='manual_major', reason=?, category=?, store_name=?,
                       final_url=?, final_key=?, verified_at=?, duplicate_of=NULL, evidence_url=COALESCE(?, evidence_url) WHERE key=?""",
                    (note, a["category"], a["name"], a["url"], a["key"], db.now(), a.get("evidence_url"), a["key"]))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (a["key"],))
    con.commit()


if __name__ == "__main__":
    main()
