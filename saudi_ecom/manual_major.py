"""Manual acceptance of well-known major retailers whose two-proof verification was blocked (bot wall / geo-block / stale archive)."""
from . import db

LABEL = "Known major retailer – manually accepted"
ACCEPT = [
    dict(key="pullandbear.com|sa", name="Pull&Bear", category="Fashion & Apparel", url="https://www.pullandbear.com/sa/",
         blocked="live storefront returns HTTP 403 to automated fetches and the Wayback product capture is older than the 12-month window",
         evidence="Saudi App Store listing 'PULL&BEAR' (Inditex) updated 2026-10-14; Wayback product page with SAR price and ordering control 2025-09-06; Saudi locale /sa/ on pullandbear.com"),
    dict(key="sivvi.com|sa", name="Sivvi", category="Fashion & Apparel", url="https://www.sivvi.com/saudi-en/",
         blocked="live storefront times out for automated fetches and archive/App Store proofs are older than the 12-month window",
         evidence="Saudi App Store listing 'SIVVI Online Shopping' (Noon) updated 2025-09-19; Wayback product page with 4 SAR price strings and ordering control 2025-03-06; Saudi locale /saudi-en/"),
]


def main():
    con = db.connect()
    for a in ACCEPT:
        note = f"{LABEL}: manually accepted as known major retailer; automated two-proof verification blocked by {a['blocked']}. Evidence: {a['evidence']}"
        con.execute("""UPDATE verifications SET status='verified_manual_major', method='manual_major', reason=?, category=?, store_name=?, verified_at=?
                       WHERE key=?""", (note, a["category"], a["name"], db.now(), a["key"]))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (a["key"],))
    con.commit()


if __name__ == "__main__":
    main()
