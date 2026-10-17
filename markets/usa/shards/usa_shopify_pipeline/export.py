"""Export markets/usa/shards/usa_shopify.csv (+ parts if large) and usa_shopify_summary.json."""
from __future__ import annotations

import csv
import glob
import gzip
import json
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from common import DB_PATH, SHARD_DIR, connect, get_meta, registrable, utcnow  # noqa: E402
import signals as S  # noqa: E402

SHARD = "usa_shopify"
COLS = ["store_name", "canonical_storefront_url", "root_domain", "platform", "category", "status", "us_evidence",
        "verification_url", "verification_utc", "discovery_source", "tranco_rank", "reason"]
RANK = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
MAX_PART_BYTES = 85_000_000


def short_sources(s):
    out = []
    for x in (s or "").split(","):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return ";".join(out)


def main(snapshot=False):
    con = connect()
    try:
        trk = dict(con.execute("SELECT domain, rank FROM tranco"))
    except sqlite3.OperationalError:
        trk = {}
    cand = {k: (kind, src, hint) for k, kind, src, hint in con.execute("SELECT key, kind, sources, hint FROM candidates")}
    dup_sources = defaultdict(set)
    rows = []
    for (key, status, reason, name, canon, root, msd, plat, cat, usev, vurl, vutc, cur, country, extra) in con.execute(
            "SELECT key, status, reason, store_name, canonical_url, root_domain, myshopify_domain, platform, category, "
            "us_evidence, verification_url, verification_utc, currency, country, extra FROM results"):
        kind, src, hint = cand.get(key, ("", "", ""))
        if status == "duplicate":
            owner = (reason or "").replace("duplicate_of ", "").strip()
            dup_sources[owner].update(short_sources(src).split(";"))
            dup_sources[owner].add(f"myshopify:{key}" if key.endswith(".myshopify.com") else f"alias:{key}")
            continue
        if status == "error":
            status = "unverified"
        if status == "verified" and extra:
            try:
                x = json.loads(extra)
                if x.get("top_types") or x.get("sample_titles"):
                    cat = S.categorize(x.get("top_types") or [], x.get("sample_titles") or [], [], name or "")
            except ValueError:
                pass
        if not root:
            root = key if key.endswith(".myshopify.com") else registrable(key)
        if not canon:
            canon = f"https://{key}/"
        rows.append({"key": key, "store_name": (name or "").replace("\n", " ").strip(), "canonical_storefront_url": canon,
                     "root_domain": root, "platform": plat or "shopify", "category": cat or "" if status == "verified" else (cat or ""),
                     "status": status, "us_evidence": usev or "", "verification_url": vurl or "",
                     "verification_utc": vutc or "", "discovery_source": short_sources(src), "tranco_rank": "",
                     "reason": reason or "", "_cand_host": key})
    for r in rows:
        r["tranco_rank"] = trk.get(r["root_domain"]) or trk.get(r["_cand_host"]) or ""
    for r in rows:
        if r["key"] in dup_sources:
            extra_src = sorted(x for x in dup_sources[r["key"]] if x)
            r["discovery_source"] = ";".join(dict.fromkeys(r["discovery_source"].split(";") + extra_src)).strip(";")

    # one row per registrable root domain (myshopify roots are per-store); best status wins
    by_root = defaultdict(list)
    for r in rows:
        by_root[r["root_domain"]].append(r)
    final = []
    merged = 0
    for root, rs in by_root.items():
        def score(r):
            host = r["canonical_storefront_url"].split("/")[2] if "//" in r["canonical_storefront_url"] else ""
            return (RANK.get(r["status"], 9), 0 if host in (root, "www." + root) else 1, r["key"])
        rs.sort(key=score)
        best = rs[0]
        if len(rs) > 1:
            merged += len(rs) - 1
            others = [x["key"] for x in rs[1:]]
            best["discovery_source"] = ";".join(dict.fromkeys(best["discovery_source"].split(";") + [f"alias:{k}" for k in others[:5]])).strip(";")
        final.append(best)
    final.sort(key=lambda r: (RANK.get(r["status"], 9), r["root_domain"]))

    for old in glob.glob(os.path.join(SHARD_DIR, f"{SHARD}*.csv")):
        os.remove(old)
    part, size, paths = 0, 0, []
    fh = None
    w = None

    def open_part(n):
        p = os.path.join(SHARD_DIR, f"{SHARD}.csv" if n == 0 else f"{SHARD}_part{n + 1}.csv")
        f = open(p, "w", newline="", encoding="utf-8")
        wr = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        wr.writeheader()
        paths.append(p)
        return f, wr

    fh, w = open_part(0)
    for r in final:
        w.writerow(r)
        size += sum(len(str(r.get(c, ""))) for c in COLS) + 24
        if size > MAX_PART_BYTES:
            fh.close()
            part += 1
            size = 0
            fh, w = open_part(part)
    fh.close()
    if len(paths) > 1:
        os.rename(paths[0], os.path.join(SHARD_DIR, f"{SHARD}_part1.csv"))

    st = Counter(r["status"] for r in final)
    cats = Counter(r["category"] for r in final if r["status"] == "verified")
    reasons = Counter((r["reason"].split(" (")[0]) for r in final if r["status"] in ("rejected", "unverified"))
    by_src = Counter()
    for r in final:
        if r["status"] == "verified":
            for s in r["discovery_source"].split(";"):
                if s and not s.startswith("alias:") and not s.startswith("myshopify:"):
                    by_src[s.split(":")[0]] += 1
    jobs = dict(con.execute("SELECT kind, count(*) FROM jobs WHERE status='done' GROUP BY kind").fetchall())
    vs = get_meta(con, "verify_stats_last", {}) or {}
    summary = {
        "shard": SHARD,
        "generated_utc": utcnow(),
        "inputs_discovered": con.execute("SELECT count(*) FROM candidates").fetchone()[0],
        "inputs_discovered_by_kind": dict(con.execute("SELECT kind, count(*) FROM candidates GROUP BY kind").fetchall()),
        "screened": con.execute("SELECT count(*) FROM results").fetchone()[0],
        "pending_not_screened": con.execute("SELECT count(*) FROM candidates WHERE state!='done'").fetchone()[0],
        "duplicates_merged": con.execute("SELECT count(*) FROM results WHERE status='duplicate'").fetchone()[0] + merged,
        "rows_in_csv": len(final),
        "verified": st.get("verified", 0),
        "verified_secondary_evidence": st.get("verified_secondary_evidence", 0),
        "unverified": st.get("unverified", 0),
        "rejected": st.get("rejected", 0),
        "errors": con.execute("SELECT count(*) FROM results WHERE status='error'").fetchone()[0],
        "verified_by_category": dict(cats.most_common()),
        "verified_by_discovery_source": dict(by_src.most_common()),
        "top_rejection_and_unverified_reasons": dict(reasons.most_common(25)),
        "runtime_verify_seconds": round((get_meta(con, "verify_runtime_s", 0) or 0) + (vs.get("elapsed_s") or 0)),
        "concurrency_used": {"global_http_requests_peak": get_meta(con, "concurrency_peak", None),
                             "stores_in_flight": vs.get("stores_in_flight"), "per_host": 2, "per_host_min_gap_s": 0.35,
                             "columnar_parquet_workers": 6},
        "requests": {k[2:]: v for k, v in vs.items() if k.startswith("f_")},
        "snapshots_used": {"cc_columnar_myshopify_and_shopify_paths": get_meta(con, "columnar_crawls", []),
                           "cc_cdx_api": get_meta(con, "cdx_crawls", []),
                           "wayback_cdx": get_meta(con, "wayback_ranges", [])},
        "index_jobs_done": jobs,
        "csv_files": [os.path.basename(p) for p in (glob.glob(os.path.join(SHARD_DIR, f"{SHARD}*.csv")))],
    }
    qpath = os.path.join(SHARD_DIR, f"{SHARD}_pending_queue.csv.gz")
    n_q = 0
    with gzip.open(qpath, "wt", newline="", encoding="utf-8", compresslevel=9) as qf:
        qw = csv.writer(qf)
        qw.writerow(["candidate_host", "kind", "priority", "tranco_rank", "discovery_source", "hint"])
        for key, kind, pr, src, hint in con.execute(
                "SELECT key, kind, priority, sources, hint FROM candidates WHERE state!='done' ORDER BY priority DESC, key"):
            qw.writerow([key, kind, round(pr, 2), trk.get(key) or trk.get(registrable(key)) or "", short_sources(src), hint])
            n_q += 1
    summary["pending_queue_file"] = os.path.basename(qpath)
    summary["pending_queue_rows"] = n_q
    summary["verified_with_tranco_rank"] = sum(1 for r in final if r["status"] == "verified" and r["tranco_rank"])
    summary["verified_top_by_tranco"] = [[r["root_domain"], r["tranco_rank"]] for r in sorted(
        (r for r in final if r["status"] == "verified" and r["tranco_rank"]), key=lambda r: r["tranco_rank"])[:40]]
    summary.update(get_meta(con, "summary_notes", {}) or {})
    with open(os.path.join(SHARD_DIR, f"{SHARD}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    if snapshot:
        dst = os.path.join(SHARD_DIR, "work", "snap.sqlite")
        src = sqlite3.connect(DB_PATH)
        bk = sqlite3.connect(dst)
        src.backup(bk)
        bk.close()
        with open(dst, "rb") as fi, gzip.open(os.path.join(SHARD_DIR, f"{SHARD}_state.sqlite.gz"), "wb", 6) as fo:
            shutil.copyfileobj(fi, fo)
        os.remove(dst)
    print(json.dumps({k: summary[k] for k in ("inputs_discovered", "screened", "verified", "unverified", "rejected", "rows_in_csv")}))


if __name__ == "__main__":
    main(snapshot="--snapshot" in sys.argv)
