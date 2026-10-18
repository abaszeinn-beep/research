"""Manual / targeted resolutions for reference brands (evidence gathered by hand or by scripts/major_probe.py).

Verified entries are written into candidates + verifications (idempotent) and mapped to the reference store;
exclusions / keep-unresolved decisions go to `ref_overrides`, which `reference.audit` applies last.
Every proof carries its URL and a date. No challenge/bot wall/robots rule was bypassed to collect these.

  ECOM_MARKET=qatar python3 -m market_ecom.manual_resolve
"""
from __future__ import annotations

import json
import os

from . import db
from .reference import connect

TSV = os.path.join(os.path.dirname(__file__), "data", "manual_resolutions.json")


def apply(con):
    with open(TSV, encoding="utf-8") as fh:
        items = json.load(fh)
    con.execute("CREATE TABLE IF NOT EXISTS ref_overrides(ref_id INTEGER PRIMARY KEY, status TEXT, reason TEXT, evidence TEXT, url TEXT, key TEXT, ts TEXT)")
    now = db.now()
    for it in items:
        row = con.execute("SELECT ref_id FROM reference_stores WHERE name=? AND kind IN ('brand','mall')", (it["ref"],)).fetchone()
        if not row:
            print("missing ref", it["ref"])
            continue
        ref_id = row[0]
        act = it["action"]
        if act in ("verified", "verified_secondary_evidence"):
            key, sf = it["key"], it["storefront"]
            proofs = it["proofs"]
            text = " | ".join(f"{p['type']}: {p['detail']} ({p['url']}, {p['date']})" for p in proofs)
            reason = f"{act}: {text}"
            root = it.get("root") or key.split("|")[0]
            con.execute("INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,first_source,source_detail,discovered_at,status,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                        (key, sf, root, "independent", "reference:manual", f"ref {ref_id}", now, "verified", 10))
            con.execute("UPDATE candidates SET status='verified' WHERE key=?", (key,))
            con.execute("DELETE FROM verifications WHERE key=?", (key,))
            con.execute("""INSERT INTO verifications(key, final_url, final_key, http_status, store_name, platform, category, market_score, market_evidence,
                           ecom_evidence, product_evidence, status, reason, evidence_url, verified_at, method)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (key, sf, key, it.get("http", 0), it["name"], it.get("platform", "custom/unknown"), it["category"], 0.94,
                         json.dumps({"manual": True, "qar_prices": True}), json.dumps({}), proofs[0]["url"], act, reason, proofs[0]["url"], it["verified_at"], "manual_resolve"))
            con.execute("DELETE FROM reference_urls WHERE ref_id=? AND via='manual'", (ref_id,))
            con.execute("INSERT OR REPLACE INTO reference_urls VALUES(?,?,?,?,?,?,?,?)", (ref_id, sf, key, "manual", None, sf, "{}", now))
        elif act == "map":
            con.execute("DELETE FROM reference_urls WHERE ref_id=? AND via='manual'", (ref_id,))
            con.execute("INSERT OR REPLACE INTO reference_urls VALUES(?,?,?,?,?,?,?,?)", (ref_id, it["storefront"], it["key"], "manual", None, it["storefront"], "{}", now))
        else:
            con.execute("INSERT OR REPLACE INTO ref_overrides VALUES(?,?,?,?,?,?,?)",
                        (ref_id, act, it["reason"], it.get("evidence", ""), it.get("storefront", ""), it.get("key"), now))
    methods = ("path-pattern Wayback product probes (qa, en-qa, qa-en, qa/en, qa/ar, en_qa, qa_en, qatar, shop./qa./.com.qa host variants), "
               "hreflang/selector links and robots.txt sitemaps on the brand site, Shopify /meta.json markets, live Qatar paths, Qatar App Store, GCC operator host variants")
    for ref_id, doms in con.execute("SELECT ref_id, domains FROM reference_stores WHERE kind='brand' AND status='excluded' AND reason LIKE 'excluded: no%storefront found%'").fetchall():
        if not con.execute("SELECT 1 FROM ref_overrides WHERE ref_id=?", (ref_id,)).fetchone():
            con.execute("INSERT INTO ref_overrides VALUES(?,?,?,?,?,?,?)", (ref_id, "excluded", "excluded: no Qatar storefront found after extended search (" + methods + ", checked 2026-10-17)", "", "", None, now))
    con.commit()


if __name__ == "__main__":
    apply(connect())
