"""Dedup pass + Excel/CSV export of the directory (market-parameterized).

  python3 -m mktecom.export
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

import pandas as pd

from . import db
from .common import identity, SHARED_SUBDOMAIN_PLATFORMS
from .market import M, US_STATES
from .verify import MARKET_GEO
from .merge_shards import unify_category

OUT_DIR = os.path.join(os.path.dirname(__file__), "..")
BASE = f"{M.prefix}_Ecommerce_Master_Directory"
XLSX = os.path.join(OUT_DIR, BASE + ".xlsx")
CSV = os.path.join(OUT_DIR, BASE + ".csv")
UNVERIFIED_CSV = os.path.join(OUT_DIR, "data", f"{M.prefix}_Unverified_Candidates.csv.gz")
EVIDENCE_CSV = os.path.join(OUT_DIR, "data", f"{M.prefix}_Verification_Evidence.csv")
REF_CSV = os.path.join(OUT_DIR, "data", f"{M.prefix}_reference_universe.csv")
XLSX_ROW_CAP = 1_000_000
UNVERIFIED_SHEET_CAP = 20_000


def master_url(row):
    final = row["final_url"] if isinstance(row["final_url"], str) and row["final_url"] else row["url"]
    ident = identity(final) or identity(row["url"])
    if not ident:
        return final
    if ident["root_domain"] in SHARED_SUBDOMAIN_PLATFORMS or "|" in ident["key"]:
        return ident["url"].rstrip("/") + ("/" if "|" in ident["key"] else "")
    host = urlsplit(final).hostname or ident["root_domain"]
    return f"https://{host}/"


def clean_name(name, url):
    n = re.sub(r"\s+", " ", (name or "").strip())
    n = n.strip(" \"'`“”‘’«»|-–—:,.").strip()
    if not n or len(n) < 2:
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
    p = json_obj(ev).get("probe") or {}
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
    rep_of = {}
    for gid, members in groups.items():
        members.sort(key=lambda m: (not MARKET_GEO.search(m[2] or ""), m[0] != m[1], m[4] is not None, len(m[0])))
        for m in members:
            rep_of[m[0]] = members[0][0]
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


LABELS = {"cctld": ".us domain", "locale": "en-US locale/path", f"currency_{M.currency}_code": f"{M.currency} currency in store config",
          "local_prices": "$ prices", "us_phone": "US phone (US area code)", "nanp_tollfree_phone": "US/CA toll-free phone",
          "us_address": "US street address/ZIP", "places": "US states/cities", "shipping_payment": "US shipping/payment/legal terms",
          "shopify_shop_country": "Shopify shop country", "shopify_base_currency": "Shopify base currency", "woo_store_currency": "WooCommerce currency"}


def fmt_market(ev):
    e = json_obj(ev)
    parts = []
    for k, v in e.items():
        if v is True:
            parts.append(LABELS.get(k, k))
        elif isinstance(v, list):
            parts.append(f"{LABELS.get(k, k)}: {', '.join(map(str, v))}")
        else:
            parts.append(f"{LABELS.get(k, k)}: {v}")
    return "; ".join(parts)


def main():
    con = db.connect()
    ndup = dedup(con)
    v = pd.read_sql_query(
        """SELECT v.*, c.url, c.root_domain, c.first_source, c.source_detail, c.platform_hint,
                  (SELECT group_concat(source, ', ') FROM candidate_sources s WHERE s.key=v.key) AS all_sources
           FROM verifications v JOIN candidates c USING(key)""", con)
    ver = v[(v.status.isin(["verified", "verified_secondary_evidence"])) & (v.duplicate_of.isna())].copy()
    ver["Master URL"] = ver.apply(master_url, axis=1)
    ver["Store Name"] = [clean_name(n, u) for n, u in zip(ver.store_name, ver["Master URL"])]
    ver["Registrable Root Domain"] = [(identity(u) or {}).get("root_domain") or r for u, r in zip(ver.final_url.fillna(ver.url), ver.root_domain)]
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
            n.append(r.reason[:600])
        return " | ".join(x for x in n if x)

    evidence = pd.DataFrame({
        "Store Name": ver["Store Name"],
        "Canonical Storefront URL": ver["Master URL"],
        "Registrable Root Domain": ver["Registrable Root Domain"],
        "Platform": ver.platform.fillna("").replace("", "unknown (secondary evidence)"),
        "Industry / Category": ver.category.map(unify_category),
        "Source Category": ver.category.fillna(""),
        "US Market-Relevance Evidence": ver.market_evidence.map(fmt_market),
        "Market Score": ver.market_score,
        "Verification Source URL": ver.final_url,
        "Product Evidence URL": ver.product_evidence,
        "Verification Date (UTC)": ver.verified_at,
        "Status": ver.status,
        "Discovery Source": ver.all_sources.fillna(ver.first_source),
        "Notes": ver.apply(notes, axis=1),
    })

    unv = v[v.status.isin(["unverified", "rejected"])].copy().sort_values(["status", "reason"], ascending=[False, True])
    unverified = pd.DataFrame({
        "Candidate URL": unv.url, "Final URL": unv.final_url, "Status": unv.status, "Reason": unv.reason,
        "Platform (detected)": unv.platform, "Name (if detected)": unv.store_name, "Market Score": unv.market_score,
        "Checked At (UTC)": unv.verified_at, "Discovery Source": unv.first_source,
    })
    pending = pd.read_sql_query("SELECT url AS 'Candidate URL', status AS Status, first_source AS 'Discovery Source' FROM candidates WHERE status IN ('pending','in_progress')", con)
    if len(pending):
        pending["Reason"] = "not yet checked (queue not exhausted when exported)"
        unverified = pd.concat([unverified, pending], ignore_index=True)
    # Unverified first in the sheet (most actionable), then pending, then rejected.
    order = {"unverified": 0, "pending": 1, "in_progress": 1, "rejected": 2}
    strong = unverified["Reason"].fillna("").str.match(r"^(blocked|rate_limited|js_rendered|partial|weak_ecommerce|insufficient_ecommerce|physical_goods_unclear|http_5|fetch_failed|verification_timeout|robots)")
    unverified = unverified.assign(_o=unverified["Status"].map(order).fillna(3) * 2 + (~strong).astype(int)).sort_values("_o", kind="stable").drop(columns="_o")
    unverified.to_csv(UNVERIFIED_CSV, index=False, compression="gzip")

    from . import reference
    rcon = reference.connect()
    ref_rows = reference.audit(rcon)
    ref_df = pd.DataFrame(ref_rows)
    if len(ref_df):
        ref_df.to_csv(REF_CSV, index=False)
        tier_order = {"huge": 0, "large": 1, "medium": 2, "recognized": 3}
        audit_df = ref_df[(ref_df.kind == "brand") | ref_df.status.str.startswith("in_directory") | ref_df.tier.isin(["large", "medium"])]
        md = pd.read_sql_query("SELECT name AS Store, rule AS 'Decision Rule', evidence AS 'Decision Evidence', decided_at AS 'Decision Date (UTC)' FROM major_decisions", con) if con.execute("SELECT 1 FROM sqlite_master WHERE name='major_decisions'").fetchone() else pd.DataFrame(columns=["Store", "Decision Rule", "Decision Evidence", "Decision Date (UTC)"])
        audit_sheet = pd.DataFrame({
            "Store": audit_df.name, "Tier": audit_df.tier, "Category": audit_df.category, "Reference Source(s)": audit_df.sources,
            "Tranco Rank": audit_df.tranco_rank, "Status": audit_df.status, "URL": audit_df.url, "Evidence": audit_df.evidence,
            "Reason": audit_df.reason,
        })
        audit_sheet = audit_sheet.merge(md.drop_duplicates("Store"), on="Store", how="left")
        audit_sheet = audit_sheet.assign(_t=audit_sheet.Tier.map(tier_order)).sort_values(["_t", "Status", "Store"]).drop(columns="_t")
    else:
        audit_sheet = pd.DataFrame()

    cov = coverage(con, ver, v, ndup, ref_df)
    evidence.to_csv(EVIDENCE_CSV, index=False)
    with pd.ExcelWriter(XLSX, engine="openpyxl") as xw:
        master.to_excel(xw, sheet_name="Master Directory", index=False)
        evidence.to_excel(xw, sheet_name="Verification Evidence", index=False)
        cap = unverified.head(UNVERIFIED_SHEET_CAP)
        if len(unverified) > UNVERIFIED_SHEET_CAP:
            cap = pd.concat([pd.DataFrame({"Candidate URL": [f"[sheet trimmed to the strongest {UNVERIFIED_SHEET_CAP:,} of {len(unverified):,} rows (unverified with blocked/partial/JS/insufficient-evidence reasons first); full list in markets/usa/data/{os.path.basename(UNVERIFIED_CSV)}]"]}), cap])
        cap.to_excel(xw, sheet_name="Unverified Candidates", index=False)
        startrow = 0
        for title, df in cov:
            pd.DataFrame({title: []}).to_excel(xw, sheet_name="Research Coverage", index=False, startrow=startrow)
            df.to_excel(xw, sheet_name="Research Coverage", index=False, startrow=startrow + 1)
            startrow += len(df) + 4
        audit_sheet.to_excel(xw, sheet_name="Major Retailer Coverage Audit", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = min(max(len(str(c.value or "")) for c in list(col)[:300]) + 2, 70)
                ws.column_dimensions[col[0].column_letter].width = max(width, 12)
    master.to_csv(CSV, index=False)
    print(f"exported: verified={len(master)} (primary={int((ver.status == 'verified').sum())}, secondary={int((ver.status == 'verified_secondary_evidence').sum())}) "
          f"duplicates_merged={ndup} unverified_rows={len(unverified)} -> {XLSX}")
    return len(master)


SOURCE_ORDER = ["main", "shard_shopify", "shard_other_platforms", "shard_tranco_200k_500k", "shard_tranco_500k_1m"]
SOURCE_LABEL = {"main": "USA main pipeline (Tranco 1-200k, reference universe, Wikidata)", "shard_shopify": "Shopify shard",
                "shard_other_platforms": "Other platforms shard (Square, Shift4Shop, Wix, Big Cartel, Woo, Ecwid, ...)",
                "shard_tranco_200k_500k": "Tranco 200k-500k shard", "shard_tranco_500k_1m": "Tranco 500k-1M shard"}


def shard_tables(con, ver):
    import glob
    gs = pd.read_sql_query("SELECT grp, source, status FROM group_sources", con)
    if gs.empty:
        return []
    final = set(ver.final_key.fillna(ver.key)) | set(ver.key)
    rows = []
    gs["final_verified"] = gs.grp.isin(final)
    ver_members = gs[gs.status.str.startswith("verified")]
    per_grp = ver_members.groupby("grp").source.apply(lambda x: sorted(set(x)))
    claim = {}
    for g, srcs in per_grp.items():
        if g in final:
            claim[g] = next(s for s in SOURCE_ORDER if s in srcs)
    claimed = pd.Series(claim).value_counts()
    for src in SOURCE_ORDER:
        sub = gs[gs.source == src]
        vm = ver_members[(ver_members.source == src) & ver_members.grp.isin(final)]
        excl = sum(1 for g, srcs in per_grp.items() if g in final and srcs == [src])
        rows.append({"Source": SOURCE_LABEL[src], "Rows imported (after identity normalization)": len(sub),
                     "Own verified rows": int(sub.status.str.startswith("verified").sum()),
                     "Own rejected": int((sub.status == "rejected").sum()), "Own unverified": int((sub.status == "unverified").sum()),
                     "Final verified stores this source verified (incl. overlap)": int(vm.grp.nunique()),
                     "Final verified stores claimed by this source (first-claim order: main, Shopify, Other platforms, 200k-500k, 500k-1M)": int(claimed.get(src, 0)),
                     "Final verified verified ONLY by this source": excl})
    t1 = pd.DataFrame(rows)
    sm = []
    for f in sorted(glob.glob(os.path.join(OUT_DIR, "shards", "*_summary.json"))):
        j = json.load(open(f))
        flat = {k: v for k, v in j.items() if isinstance(v, (int, float, str)) and k != "generated_utc"}
        sm.append(flat)
    t2 = pd.DataFrame(sm) if sm else pd.DataFrame()
    out = [("Per-shard / per-source contribution after merge and deduplication", t1)]
    if len(t2):
        out.append(("Shard run summaries (as reported by each shard branch)", t2))
    ml = pd.read_sql_query("SELECT kind AS 'Merge rule', count(*) AS Groups FROM merge_log GROUP BY 1", con)
    if len(ml):
        out.append(("Merge conflict resolutions (hard rejection beat weak verify)", ml))
    return out


def coverage(con, ver, v, ndup, ref_df):
    q = lambda s: pd.read_sql_query(s, con)
    out = []
    totals = q("SELECT status AS 'Candidate status', count(*) AS Count FROM candidates GROUP BY 1 ORDER BY 2 DESC")
    totals.loc[len(totals)] = ["verified unique stores in Master Directory", len(ver)]
    totals.loc[len(totals)] = ["  of which live-verified (primary)", int((ver.status == "verified").sum())]
    totals.loc[len(totals)] = ["  of which verified_secondary_evidence", int((ver.status == "verified_secondary_evidence").sum())]
    totals.loc[len(totals)] = ["duplicates merged (aliases/redirects/same store id)", ndup]
    out.append(("Summary counts", totals))
    out.extend(shard_tables(con, ver))
    out.append(("Verified stores by category (unified taxonomy)", ver.category.map(unify_category).value_counts().rename_axis("Category").reset_index(name="Verified stores")))
    out.append(("Verified stores by platform", ver.platform.fillna("unknown").replace("", "unknown").value_counts().rename_axis("Platform").reset_index(name="Verified stores")))
    states = Counter()
    for ev in ver.market_evidence:
        e = json_obj(ev)
        for p in e.get("places", []):
            states[p] += 1
        a = e.get("us_address") or ""
        m = re.match(r"([A-Z]{2})\b", a)
        if m and m.group(1) in US_STATES:
            states[US_STATES[m.group(1)] + " (address)"] += 1
    out.append(("US states / metros named on verified storefronts (multi-count; address = state in a US street address)",
                pd.DataFrame(states.most_common(), columns=["State / metro", "Stores mentioning"])))
    missing = [s for s in US_STATES.values() if not any(k.startswith(s) for k in states)]
    out.append(("States with no verified storefront mentioning them", pd.DataFrame({"State": missing or ["(none: all 50 states + DC appear)"]})))
    src = q("""SELECT s.source AS Source, count(*) AS Candidates, sum(c.status IN ('verified','duplicate')) AS 'Verified (incl. dup)',
                      sum(c.status='rejected') AS Rejected, sum(c.status='unverified') AS Unverified, sum(c.status IN ('pending','in_progress')) AS Pending
               FROM candidate_sources s JOIN candidates c USING(key) GROUP BY 1 ORDER BY 3 DESC""")
    out.append(("Discovery sources (a candidate may have several sources)", src))
    try:
        scr = q("SELECT status AS 'Screen result', count(*) AS Domains, min(rank) AS 'Best rank', max(rank) AS 'Worst rank' FROM screen GROUP BY 1 ORDER BY 2 DESC")
        out.append(("Tranco top-1M homepage screen", scr))
    except Exception:
        pass
    out.append(("Sources / directories registry", q("SELECT source AS Source, type AS Type, description AS Description, status AS Status, notes AS Notes FROM sources")))
    try:
        out.append(("Searches performed (by engine and workstream)", q("SELECT engine AS Engine, workstream AS Workstream, status AS Status, count(*) AS Queries, sum(n_results) AS Results, sum(n_new) AS 'New candidates' FROM queries GROUP BY 1,2,3 ORDER BY 1,4 DESC")))
    except Exception:
        pass
    out.append(("Common Crawl CDX harvesting", q("SELECT substr(job, instr(job,'|')+1, instr(substr(job, instr(job,'|')+1),'|')-1) AS Pattern, count(*) AS 'Index pages fetched', sum(n) AS 'Keys seen', sum(n_new) AS 'New candidates' FROM jobs WHERE kind='cc' AND status='done' GROUP BY 1")))
    out.append(("Worker utilization (parallel code workers; no AI subagents were available/spawned)", q("SELECT name AS Worker, kind AS Kind, concurrency AS Concurrency, started AS Started, heartbeat AS 'Last heartbeat', info AS 'Last stats' FROM workers")))
    out.append(("Top rejection / unverified reasons", q("SELECT status AS Status, substr(reason,1,70) AS Reason, count(*) AS Count FROM verifications WHERE status NOT IN ('verified','verified_secondary_evidence') GROUP BY 1,2 ORDER BY 3 DESC LIMIT 50")))
    if len(ref_df):
        rc = ref_df.groupby(["tier", ref_df.status.str.split(":").str[0].str.split(" \\(").str[0]]).size().reset_index(name="Refs")
        rc.columns = ["Tier", "Coverage status", "Refs"]
        out.append(("Reference-universe coverage by tier", rc))
    gaps = pd.DataFrame({"Remaining gaps / expansion opportunities": [
        "Egress from this VM saturates around ~600 new domains/minute (DNS and NAT time out above that), which bounds Tranco screening and verification throughput.",
        "Tranco: see the screen table for how far down the ranking the homepage screen got; ranks beyond were not screened unless found via another channel.",
        "Bot-walled retailers (Akamai/Cloudflare/PerimeterX/Vercel 403/429) are verified only with two independent secondary proofs; otherwise listed as Unverified with the reason.",
        "Search engines: Google requires JS, DuckDuckGo returns HTTP 202 anomaly pages, Brave 429, Mojeek 403 from this VM; no search API keys were configured.",
        "Shopify throttles this VM's IP platform-wide after bursts, so myshopify.com candidates from Common Crawl are verified slowly (slow lane).",
        "Category labels are keyword-based (title/meta/product names) and can be wrong for multi-category stores.",
        "Small stores are covered only when they appear in Tranco top ranks, Common Crawl platform host lists, Wikidata, or the reference list.",
        "Opportunities: screen Tranco beyond the ranks completed; more Common Crawl crawls for platform hosts; mall tenant directories (Simon/Brookfield/Macerich/Westfield) and Shopify/BigCommerce showcases.",
    ]})
    out.append(("Remaining gaps and expansion opportunities", gaps))
    return out


if __name__ == "__main__":
    main()
