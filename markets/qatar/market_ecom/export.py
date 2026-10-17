"""Dedup pass + Excel/CSV export of the directory."""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

import pandas as pd

from . import db
from .common import identity
from .queries import NICHES, CITIES
from .verify import MARKET_GEO
from .market import M, WORK_DIR

OUT_DIR = WORK_DIR
XLSX = M.xlsx
CSV = M.csv
REF_CSV = os.path.join(OUT_DIR, "data", "reference_universe.csv")
PREVIOUS_CSV = None

PLATFORM_SHARED = {"salla.sa", "zid.store", "myshopify.com", "expandcart.com", "matjrah.store", "youcan.shop", "wuilt.com", "salla.store", "company.site", "wixsite.com"}


def master_url(row):
    final = row["final_url"] or row["url"]
    ident = identity(final) or identity(row["url"])
    if ident and ident["root_domain"] in PLATFORM_SHARED:
        return ident["url"].rstrip("/")
    if ident and "|" in ident["key"]:
        return ident["url"]
    sp = urlsplit(final)
    host = sp.hostname or ident["root_domain"]
    return f"https://{host}/"


def clean_name(name, url):
    n = (name or "").strip()
    n = re.sub(r"\s+", " ", n)
    n = n.strip(" \"'`“”‘’«»|-–—:،,.").strip()
    n = re.sub(r"^(?:متجر|store)\s*[:\-|]\s*", "", n, flags=re.I)
    if not n or n.startswith("salla.sa/") or len(n) < 2:
        host = urlsplit(url).hostname or url
        n = host.replace("www.", "")
    return n[:120]


def json_obj(ev):
    if not isinstance(ev, str) or not ev.strip():
        return {}
    try:
        out = json.loads(ev)
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def store_identity_ids(ev):
    e = json_obj(ev)
    if not e and not isinstance(ev, str):
        return None
    p = e.get("probe") or {}
    if p.get("store_id"):
        return f"salla_store_id:{p['store_id']}"
    if p.get("myshopify_domain"):
        return f"shopify:{p['myshopify_domain']}"
    return None


def dedup(con):
    rows = con.execute(
        "SELECT v.key, v.final_key, v.final_url, v.ecom_evidence, c.url, c.platform_hint FROM verifications v JOIN candidates c USING(key) WHERE v.status IN ('verified','verified_secondary_evidence')"
    ).fetchall()
    groups = defaultdict(list)
    for key, fkey, furl, ev, url, ph in rows:
        gid = store_identity_ids(ev) or fkey or key
        groups[gid].append((key, fkey, furl, url, ph))
    # second-level union: final_key groups that share a store id
    rep_of = {}
    for gid, members in groups.items():
        # prefer the member whose key equals the final key (custom domain), then non-platform keys
        members.sort(key=lambda m: (not MARKET_GEO.search(m[2] or ""), m[0] != m[1], m[4] is not None, len(m[0])))
        rep = members[0][0]
        for m in members:
            rep_of[m[0]] = rep
    # final-key collisions across different gids
    by_final = defaultdict(set)
    for gid, members in groups.items():
        for m in members:
            if m[1]:
                by_final[m[1]].add(rep_of[m[0]])
    for fk, reps in by_final.items():
        if len(reps) > 1:
            keep = sorted(reps, key=lambda r: (r != fk, len(r)))[0]
            for k, r in list(rep_of.items()):
                if r in reps:
                    rep_of[k] = keep
    dups = [(rep, k) for k, rep in rep_of.items() if rep != k]
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE verifications SET duplicate_of=NULL WHERE status IN ('verified','verified_secondary_evidence')")
    con.executemany("UPDATE verifications SET duplicate_of=? WHERE key=?", dups)
    con.executemany("UPDATE candidates SET status='duplicate' WHERE key=?", [(k,) for _, k in dups])
    con.executemany("UPDATE candidates SET status='verified' WHERE key=?", [(k,) for k in set(rep_of.values())])
    con.execute("COMMIT")
    return len(dups)


def fmt_market(ev):
    e = json_obj(ev)
    if not e and not isinstance(ev, str):
        return ""
    parts = []
    lab = {"cctld": f".{M.tld} domain", "market_locale": f"{M.country} locale path/subdomain/hreflang (en-{M.code}/ar-{M.code})",
           "currency_code": f"{M.currency} currency in store config", "local_prices": f"{M.currency} prices on page",
           "local_phone": f"+{M.phone_cc} phone", "commercial_registration": "CR no.", "market_places": f"{M.country} cities/areas/malls",
           "local_payment_shipping": "local payment/delivery", "shopify_shop_country": "Shopify shop country",
           "shopify_base_currency": "Shopify base currency", "other_currency": "other currency", "woo_store_currency": "WooCommerce currency"}
    for k, v in e.items():
        if v is True:
            parts.append(lab.get(k, k))
        elif isinstance(v, list):
            parts.append(f"{lab.get(k, k)}: {', '.join(map(str, v))}")
        else:
            parts.append(f"{lab.get(k, k)}: {v}")
    return "; ".join(parts)


REVIEW_TSV = os.path.join(os.path.dirname(__file__), "data", "manual_review.tsv")
REVIEW_STATUS = {"reject": "rejected", "unverified": "unverified", "name": None}


def apply_manual_review(con):
    """Human QA decisions (key, decision, value/reason): override verifier status or fix a store name; re-applied on every export."""
    if not os.path.exists(REVIEW_TSV):
        return 0
    n = 0
    with open(REVIEW_TSV, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            key, decision, text = (line.rstrip("\n").split("\t") + ["", ""])[:3]
            if decision == "name":
                con.execute("UPDATE verifications SET store_name=? WHERE key=?", (text, key))
            elif decision in REVIEW_STATUS:
                st = REVIEW_STATUS[decision]
                con.execute("UPDATE verifications SET status=?, reason=?, method='manual_review' WHERE key=? AND status IN ('verified','verified_secondary_evidence')",
                            (st, "manual_review: " + text, key))
                if con.execute("SELECT changes()").fetchone()[0]:
                    con.execute("UPDATE candidates SET status=? WHERE key=?", (st, key))
            n += 1
    con.commit()
    return n


def main():
    con = db.connect()
    apply_manual_review(con)
    ndup = dedup(con)
    v = pd.read_sql_query(
        """SELECT v.*, c.url, c.root_domain, c.first_source, c.source_detail, c.platform_hint,
                  (SELECT group_concat(source, ', ') FROM candidate_sources s WHERE s.key=v.key) AS all_sources
           FROM verifications v JOIN candidates c USING(key)""", con)
    ver = v[(v.status.isin(["verified", "verified_secondary_evidence"])) & (v.duplicate_of.isna())].copy()
    ver["Master URL"] = ver.apply(master_url, axis=1)
    ver["Store Name"] = [clean_name(n, u) for n, u in zip(ver.store_name, ver["Master URL"])]
    ver["Registrable Root Domain"] = [
        (identity(u) or {}).get("root_domain") or r for u, r in zip(ver.final_url.fillna(ver.url), ver.root_domain)]
    ver = ver.drop_duplicates("Master URL").sort_values(["Store Name"], key=lambda s: s.str.lower())

    master = ver[["Store Name", "Master URL"]].rename(columns={"Master URL": "Root Domain / Storefront URL"})

    def notes(r):
        n = []
        if r.final_key and r.final_key != r.key:
            n.append(f"discovered as {r.key}, resolves to {r.final_url}")
        if r.subcategory:
            n.append(f"secondary category: {r.subcategory}")
        e = json_obj(r.ecom_evidence)
        if e:
            n.append("product evidence: " + "; ".join(e.get("product_evidence") or []))
            n.append("purchase evidence: " + "; ".join(e.get("purchase_evidence") or []))
        if r.reason and r.reason != "ecommerce+market evidence ok":
            n.append(r.reason)
        return " | ".join(x for x in n if x)

    evidence = pd.DataFrame({
        "Store Name": ver["Store Name"],
        "Canonical Storefront URL": ver["Master URL"],
        "Registrable Root Domain": ver["Registrable Root Domain"],
        "Platform": ver.platform,
        "Industry / Category": ver.category,
        "Market Relevance Evidence": ver.market_evidence.map(fmt_market),
        "Market Score": ver.market_score,
        "Verification Source URL": ver.final_url,
        "Product Evidence URL": ver.product_evidence,
        "Verification Date (UTC)": ver.verified_at,
        "Status": ver.status,
        "Discovery Source": ver.all_sources.fillna(ver.first_source),
        "Notes": ver.apply(notes, axis=1),
    })

    unv = v[v.status.isin(["unverified", "rejected"])].copy()
    unv = unv.sort_values(["status", "reason"], ascending=[False, True])
    unverified = pd.DataFrame({
        "Candidate URL": unv.url,
        "Final URL": unv.final_url,
        "Status": unv.status,
        "Reason": unv.reason,
        "Platform (detected)": unv.platform,
        "Name (if detected)": unv.store_name,
        "Market Score": unv.market_score,
        "Checked At (UTC)": unv.verified_at,
        "Discovery Source": unv.first_source,
    })
    pending = pd.read_sql_query("SELECT url AS 'Candidate URL', status AS Status, first_source AS 'Discovery Source' FROM candidates WHERE status IN ('pending','in_progress')", con)
    if len(pending):
        pending["Reason"] = "not yet checked (queue not exhausted when exported)"
        unverified = pd.concat([unverified, pending], ignore_index=True)

    cov = coverage(con, ver, v, ndup)
    from . import reference
    rcon = reference.connect()
    ref_rows = reference.audit(rcon, PREVIOUS_CSV)
    ref_df = pd.DataFrame(ref_rows)
    audit_df = ref_df[ref_df.kind.isin(["brand", "mall"])] if len(ref_df) else ref_df
    audit_df = pd.concat([audit_df, ref_df[~ref_df.kind.isin(["brand", "mall"]) & ref_df.status.str.startswith("in_directory")]], ignore_index=True) if len(ref_df) else ref_df
    audit_sheet = pd.DataFrame({
        "Reference Store": audit_df.name, "Tier": audit_df.tier, "Category": audit_df.category,
        "Reference Source(s)": audit_df.sources, "Tranco Rank": audit_df.tranco_rank,
        "Coverage Status": audit_df.status, "Storefront URL": audit_df.url, "Reason": audit_df.reason,
        "Evidence": audit_df.evidence, "Known Domains": audit_df.domains,
    }).sort_values(["Coverage Status", "Tier", "Reference Store"]) if len(audit_df) else pd.DataFrame()
    ref_df.to_csv(REF_CSV, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(XLSX, engine="openpyxl") as xw:
        master.to_excel(xw, sheet_name="Master Directory", index=False)
        evidence.to_excel(xw, sheet_name="Verification Evidence", index=False)
        unverified.to_excel(xw, sheet_name="Unverified Candidates", index=False)
        audit_sheet.to_excel(xw, sheet_name="Major Retailer Coverage Audit", index=False)
        startrow = 0
        for title, df in cov:
            pd.DataFrame({title: []}).to_excel(xw, sheet_name="Research Coverage", index=False, startrow=startrow)
            df.to_excel(xw, sheet_name="Research Coverage", index=False, startrow=startrow + 1)
            startrow += len(df) + 4
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = min(max(len(str(c.value or "")) for c in list(col)[:300]) + 2, 70)
                ws.column_dimensions[col[0].column_letter].width = max(width, 12)
    master.to_csv(CSV, index=False, encoding="utf-8-sig")
    print(f"exported: verified={len(master)} duplicates_merged={ndup} unverified_rows={len(unverified)} -> {XLSX}")
    return len(master)


GAPS = [
    "Bot-protected large retailers (Akamai/Cloudflare 403) stay Unverified unless two independent secondary proofs exist (archives, sitemaps, App Store); no challenge was bypassed.",
    "This VM is outside Qatar: global brands may geo-redirect or price in USD; Qatar paths (/en-qa, /qa-en, qa.) are probed explicitly but some geo-locked storefronts remain unresolved.",
    "Shopify's edge rate-limits this IP (HTTP 429) for storefront HTML; Shopify stores are verified from public meta.json/products.json when HTML is throttled.",
    "Search engines: Bing returns no organic results to this IP, Google is JS-gated, Brave 429, Mojeek/Ecosia/Qwant 403; DuckDuckGo Lite works intermittently with long backoffs, so long-tail search coverage is partial.",
    "Common Crawl / crt.sh / Tranco only see sites that were crawled, certified or ranked; small Instagram-first sellers without their own website are out of scope or missed.",
    "Category labels are keyword-based (Arabic + English) from title/meta/products; expect some misclassification.",
    "Expansion: more DDG query templates per niche/area once the engine stops throttling; Wayback CDX for *.qa when archive.org is back online; more mall directories (several are JS-only).",
]


def coverage(con, ver, v, ndup):
    q = lambda s: pd.read_sql_query(s, con)
    out = []
    totals = q("SELECT status AS 'Candidate status', count(*) AS Count FROM candidates GROUP BY 1 ORDER BY 2 DESC")
    totals.loc[len(totals)] = ["verified unique stores in Master Directory", len(ver)]
    totals.loc[len(totals)] = ["duplicates merged (aliases/redirects/same store id)", ndup]
    out.append(("Summary counts", totals))
    cat = ver.category.value_counts().rename_axis("Category").reset_index(name="Verified stores")
    known = {c for c, _ in []}
    out.append(("Verified stores by category", cat))
    plat = ver.platform.value_counts().rename_axis("Platform").reset_index(name="Verified stores")
    out.append(("Verified stores by platform", plat))
    cities = Counter()
    for ev in ver.market_evidence:
        for p in json_obj(ev).get("market_places", []):
            cities[p] += 1
    out.append(("Regions/cities mentioned on verified storefronts (multi-count)", pd.DataFrame(cities.most_common(), columns=["City/Region", "Stores mentioning"])))
    src = q("""SELECT s.source AS Source, count(*) AS Candidates, sum(c.status IN ('verified','duplicate')) AS 'Verified (incl. dup)',
                      sum(c.status='rejected') AS Rejected, sum(c.status='unverified') AS Unverified, sum(c.status IN ('pending','in_progress')) AS Pending
               FROM candidate_sources s JOIN candidates c USING(key) GROUP BY 1 ORDER BY 3 DESC""")
    out.append(("Discovery sources (a candidate may have several sources)", src))
    reg = q("SELECT source AS Source, type AS Type, description AS Description, status AS Status, notes AS Notes FROM sources")
    out.append(("Sources / directories registry", reg))
    qs = q("SELECT engine AS Engine, workstream AS Workstream, status AS Status, count(*) AS Queries, sum(n_results) AS Results, sum(n_new) AS 'New candidates' FROM queries GROUP BY 1,2,3 ORDER BY 1,4 DESC")
    out.append(("Searches performed (by engine and workstream)", qs))
    cc = q("SELECT substr(job, instr(job,'|')+1, instr(substr(job, instr(job,'|')+1),'|')-1) AS Pattern, count(*) AS 'Index pages fetched', sum(n) AS 'Keys seen', sum(n_new) AS 'New candidates' FROM jobs WHERE kind='cc' AND status='done' GROUP BY 1")
    out.append(("Common Crawl CDX harvesting", cc))
    workers = q("SELECT name AS Worker, kind AS Kind, concurrency AS Concurrency, started AS Started, heartbeat AS 'Last heartbeat', info AS 'Last stats' FROM workers")
    out.append(("Agent / worker utilization (tmux code workers sharing one SQLite DB; no AI subagents were spawned)", workers))
    reasons = q("SELECT status AS Status, substr(reason,1,70) AS Reason, count(*) AS Count FROM verifications WHERE status!='verified' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 40")
    out.append(("Top rejection / unverified reasons", reasons))
    niche_cats = sorted({c for c, _, _ in NICHES})
    gaps = pd.DataFrame({"Remaining gaps / expansion opportunities": GAPS})
    out.append(("Remaining gaps and expansion opportunities", gaps))
    return out


if __name__ == "__main__":
    main()
