"""Remove obvious non-stores (hosting/SaaS/agencies, adult, nonprofits/institutions, corporate/media/attraction sites) from the verified set.

  python3 -m mktecom.nonstore_filter [--apply]
Name, domain, category and stored reason are matched; rejected rows keep the reason 'nonstore_filter: <rule>'.
"""
import argparse, re
from collections import Counter
from . import db, export

RULES = [
    ("adult", r"\b(porn|xxx|sex ?toys?|adult toys?|adult (?:store|shop|novelt\w+|magazines?)|erotic|vibrators?|dildos?|fetish|bdsm|sexshop|sex shop)\b|sextoys|adulttoy|sex-toy"),
    ("hosting_saas_agency", r"\b(web ?hosting|hosting|domain registr\w+|vps|residential proxies|proxy provider|saas|loyalty (?:&|and) retention platform|marketing agency|seo agency|web design|web development|digital agency|shoppable content|franchise growth|software company|managed services|it services|cloud services|ai services|crypto mining hosting)\b"),
    ("nonprofit_institution", r"\b(foundation|association|institute|society|ministry|ministries|church|synagogue|university|college alumni|museum|council|conservancy|association of america)\b"),
    ("foreign_cctld", r"\.(?:uk|au|ca|de|fr|nl|ro|it|in|pk|ar|ec|pa|sv|es|br|mx|jp|cn|ru|pl|se|no|dk|fi|ie|nz|za|sg|hk|tw|kr|id|my|ph|th|vn|tr|gr|pt|cz|hu|at|ch|be|ua|il|ae|sa|eg|ng|ke|cl|co\.uk|com\.au|co\.nz|co\.za)$"),
    ("corporate_attraction_media", r"\b(shopping mall|the mall at|magazine for the love|santa monica pier|news(?:paper)?|radio network|tv network)\b"),
]
RXS = [(n, re.compile(p, re.I)) for n, p in RULES]
ORG_TLD = re.compile(r"\.(?:org|edu|gov)(?:\||$|/)")
NONPROFIT_NAME_ONLY_ORG = RXS[2]


def main(apply):
    con = db.connect()
    export.dedup(con)
    rows = con.execute("SELECT key, store_name, category, final_url, reason, status, platform FROM verifications WHERE status LIKE 'verified%' AND duplicate_of IS NULL").fetchall()
    hits = []
    for key, name, cat, url, reason, st, plat in rows:
        text = f"{name or ''} {key}"
        for rn, rx in RXS:
            if rn == "foreign_cctld":
                if "|" not in key and rx.search(key.split("/")[0]):
                    hits.append((key, name, rn, plat))
                    break
                continue
            if rn == "nonprofit_institution":
                if ORG_TLD.search(key + "|") and rx.search(text):
                    hits.append((key, name, rn, plat))
                    break
                continue
            if rx.search(text):
                hits.append((key, name, rn, plat))
                break
    c = Counter(h[2] for h in hits)
    print(c)
    for h in hits:
        print(h)
    if apply:
        con.execute("BEGIN")
        for key, name, rn, plat in hits:
            con.execute("UPDATE verifications SET status='rejected', reason=? WHERE key=?", (f"nonstore_filter: {rn}", key))
            con.execute("UPDATE candidates SET status='rejected' WHERE key=?", (key,))
        con.execute("COMMIT")
    return hits

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args(); main(a.apply)
