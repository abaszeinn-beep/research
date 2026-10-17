"""Export the usa_other_platforms shard CSV + summary JSON, and restore DB state from a pushed CSV."""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import time
import zipfile
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from . import db
from .common_us import identity, strip_tracking

SHARD = "usa_other_platforms"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_COLS = ["store_name", "canonical_storefront_url", "root_domain", "platform", "category", "status", "us_evidence",
            "verification_url", "verification_utc", "discovery_source", "tranco_rank", "reason"]
MAX_BYTES = 85_000_000
STATUS_RANK = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
TRANCO_ZIP = os.path.join(db.WORK, "tranco_top1m.csv.zip")


def load_tranco():
    ranks = {}
    if not os.path.exists(TRANCO_ZIP):
        return ranks
    with zipfile.ZipFile(TRANCO_ZIP) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            for line in fh:
                r, d = line.decode().strip().split(",", 1)
                ranks.setdefault(d.lower(), int(r))
    return ranks


def canonical(final_url: str, key: str) -> str:
    ident = identity(final_url) if final_url else None
    if ident is None:
        ident = identity("https://" + key.split("|")[0])
    if ident is None:
        return final_url or ""
    if ident["platform_hint"] or ident["key"].endswith("|us"):
        return ident["url"]
    host = urlsplit(strip_tracking(final_url)).hostname or ident["root_domain"]
    return f"https://{host}/"


def compact_evidence(ev_json: str) -> str:
    try:
        ev = json.loads(ev_json or "{}")
    except ValueError:
        return ""
    parts = []
    for k, v in ev.items():
        if isinstance(v, list):
            v = "/".join(str(x) for x in v[:3])
        parts.append(f"{k}={v}" if v is not True else k)
    return "; ".join(parts)[:400]


def build_rows(con, tranco):
    srcs = defaultdict(set)
    for k, s, d in con.execute("SELECT key, source, detail FROM candidate_sources"):
        srcs[k].add(f"{s}:{d}" if d else s)
    rows = con.execute(
        "SELECT c.key, c.platform_hint, c.root_domain, v.final_url, v.final_key, v.store_name, v.platform, v.category, v.status, "
        "v.us_evidence, v.evidence_url, v.verified_at, v.reason, v.product_evidence FROM candidates c JOIN verifications v ON v.key=c.key").fetchall()
    best = {}
    for (key, hint, root, final_url, final_key, name, plat, cat, status, usev, evurl, vat, reason, prod) in rows:
        if status not in STATUS_RANK:
            continue
        group = final_key or key
        if status in ("unverified", "rejected"):
            group = key
        canon = canonical(final_url or "", key) if status.startswith("verified") else canonical(final_url or "", key)
        rd = (identity(canon) or {}).get("root_domain") or root
        platform = plat if plat and plat != "custom/unknown" else (hint or "custom/unknown")
        rec = {
            "store_name": (name or "").strip(), "canonical_storefront_url": canon, "root_domain": rd,
            "platform": platform, "category": cat if status.startswith("verified") else (cat or ""),
            "status": status, "us_evidence": compact_evidence(usev),
            "verification_url": (prod if status.startswith("verified") and prod else evurl) or final_url or "",
            "verification_utc": vat or "", "discovery_source": "; ".join(sorted(srcs.get(key, [])))[:200],
            "tranco_rank": tranco.get(rd, "") if rd else "", "reason": (reason or "")[:300], "_key": key,
        }
        cur = best.get(group)
        if cur is None or STATUS_RANK[status] < STATUS_RANK[cur["status"]] or (
                status == cur["status"] and key == group and cur["_key"] != group):
            if cur is not None and cur["status"].startswith("verified") and status.startswith("verified"):
                rec["discovery_source"] = "; ".join(sorted(set(rec["discovery_source"].split("; ")) | set(cur["discovery_source"].split("; "))))[:200]
            best[group] = rec
    # a verified custom domain supersedes unverified/rejected rows for the same root
    verified_roots = {r["canonical_storefront_url"] for r in best.values() if r["status"].startswith("verified")}
    out = [r for r in best.values() if r["status"].startswith("verified") or r["canonical_storefront_url"] not in verified_roots]
    out.sort(key=lambda r: (STATUS_RANK[r["status"]], r["platform"], r["root_domain"]))
    return out


def write_csv(rows):
    for old in glob.glob(os.path.join(OUT_DIR, f"{SHARD}*.csv")):
        os.remove(old)
    part, size, fh, w, files = 1, 0, None, None, []

    def open_part(n):
        name = os.path.join(OUT_DIR, f"{SHARD}.csv" if n == 1 else f"{SHARD}_part{n}.csv")
        f = open(name, "w", newline="", encoding="utf-8")
        wr = csv.DictWriter(f, CSV_COLS, extrasaction="ignore")
        wr.writeheader()
        files.append(name)
        return f, wr

    fh, w = open_part(part)
    for r in rows:
        line = sum(len(str(r.get(c, ""))) + 3 for c in CSV_COLS)
        if size + line > MAX_BYTES:
            fh.close()
            part += 1
            size = 0
            fh, w = open_part(part)
        w.writerow(r)
        size += line
    fh.close()
    if len(files) > 1:
        os.rename(files[0], os.path.join(OUT_DIR, f"{SHARD}_part1.csv"))
    return files


def summary(con, rows, extra):
    st = Counter(r["status"] for r in rows)
    ver = [r for r in rows if r["status"].startswith("verified")]
    disc = dict(con.execute("SELECT coalesce(platform_hint,'unknown'), count(*) FROM candidates GROUP BY 1 ORDER BY 2 DESC").fetchall())
    by_src = dict(con.execute("SELECT source, count(DISTINCT key) FROM candidate_sources GROUP BY 1").fetchall())
    screened = con.execute("SELECT count(*) FROM verifications").fetchone()[0]
    pending = con.execute("SELECT count(*) FROM candidates WHERE status IN ('pending','in_progress')").fetchone()[0]
    reasons = Counter()
    errors = 0
    for (r,) in con.execute("SELECT reason FROM verifications WHERE status IN ('unverified','rejected')"):
        k = re.split(r"[ :(]", r or "", maxsplit=1)[0]
        reasons[k] += 1
        if k.startswith(("fetch_failed", "verifier_error", "verification_timeout")):
            errors += 1
    snaps = [r[0] for r in con.execute("SELECT DISTINCT detail FROM candidate_sources WHERE source='commoncrawl-columnar' ORDER BY 1 DESC")]
    parts = con.execute("SELECT count(*) FROM jobs WHERE kind='ccparquet' AND status='done'").fetchone()[0]
    out = {
        "shard": SHARD, "generated_utc": db.now(),
        "inputs_discovered_total": sum(disc.values()), "inputs_discovered_per_platform": disc,
        "inputs_discovered_per_source": by_src, "screened": screened, "not_yet_screened": pending,
        "rows_in_csv": len(rows), "verified": st.get("verified", 0), "verified_secondary_evidence": st.get("verified_secondary_evidence", 0),
        "unverified": st.get("unverified", 0), "rejected": st.get("rejected", 0), "errors": errors,
        "verified_by_platform": dict(Counter(r["platform"] for r in ver).most_common()),
        "verified_by_category": dict(Counter(r["category"] for r in ver).most_common()),
        "top_unverified_rejected_reasons": dict(reasons.most_common(30)),
        "common_crawl_snapshots_used": snaps, "common_crawl_columnar_part_files_scanned": parts,
    }
    out.update(extra)
    with open(os.path.join(OUT_DIR, f"{SHARD}_summary.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    return out


def restore(paths):
    """Load a previously pushed shard CSV into an empty DB so verified/rejected keys are not re-fetched."""
    con = db.connect()
    n = 0
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        def _do():
            nonlocal n
            for r in rows:
                ident = identity(r["canonical_storefront_url"])
                if not ident:
                    continue
                key = ident["key"]
                con.execute("INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,status,first_seen) VALUES(?,?,?,?,?,?)",
                            (key, ident["url"], ident["root_domain"], r["platform"], r["status"], r["verification_utc"]))
                con.execute("UPDATE candidates SET status=? WHERE key=?", (r["status"], key))
                con.execute("INSERT OR IGNORE INTO verifications(key,final_url,final_key,store_name,platform,category,us_evidence,status,reason,evidence_url,verified_at,product_evidence,method) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (key, r["canonical_storefront_url"], key, r["store_name"], r["platform"], r["category"],
                             json.dumps({"restored": r["us_evidence"]}), r["status"], r["reason"], r["verification_url"],
                             r["verification_utc"], r["verification_url"], "restored_csv"))
                n += 1
        db.retry(con, _do)
    print("restored", n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", nargs="*")
    ap.add_argument("--runtime-s", type=float, default=0)
    ap.add_argument("--concurrency", default="")
    a = ap.parse_args()
    if a.restore:
        restore(a.restore)
    else:
        t = time.time()
        con = db.connect()
        rows = build_rows(con, load_tranco())
        files = write_csv(rows)
        s = summary(con, rows, {"runtime_seconds": a.runtime_s, "concurrency_used": a.concurrency, "csv_files": [os.path.basename(f) for f in files]})
        print(json.dumps({k: s[k] for k in ("rows_in_csv", "verified", "unverified", "rejected", "screened", "not_yet_screened")}))
