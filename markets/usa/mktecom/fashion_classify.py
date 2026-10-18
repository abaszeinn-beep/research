"""Fashion classification + export for USA fashion discovery (new stores not in the master directory).

  python3 -m mktecom.fashion_classify [--out ../fashion/usa_parts]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from collections import Counter

DB = os.environ.get("MKT_ECOM_DB", "data/usa_ecom.sqlite")

APP = re.compile(
    r"\b(clothing|clothes|apparel|fashion|dress(?:es)?|shirts?|t-?shirts?|tees?|tops?|blouses?|sweaters?|sweatshirts?|hoodies?|"
    r"jeans|denim|pants|trousers|shorts|skirts?|leggings?|jackets?|coats?|outerwear|swimwear|swimsuits?|bikinis?|lingerie|"
    r"underwear|bras?|panties|loungewear|sleepwear|pajamas?|activewear|athleisure|streetwear|workwear|menswear|womenswear|"
    r"suits?|blazers?|gowns?|jumpsuits?|rompers?|knitwear|cardigans?|polos?|joggers|scrubs|uniforms?|wardrobe|outfits?|abayas?|apparel)\b", re.I)
NONAPP = re.compile(
    r"\b(shoes?|sneakers?|boots?|sandals?|footwear|jewelry|jewellery|necklaces?|earrings?|rings?|watches|handbags?|bags?|purses?|"
    r"wallets?|furniture|mattress(?:es)?|sofas?|kitchen|decor|beauty|skincare|makeup|cosmetics|supplements?|electronics|"
    r"toys?|pets?|dog|garden|tools?|software|books?|candles?|sunglasses|eyewear|hats?|caps?|socks)\b", re.I)
WOMEN = re.compile(r"\b(women'?s?|womens|woman|ladies|lady|her|girls?|female|dresses|lingerie|bras?|skirts?|blouses?|maternity|bikinis?)\b", re.I)
MEN = re.compile(r"\b(men'?s?|mens|man|gentlemen|guys?|him|male|menswear|boys?)\b", re.I)
KIDS = re.compile(r"\b(kids?|baby|babies|toddlers?|infants?|children|newborn)\b", re.I)
UNI = re.compile(r"\b(unisex|gender[- ]neutral|all[- ]gender|for everyone|for all)\b", re.I)
WOM_ONLY_WORDS = re.compile(r"\b(dresses|lingerie|bras?|skirts?|blouses?|bikinis?|maternity|boutique)\b", re.I)


def classify(name: str, category: str, cat_text: str, url: str = ""):
    t = cat_text or ""
    head = " ".join((t.split("\x1f") + [""] * 3)[:3]) + " " + (name or "")
    body = t
    a_head = len(APP.findall(head))
    a = len(APP.findall(body))
    n = len(NONAPP.findall(body))
    n_head = len(NONAPP.findall(head))
    cat_fash = bool(re.search(r"Apparel|Fashion", category or ""))
    kids = len(KIDS.findall(head))
    w = len(re.findall(r"women'?s?|womens|ladies|female|her\b|dresses|lingerie|bikini|maternity|skirt", body, re.I))
    m = len(re.findall(r"\bmen'?s?\b|\bmens\b|menswear|\bguys?\b|\bmale\b|\bhim\b", body, re.I))
    uni = bool(UNI.search(body))
    if kids >= 2 and a_head < 3 and not re.search(r"women|men\b|adult", head, re.I):
        return None, None, "kids"
    if a < 3 and not cat_fash:
        return None, None, "no_apparel_signal"
    if n_head >= 2 and a_head == 0 and not cat_fash:
        return None, None, "non_apparel_focus"
    if cat_fash and a >= 2 and n <= a * 1.5:
        typ = "Fashion-only"
    elif a_head >= 1 and a >= 4 and n <= a:
        typ = "Fashion-only"
    elif a >= 4 and a_head >= 1:
        typ = "Has clothing section"
    else:
        return None, None, "weak_apparel"
    if w >= 2 * m + 1 and w >= 2:
        g = "Women"
    elif m >= 2 * w + 1 and m >= 2:
        g = "Men"
    else:
        g = "Unisex"
    return typ, g, "ok"


def nb(u):
    return re.sub(r"^https?://(www\.)?", "", u.lower()).rstrip("/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../fashion/usa_parts")
    ap.add_argument("--sources", default="fashion%")
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    master = set()
    with open("USA_Ecommerce_Master_Directory.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            master.add(nb(r["Root Domain / Storefront URL"]))
    rank = {}
    p = "data/raw/t.zip"
    if os.path.exists(p):
        for l in open(p):
            rk, d = l.strip().split(",")[:2]
            rank[d] = int(rk)
    ref = {r[0] for r in con.execute("select key from candidates where first_source in ('fashion_brands') or first_source like 'reference%'")}
    rows = con.execute(
        """select c.key,c.url,c.first_source,v.final_url,v.store_name,v.platform,v.category,v.status,v.reason,v.evidence_url,v.cat_text,v.method,c.status
           from candidates c join verifications v using(key)
           where (c.first_source like ? or c.priority>=5) and v.status in ('verified','verified_secondary_evidence','verified_manual_major')
           and c.key not in (select key from candidates where first_source not like 'fashion%' and status='verified' and 0)""", (a.sources,)).fetchall()
    out, stats, rej = [], Counter(), Counter()
    seen = set()
    for key, url, src, final, name, plat, cat, st, reason, ev, ct, meth, cst in rows:
        site = (final or url).rstrip("/")
        if re.match(r"https?://[^/]+/.+", site) and not re.search(r"/(us|en[-_]us|usa|market-us)(/|$)", site, re.I):
            site = re.match(r"https?://[^/]+", site).group(0)
        base = re.sub(r"^https?://(www\.)?", "", site.lower()).split("/")[0]
        if nb(site) in master or base in master or base in seen:
            rej["already_in_master"] += 1
            continue
        typ, g, why = classify(name, cat, ct or "", site)
        if not typ:
            rej[why] += 1
            continue
        seen.add(base)
        rk = rank.get(base, None)
        if key in ref and rk and rk <= 30000 or (rk and rk <= 8000):
            tier = "Brand-Major"
        elif rk and rk <= 60000:
            tier = "Large"
        elif rk and rk <= 250000:
            tier = "Medium"
        else:
            tier = "Small"
        vs = {"verified": "Verified", "verified_secondary_evidence": "Verified (secondary evidence)",
              "verified_manual_major": "Known major retailer – manually accepted"}[st]
        srcname = {"fashion_brands": "Brand portfolios / curated apparel brands", "fashion_wikidata": "Wikidata clothing brands/retailers",
                   "fashion_tranco_kw": "Tranco fashion-keyword domains", "fashion_appstore": "US App Store fashion apps"}.get(src, "Unverified-candidate re-verification")
        out.append([name or base, site + "/", typ, g, plat or "", tier, vs, ev or site, srcname])
        stats[(typ, g)] += 1
    os.makedirs(a.out, exist_ok=True)
    out.sort(key=lambda r: (r[5] != "Brand-Major", r[0].lower()))
    with open(os.path.join(a.out, "usa_fashion_discovery.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Store Name", "Website", "Type", "Gender", "Platform", "Size Tier", "Verification Status", "Evidence URL", "Source"])
        w.writerows(out)
    summ = {"total_added": len(out), "by_type": dict(Counter(r[2] for r in out)), "by_gender": dict(Counter(r[3] for r in out)),
            "by_size_tier": dict(Counter(r[5] for r in out)), "by_source": dict(Counter(r[8] for r in out)),
            "by_verification": dict(Counter(r[6] for r in out)), "excluded_reasons": dict(rej)}
    json.dump(summ, open(os.path.join(a.out, "usa_fashion_discovery_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
