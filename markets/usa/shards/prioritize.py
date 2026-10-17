"""Re-rank pending candidates so likely medium/large stores are verified first.

score = platform tier + custom-domain bonus + Tranco rank bonus + log(hits) (more crawled product pages / snapshots).
"""
from __future__ import annotations

import math

from . import db
from .export import load_tranco

PLATFORM_TIER = {"salesforce-commerce": 60, "magento": 45, "bigcommerce": 45, "shopware": 30, "shift4shop": 20,
                 "volusion": 20, "prestashop": 15, "woocommerce": 15, "opencart": 12, "ecwid": 10, "squarespace": 8,
                 "wix": 6, "square": 5, "bigcartel": 4}
SHARED = {"wixsite.com", "editorx.io", "square.site", "company.site", "mybigcommerce.com", "bigcartel.com", "3dcartstores.com",
          "azurewebsites.net", "ecwid.com", "myvolusion.com", "volusion.store", "squarespace.com", "weebly.com", "wordpress.com"}


def tranco_bonus(rank):
    if not rank:
        return 0
    return 80 if rank <= 50_000 else 60 if rank <= 200_000 else 40 if rank <= 500_000 else 25


def main():
    con = db.connect()
    tr = load_tranco()
    print("tranco", len(tr))
    rows = con.execute("SELECT key, root_domain, platform_hint, hits, tld FROM candidates WHERE status='pending'").fetchall()
    upd = []
    for key, root, plat, hits, tld in rows:
        s = PLATFORM_TIER.get(plat or "", 10)
        if root not in SHARED:
            s += 25
        if root not in SHARED:
            s += tranco_bonus(tr.get(root))
        s += 6 * math.log10(1 + (hits or 0))
        if tld == "us":
            s += 3
        upd.append((s, key))
    con.execute("BEGIN")
    con.executemany("UPDATE candidates SET priority=? WHERE key=?", upd)
    con.execute("COMMIT")
    print("reprioritized", len(upd))


if __name__ == "__main__":
    main()
