"""Final merge: import the USA shard CSVs into the main DB, normalize identity, deduplicate, resolve status conflicts.

  python3 -m mktecom.merge_shards            # idempotent: re-running re-imports shard rows (INSERT OR REPLACE by key)

Identity: registrable root (or merchant-specific host for platform-hosted stores such as *.myshopify.com), computed with
common.identity. Shop/merch subdomains of a brand (shop.<brand>.com) collapse into the brand root and are named after the brand.
Conflict rule (per identity group, all sources incl. the main pipeline):
  1. a hard rejection (marketplace / service / digital / SaaS / media / adult / gambling / charity / no physical products
     with a sample of >=5 products) beats every verify except a main-pipeline primary verify with strength >= WEAK;
  2. otherwise the strongest verified row wins (primary > secondary; more US/purchase evidence wins; main pipeline > shards on ties);
  3. otherwise unverified beats rejected, rejected beats nothing.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from . import db
from .common import identity, MARKETPLACE_ROOTS, registrable_domain

csv.field_size_limit(10**9)
HERE = os.path.dirname(__file__)
SHARDS = os.path.join(HERE, "..", "shards")
SHARD_FILES = {
    "shard_shopify": "usa_shopify.csv",
    "shard_other_platforms": "usa_other_platforms.csv",
    "shard_tranco_200k_500k": "usa_tranco_200k_500k.csv",
    "shard_tranco_500k_1m": "usa_tranco_500k_1m.csv",
}
VERIFIED = ("verified", "verified_secondary_evidence")
HARD_REJECT = re.compile(
    r"marketplace|aggregator|services?\b|saas|digital|media/organisation|organisation|adult|gambling|"
    r"restaurant|charity|no_physical|not physical|non.?store|corporate|agency", re.I)
LOW_CONF_REJECT = re.compile(r"\(0/[1-4] products|products are services/tickets", re.I)
WEAK = 118

SHOP_SUBS = {"shop", "store", "shopping", "merch", "merchandise", "shop-us", "us-shop", "usshop", "shopus", "store-us", "webstore", "estore", "eshop"}

CATEGORY_RULES = [
    ("Firearms, Hunting & Tactical", r"firearm|tactical|hunting|ammo|gun"),
    ("Vape, Smoke & CBD", r"vape|smoke|tobacco|cbd|cigar"),
    ("Jewelry & Watches", r"jewel|watch"),
    ("Shoes & Footwear", r"shoe|footwear|sneaker|boot"),
    ("Bags & Luggage", r"bag|luggage"),
    ("Eyewear", r"eyewear|glasses|optical"),
    ("Apparel & Fashion", r"apparel|fashion|clothing|wear|streetwear|sportswear|activewear|swim|lingerie"),
    ("Beauty & Personal Care", r"beauty|cosmetic|personal care|grooming|fragrance|perfume|skincare|hair"),
    ("Health, Supplements & Medical", r"health|wellness|pharmac|supplement|vitamin|medical|lab supplies"),
    ("Baby & Kids", r"baby|kids|maternity"),
    ("Toys, Games & Hobbies", r"toy|game|gaming|hobby|collectible|trading card"),
    ("Pet Supplies", r"\bpets?\b|pet supplies"),
    ("Food, Grocery & Beverages", r"food|grocery|beverage|coffee|tea\b|wine|beer|spirits|chocolate|candy|sweets|bak(?:ed|ery)|snack"),
    ("Flowers, Gifts & Party", r"flower|gift|party|seasonal|costume"),
    ("Home, Furniture & Decor", r"home|furniture|decor|bedding|mattress|kitchen|tableware|lighting|appliance|cleaning|household|bath|rug"),
    ("Garden, Agriculture & Outdoor Living", r"garden|agricultur|farm|outdoor living"),
    ("Tools, Hardware & Building", r"tool|hardware|industrial|building|improvement|electrical|packaging|shipping supplies|business supplies|wholesale|b2b"),
    ("Automotive, Marine & Powersports", r"automotive|auto|powersports|marine|\brv\b|tires|wheels|bikes|micromobility|motorcycle"),
    ("Electronics & Computers", r"electronic|computer|mobile|phone|audio|component"),
    ("Sports, Fitness & Outdoor", r"sport|fitness|outdoor|camping"),
    ("Books, Media & Stationery", r"book|media|music|stationery|office|school|art\b|prints|craft|sewing"),
    ("Musical Instruments & Gear", r"instrument"),
    ("Religious & Spiritual", r"religio|spiritual"),
]
CATEGORY_RULES_C = [(n, re.compile(p, re.I)) for n, p in CATEGORY_RULES]


def unify_category(cat):
    c = (cat or "").strip()
    if not c or c.lower().startswith("general / unclass"):
        return "General Merchandise / Unclassified"
    if re.search(r"general merchandise|department store", c, re.I):
        return "General Merchandise / Unclassified"
    if re.search(r"arts?, crafts|arts & crafts|art, prints", c, re.I):
        return "Arts, Crafts & Collectibles"
    if re.search(r"musical|music & instruments|instrument", c, re.I):
        return "Musical Instruments & Gear"
    for name, rx in CATEGORY_RULES_C:
        if rx.search(c):
            return name
    return "General Merchandise / Unclassified"


def strength(status, evidence_text, reason, source_rank):
    s = 100 if status == "verified" else 50
    ev = (evidence_text or "")
    n = len(re.findall(r"[a-z_]+\s*[=:]", ev)) if ev else 0
    if ev.startswith("{"):
        try:
            n = len(json.loads(ev))
        except ValueError:
            pass
    s += min(n, 5) * 4
    r = (reason or "").lower()
    if re.search(r"physical|requires_shipping|purchasable|product page", r):
        s += 6
    if re.search(r"add-to-cart|cart/checkout|purchase", r):
        s += 4
    return s + source_rank * 0.5


def host_of(url):
    return (urlsplit(url).hostname or "").lower()


def is_shop_sub(url, root):
    h = re.sub(r"^www\d?\.", "", host_of(url))
    if not h or h == root or not h.endswith("." + root):
        return False
    return h[: -len(root) - 1] in SHOP_SUBS


def brand_label(root):
    lab = root.split(".")[0]
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", lab) if w)


def load_shards():
    for source, fn in SHARD_FILES.items():
        with open(os.path.join(SHARDS, fn), newline="") as f:
            for r in csv.DictReader(f):
                yield source, r


def main():
    con = db.connect()
    con.execute("PRAGMA synchronous=OFF")
    con.execute("CREATE TABLE IF NOT EXISTS merge_log(grp TEXT, kind TEXT, detail TEXT)")
    con.execute("DELETE FROM merge_log")
    con.execute("CREATE TABLE IF NOT EXISTS group_sources(grp TEXT, source TEXT, status TEXT, winner INTEGER)")
    con.execute("DELETE FROM group_sources")
    stats = Counter()

    # --- gather rows ----------------------------------------------------------------------------------------------
    rows = []  # dicts: grp, source, status, strength, name, url, platform, category, evidence, reason, evurl, ts, key
    main_rows = con.execute(
        """SELECT v.key, coalesce(v.final_key, v.key), coalesce(v.final_url, c.url), v.store_name, v.platform, v.category, v.status,
                  v.market_evidence, v.reason, v.evidence_url, v.verified_at, c.first_source, v.product_evidence, v.market_score,
                  c.root_domain, c.url
           FROM verifications v JOIN candidates c USING(key) WHERE v.key NOT IN (SELECT key FROM verifications WHERE method='shard')""").fetchall()
    for (key, fkey, furl, name, plat, cat, st, mev, reason, evurl, ts, fsrc, prod, score, root, curl) in main_rows:
        if st not in VERIFIED + ("rejected", "unverified"):
            continue
        rows.append(dict(grp=fkey or key, key=key, source="main", status=st, name=name or "", url=furl or curl, platform=plat or "",
                         category=cat or "", evidence=mev or "", reason=reason or "", evurl=prod or evurl or "", ts=ts or "",
                         root=root or "", first_source=fsrc or "", rank=2, score=score))
    stats["main_rows"] = len(rows)

    for source, r in load_shards():
        stats[f"in:{source}"] += 1
        url = r["canonical_storefront_url"] or ""
        ident = identity(url) or identity(r["root_domain"])
        if not ident:
            stats[f"no_identity:{source}"] += 1
            continue
        status = r["status"]
        reason = r["reason"]
        root = ident["root_domain"]
        if (root in MARKETPLACE_ROOTS or registrable_domain(host_of(url)) in MARKETPLACE_ROOTS) and status in VERIFIED:
            status, reason = "rejected", "marketplace/aggregator (merge scope rule): " + reason
        rows.append(dict(grp=ident["key"], key=ident["key"], source=source, status=status, name=r["store_name"], url=url,
                         platform=r["platform"], category=r["category"], evidence=r["us_evidence"], reason=reason,
                         evurl=r["verification_url"], ts=r["verification_utc"], root=root,
                         first_source=r["discovery_source"] + f"|rank={r['tranco_rank']}", rank=1, score=None))
    # --- group ----------------------------------------------------------------------------------------------------
    groups = defaultdict(list)
    for r in rows:
        groups[r["grp"]].append(r)
    # merge groups that share a shopify store id (main pipeline evidence) is already folded into final_key; also merge main
    # keys whose final_key equals a shard key through the shared grp value above.
    resolved = {}
    per_source_verified = Counter()
    source_overlap = Counter()
    dup_merged = 0
    for g, members in groups.items():
        dup_merged += len(members) - 1
        for m in members:
            m["strength"] = strength(m["status"], m["evidence"], m["reason"], m["rank"]) if m["status"] in VERIFIED else 0
        ver = sorted([m for m in members if m["status"] in VERIFIED], key=lambda m: -m["strength"])
        hard = [m for m in members if m["status"] == "rejected" and HARD_REJECT.search(m["reason"] or "") and not LOW_CONF_REJECT.search(m["reason"] or "")]
        if ver and hard and not (ver[0]["source"] == "main" and ver[0]["status"] == "verified" and ver[0]["strength"] >= WEAK):
            win = hard[0]
            decision = "hard_reject_over_weak_verify"
            con.execute("INSERT INTO merge_log VALUES(?,?,?)", (g, decision, f"{ver[0]['source']}:{ver[0]['status']}({ver[0]['strength']:.0f}) vs {hard[0]['source']}: {hard[0]['reason'][:100]}"))
            stats[decision] += 1
        elif ver:
            win = ver[0]
            others = {m["status"] for m in members if m is not win}
            if others - set(VERIFIED):
                stats["verified_over_reject_or_unverified"] += 1
            decision = "verified"
        else:
            mainrows = [m for m in members if m["source"] == "main"]
            unv = [m for m in members if m["status"] == "unverified"]
            win = mainrows[0] if mainrows else (unv[0] if unv else members[0])
            decision = win["status"]
        if len({m["source"] for m in members if m["status"] in VERIFIED}) > 1:
            stats["verified_in_multiple_sources"] += 1
        srcs = sorted({m["source"] for m in members})
        resolved[g] = (win, srcs, decision, members)

    # --- write ----------------------------------------------------------------------------------------------------
    con.execute("BEGIN IMMEDIATE")
    ts_now = db.now()
    ins_c = ins_v = 0
    for g, (win, srcs, decision, members) in resolved.items():
        con.executemany("INSERT INTO group_sources VALUES(?,?,?,?)", [(g, m["source"], m["status"], int(m is win)) for m in members])
        if all(m["source"] == "main" for m in members) and decision in ("verified", "unverified", "rejected") and len(members) == 1:
            continue
        root = win["root"] or registrable_domain(host_of(win["url"]))
        murl = win["url"]
        name = win["name"]
        if not name:
            name = next((m["name"] for m in members if m["name"]), "")
        if is_shop_sub(murl, root) and root in (g, root):
            name = next((m["name"] for m in members if m["source"] == "main" and m["name"] and not is_shop_sub(m["url"], root)), "") or brand_label(root)
            stats["shop_subdomain_relabeled"] += 1
        final_status = win["status"]
        for m in members:
            if m["source"] == "main":
                if m is win:
                    continue
                if m["status"] in VERIFIED and final_status not in VERIFIED:
                    con.execute("UPDATE verifications SET status='rejected', reason=? WHERE key=?", ("merge_conflict: " + win["reason"][:200], m["key"]))
                    con.execute("UPDATE candidates SET status='rejected' WHERE key=?", (m["key"],))
        key = g
        first_source = ", ".join(srcs)
        exists = con.execute("SELECT 1 FROM candidates WHERE key=?", (key,)).fetchone()
        if win["source"] == "main":
            for s in srcs:
                if s != "main":
                    con.execute("INSERT OR IGNORE INTO candidate_sources VALUES(?,?,?,?)", (win["key"], s, "", ts_now))
            continue
        mev = json.dumps({"shard_evidence": win["evidence"][:600]})
        if exists:
            con.execute("DELETE FROM verifications WHERE key=?", (key,))
        else:
            con.execute("INSERT INTO candidates(key,url,root_domain,platform_hint,first_source,source_detail,discovered_at,status,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                        (key, murl, root, win["platform"], win["source"], win["first_source"][:200], ts_now, "pending", -9))
            ins_c += 1
        con.execute("INSERT OR REPLACE INTO verifications(key, final_url, final_key, store_name, platform, category, market_evidence, status, reason, evidence_url, product_evidence, verified_at, method) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, murl, key, name, win["platform"], win["category"], mev, final_status, (win["reason"] or "")[:400], win["evurl"], win["evurl"], win["ts"], "shard"))
        con.execute("UPDATE candidates SET status=?, first_source=?, url=? WHERE key=?", (final_status if final_status in ("verified", "rejected", "unverified") else "verified", win["source"] if not exists else first_source, murl, key))
        for s in srcs:
            if s != "main":
                con.execute("INSERT OR IGNORE INTO candidate_sources VALUES(?,?,?,?)", (key, s, "", ts_now))
        ins_v += 1
    con.execute("COMMIT")
    print(json.dumps(dict(stats), indent=1))
    print("groups", len(groups), "rows", len(rows), "dup_merged", dup_merged, "inserted_candidates", ins_c, "verifications_written", ins_v)


if __name__ == "__main__":
    main()
