"""Merge pass: gender from collection handles / product_type / tags; rescued stores; CSV + summary.

  python3 -m mktecom.fashion_final
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from collections import Counter

from .fashion_classify import BAD, BAD_NAME, KIDS, MANUAL_META, classify, nb
from .fashion_rescue import APP_T, MEN_T, NON_APP_T, UNI_T, WOMEN_T, tokens

OUT = "../fashion/usa_parts"
SOFT_W = {"dresses", "dress", "skirts", "skirt", "gowns", "gown", "blouses", "lingerie", "bras", "bra", "bikinis", "bikini", "maternity", "bridal", "heels", "leggings", "rompers", "jumpsuits"}
SOFT_M = {"ties", "tie", "tuxedos", "tuxedo", "boxers", "trunks", "beard", "cufflinks"}
KID_T = {"kids", "kid", "baby", "babies", "toddler", "toddlers", "infant", "newborn", "children", "youth"}


def gender_from(d: dict) -> tuple[str | None, str]:
    strings = list(d.get("navslugs", [])) + list(d.get("types", [])) + list(d.get("tags", []))
    w = m = u = sw = sm = 0
    for s in strings:
        tk = set(tokens(str(s)))
        hw, hm = bool(tk & WOMEN_T), bool(tk & MEN_T)
        if hw and not hm:
            w += 1
        elif hm and not hw:
            m += 1
        elif hw and hm:
            u += 1
        if tk & UNI_T:
            u += 1
        if tk & SOFT_W:
            sw += 1
        if tk & SOFT_M:
            sm += 1
    info = f"w{w}/m{m}/u{u}/sw{sw}"
    if w + m == 0:
        if sw >= 2 and sm == 0:
            return "Women", info
        if sm >= 2 and sw == 0:
            return "Men", info
        return None, info
    if w >= 2 * m and w >= 1:
        return "Women", info
    if m >= 2 * w and m >= 1:
        return "Men", info
    return "Unisex", info


QA_EXCLUDE = {"thenewblack.ai", "tealwindowboutique.com", "reformclothing.com", "lifestylessports.com", "tanner.rawlings.com", "ghost-holdings.wixsite.com",
              "kingsplayshop.com", "jeshirt.bigcartel.com", "shopinfinite.net", "onenessboutique.com", "levelwear.com", "us.levelwear.com", "aggielandoutfitters.com",
              "authenticbandmerch.com", "varsityfangear.com", "barefootcampusoutfitter.com", "spoiledsweetboutique.com"}
QA_GENDER = {"wardrobe.nyc": "Women", "catofashions.com": "Women", "justmeapparel.com": "Unisex", "catworkwear.com": "Unisex", "poetryfashion.com": "Unisex"}


def head_gender(name: str, ct: str, base: str) -> str:
    parts = (ct or "").split("\x1f")
    head = " ".join([name or "", base] + parts[:2])[:700]
    w = len(re.findall(r"women'?s?\b|womens|womenswear|ladies|\bfor her\b|\bgirls?\b", head, re.I))
    m = len(re.findall(r"(?<!wo)\bmen'?s?\b|\bmens\b|menswear|\bfor him\b|\bguys?\b|\bgentlem[ae]n\b", head, re.I))
    soft = len(re.findall(r"boutique|prom\b|bridal|wedding dress|dresses|gowns?|bikinis?|lingerie|swimwear|couture", head, re.I))
    if w > m or (w == 0 and m == 0 and soft):
        return "Women" if (m == 0 or w >= 2 * m) else "Unisex"
    if m > w and w == 0:
        return "Men"
    return "Unisex"


def clean(d: dict) -> dict:
    d = dict(d)
    d["navslugs"] = [x for x in d.get("navslugs", []) if x and not re.search(r"\.(css|js|woff2?|pdf|png|jpg|svg)$", x, re.I)]
    return d


def type_from(d: dict):
    labels = [str(x) for x in d.get("types", []) if str(x).strip()] or [str(x) for x in d.get("navslugs", []) if str(x).strip()]
    if len(labels) < 3:
        return None
    a = sum(1 for x in labels if APP_T.search(x.replace("-", " ")) and not NON_APP_T.search(x.replace("-", " ")))
    n = sum(1 for x in labels if NON_APP_T.search(x.replace("-", " ")))
    kids = sum(1 for x in labels if set(tokens(x)) & KID_T)
    if kids >= len(labels) * 0.5 and not any(set(tokens(x)) & (WOMEN_T | MEN_T) for x in labels):
        return "kids"
    r = a / len(labels)
    if r >= 0.5 and n <= a:
        return "Fashion-only"
    if r >= 0.2 and a >= 3:
        return "Has clothing section"
    return "none"


def main():
    con = sqlite3.connect("data/usa_ecom.sqlite")
    master = set()
    with open("USA_Ecommerce_Master_Directory.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            master.add(nb(r["Root Domain / Storefront URL"]))
    cur = list(csv.DictReader(open(os.path.join(OUT, "usa_fashion_discovery.csv"), encoding="utf-8")))
    cur = [r for r in cur if r["Source"] != "Unverified-candidate rescue (platform probes)"]
    probe_cur = {k: json.loads(d) for k, v, d, t in con.execute("select * from rescue_cur")}
    rows, ginfo = [], Counter()
    seen = set()
    for r in cur:
        base = nb(r["Website"]).split("/")[0]
        d = probe_cur.get(base)
        g, info = gender_from(clean(d)) if d else (None, "noprobe")
        if g is None:
            vr = con.execute("select store_name,cat_text from verifications where key=?", (base,)).fetchone() or (r["Store Name"], "")
            g = MANUAL_META[base][1] if base in MANUAL_META else head_gender(vr[0] or r["Store Name"], vr[1], base)
            ginfo["head_text_gender"] += 1
        else:
            ginfo["probe_gender"] += 1
        r = dict(r)
        r["Gender"] = g
        rows.append(r)
        seen.add(base)
    rescued = Counter()
    for key, verdict, data, ts in con.execute("select * from rescue where verdict='accepted'"):
        d = clean(json.loads(data))
        base = nb(d["origin"]).split("/")[0]
        if base in master or base in seen or nb(d["origin"]) in master:
            rescued["already_in_master_or_dup"] += 1
            continue
        v = con.execute("select store_name,platform,category,cat_text,final_url from verifications where key=?", (key,)).fetchone()
        name, plat, cat, ct, final = v
        if BAD.search((ct or "")[:4000]) or BAD_NAME.search((name or "") + " " + base):
            rescued["b2b_custom_or_nonstore"] += 1
            continue
        if re.search(r"\.(org|ai|edu|gov)$|demo|store-[a-z0-9]{8,}|\.mybigcommerce\.com$", base):
            rescued["excluded_nonstore_domain"] += 1
            continue
        typ = type_from(d)
        typ_t, g_t, why_t = classify(name, cat, ct or "", d["origin"])
        kwn = re.search(r"cloth|apparel|wear|shirt|tee|jean|denim|dress|suit|pajama|swim|boutique|leather|athleisure|jacket|outfit|fashion|couture|thread|uniform|lingerie|underwear|hoodie", (name or "") + " " + base, re.I)
        if re.search(r"\b(UK|México|Mexico|Canada|Australia)\b|custom t-?shirts|bnb|fine art", name or "", re.I) or re.search(r"autosport|equipment", base):
            rescued["excluded_foreign_or_custom_or_nonfashion_name"] += 1
            continue
        if typ_t is None and not kwn or typ != "Fashion-only" and typ_t is None or typ == "Fashion-only" and why_t in ("non_apparel_focus", "kids", "b2b_custom_or_nonstore"):
            rescued["excluded_text_disagrees_" + why_t] += 1
            continue
        if typ in ("kids", "none"):
            rescued["excluded_" + typ] += 1
            continue
        if typ is None:
            typ = typ_t
        g, info = gender_from(d)
        if g is None:
            g = head_gender(name, ct, base)
        plat_out = (d.get("platform") or plat or "").title()
        ev = d["origin"] + ("/meta.json" if d.get("platform") == "shopify" else "/wp-json/wc/store/v1/products" if d.get("platform") == "woocommerce" else "/")
        evtxt = "Verified (platform probe: purchase path + USD + " + "/".join(d["us"]) + ")"
        rows.append({"Store Name": name or base, "Website": d["origin"] + "/", "Type": typ, "Gender": g, "Platform": plat_out, "Size Tier": "Small",
                     "Verification Status": evtxt, "Evidence URL": ev, "Source": "Unverified-candidate rescue (platform probes)"})
        seen.add(base)
        rescued["added"] += 1
    rows = [r for r in rows if nb(r["Website"]).split("/")[0] not in QA_EXCLUDE]
    for r in rows:
        r["Gender"] = QA_GENDER.get(nb(r["Website"]).split("/")[0], r["Gender"])
    rows.sort(key=lambda r: (r["Size Tier"] != "Brand-Major", r["Store Name"].lower()))
    cols = ["Store Name", "Website", "Type", "Gender", "Platform", "Size Tier", "Verification Status", "Evidence URL", "Source"]
    with open(os.path.join(OUT, "usa_fashion_discovery.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    sp = os.path.join(OUT, "usa_fashion_discovery_summary.json")
    s = json.load(open(sp))
    s.update({"total_added": len(rows), "by_type": dict(Counter(r["Type"] for r in rows)), "by_gender": dict(Counter(r["Gender"] for r in rows)),
              "by_size_tier": dict(Counter(r["Size Tier"] for r in rows)), "by_source": dict(Counter(r["Source"] for r in rows)),
              "by_verification": dict(Counter(r["Verification Status"].split(" (platform")[0] if "platform probe" in r["Verification Status"] else r["Verification Status"] for r in rows)),
              "pass2": {"rescue": dict(rescued), "gender_basis": dict(ginfo)}})
    json.dump(s, open(sp, "w"), indent=1)
    print(json.dumps(s["pass2"]), len(rows), s["by_gender"], s["by_type"])


if __name__ == "__main__":
    main()
