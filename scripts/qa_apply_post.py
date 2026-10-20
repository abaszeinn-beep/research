"""Second step of the Sonnet QA apply: reword secondary-evidence downgrades so the coverage audit reports them as
'unresolved' (not 'excluded'), and add SHEIN's Saudi storefront (ar.shein.com), which the reference audit had excluded
because shein.com geo-redirects from a non-Saudi VM.  Idempotent."""
import csv
import datetime as dt
import json
import sqlite3

NOW = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
con = sqlite3.connect("data/saudi_ecom.sqlite")
con.execute("BEGIN IMMEDIATE")
con.execute("""UPDATE verifications SET reason='insufficient_secondary_evidence (qa_review): ' || substr(reason, instr(reason, ': ') + 2)
               WHERE status='unverified' AND (reason LIKE 'qa_review:stale_secondary_evidence%' OR reason LIKE 'qa_review:insufficient_secondary_evidence%')""")
if not con.execute("SELECT 1 FROM candidates WHERE key='ar.shein.com'").fetchone():
    ev = {"platform": "custom/unknown", "product_links": 0, "add_to_cart_markers": 6, "cart_checkout_markers": 0, "jsonld": [],
          "product_evidence": ["34 SAR price strings on the live Arabic homepage"], "purchase_evidence": ["add-to-cart markers on the live Arabic homepage"]}
    con.execute("INSERT INTO candidates(key,url,root_domain,platform_hint,first_source,source_detail,discovered_at,status,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                ("ar.shein.com", "https://ar.shein.com/", "shein.com", None, "qa_review", "Sonnet QA review: Saudi Arabic storefront of SHEIN", NOW, "verified", 0))
    con.execute("""INSERT INTO verifications(key,final_url,final_key,http_status,store_name,platform,category,subcategory,saudi_score,saudi_evidence,
                   ecom_evidence,product_evidence,status,reason,evidence_url,verified_at,method,elapsed,cat_text)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("ar.shein.com", "https://ar.shein.com/", "ar.shein.com", 200, "SHEIN (Saudi Arabia)", "custom/unknown", "Fashion & Apparel", None, 6.0,
                 json.dumps({"signals": ["Arabic Saudi host ar.shein.com", "SAR prices", "Saudi App Store app"]}), json.dumps(ev), None, "verified",
                 "ecommerce+saudi evidence ok (qa_review: live Arabic homepage, SAR prices and cart controls; product pages behind a risk challenge were not accessed)",
                 "https://ar.shein.com/", NOW, "http", 0.0, "fashion"))
con.execute("COMMIT")
rows = list(csv.DictReader(open("data/qa/sonnet_review_corrections.csv")))
if not any(r["key"] == "ar.shein.com" for r in rows):
    rows.append({"key": "ar.shein.com", "store_name": "SHEIN (Saudi Arabia)", "current_status": "rejected (reference row excluded, no candidate)",
                 "corrected_status": "verified", "category": "wrong_exclusion_geo_redirect", "grok_pass": "pass1_majors",
                 "reason": "Reference row 'Shein' was excluded as 'site serves another country' because shein.com geo-redirects to us.shein.com from the US VM; the Arabic Saudi host ar.shein.com serves SAR prices and cart controls live (checked 2026-10-17). Product pages sit behind a risk challenge and were not accessed.",
                 "evidence_url": "https://ar.shein.com/", "reviewed_at_utc": NOW})
    with open("data/qa/sonnet_review_corrections.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
