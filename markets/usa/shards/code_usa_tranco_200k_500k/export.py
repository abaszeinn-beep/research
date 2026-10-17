"""Export the shard CSV + summary JSON from the per-worker SQLite state files (and secondary-evidence results).

Dedup: rows are keyed by the canonical storefront (registrable domain of the final URL, plus a /us storefront path when
present; Shopify stores also by their primary domain). Within a key the best row is kept (verified >
verified_secondary_evidence > unverified > rejected, then lowest Tranco rank); the others stay in the file as rejected
"duplicate_of:<key>" so every screened hit is accounted for.
"""
from __future__ import annotations

import csv
import glob
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))
from pipeline import STATE, TRANCO_ID, now  # noqa: E402
from saudi_ecom.common import registrable_domain  # noqa: E402

SHARD = "usa_tranco_200k_500k"
OUT_DIR = HERE.parent
COLS = ["store_name", "canonical_storefront_url", "root_domain", "platform", "category", "status", "us_evidence", "verification_url",
        "verification_utc", "discovery_source", "tranco_rank", "reason"]
RANK = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
MAX_BYTES = 90_000_000


def key_of(row, detail):
    u = row["canonical_storefront_url"] or ("https://" + row["root_domain"] + "/")
    sp = urlsplit(u)
    root = registrable_domain((sp.hostname or row["root_domain"]).lower())
    path = sp.path if sp.path not in ("", "/") else ""
    return root + path.rstrip("/")


def load():
    rows, stats, meta = [], Counter(), {}
    for p in sorted(glob.glob(str(STATE / "w*.sqlite"))):
        con = sqlite3.connect(p)
        for stage, status, n in con.execute("SELECT stage,status,count(*) FROM results GROUP BY 1,2"):
            stats[status] += n
            stats["screened_total"] += n
        for r, d in con.execute("SELECT row, detail FROM results WHERE stage='hit' AND row IS NOT NULL"):
            rows.append((json.loads(r), json.loads(d) if d else {}))
        for k, v in con.execute("SELECT k,v FROM meta"):
            meta.setdefault(k, []).append(v)
        con.close()
    sec = STATE / "secondary.sqlite"
    sec_rows = {}
    if sec.exists():
        con = sqlite3.connect(sec)
        for dom, r in con.execute("SELECT domain,row FROM secondary WHERE row IS NOT NULL"):
            sec_rows[dom] = json.loads(r)
        con.close()
    return rows, stats, meta, sec_rows


def main():
    rows, stats, meta, sec_rows = load()
    for dom, r in sec_rows.items():
        rows.append((r, {"secondary": True}))
    groups = {}
    for r, d in rows:
        k = key_of(r, d)
        alias = (d.get("shopify_primary_domain") or "")
        groups.setdefault(k, []).append((r, d, alias))
    alias_map = {}
    for k, items in groups.items():
        for r, d, alias in items:
            if alias:
                ak = registrable_domain(alias.lower().removeprefix("www."))
                if ak != k and ak in groups:
                    alias_map[k] = ak
    for k, ak in alias_map.items():
        if k in groups and ak in groups:
            groups[ak].extend(groups.pop(k))
    out = []
    for k, items in groups.items():
        items.sort(key=lambda x: (RANK.get(x[0]["status"], 9), int(x[0].get("tranco_rank") or 10**9)))
        best = items[0][0]
        out.append(best)
        for r, _, _ in items[1:]:
            r = dict(r)
            if r["status"] != "rejected" or "duplicate" not in r["reason"]:
                r["reason"] = f"duplicate_of:{best['canonical_storefront_url']} (was {r['status']}: {r['reason'][:120]})"
                r["status"] = "rejected"
            out.append(r)
    out.sort(key=lambda r: (RANK.get(r["status"], 9), int(r.get("tranco_rank") or 10**9)))

    parts, cur, size = [], [], 0
    for r in out:
        sz = sum(len(str(r.get(c, ""))) for c in COLS) + 40
        if size + sz > MAX_BYTES and cur:
            parts.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += sz
    parts.append(cur)
    for old in glob.glob(str(OUT_DIR / f"{SHARD}*.csv")):
        Path(old).unlink()
    files = []
    for i, part in enumerate(parts):
        fn = OUT_DIR / (f"{SHARD}.csv" if len(parts) == 1 else f"{SHARD}_part{i + 1}.csv")
        with open(fn, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            for r in part:
                w.writerow({c: r.get(c, "") for c in COLS})
        files.append(fn.name)

    st = Counter(r["status"] for r in out)
    ver = [r for r in out if r["status"] in ("verified", "verified_secondary_evidence")]
    started = min(meta.get("started", [now()]))
    finished = max(meta.get("finished", [""])) if len(meta.get("finished", [])) >= 4 else None
    import datetime as dt
    def p(t):
        return dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    runtime_min = round(((p(finished) if finished else dt.datetime.utcnow()) - p(started)).total_seconds() / 60, 1)
    with open(STATE / "slice.csv") as fh:
        n_slice = sum(1 for _ in fh)
    summary = {
        "shard": SHARD,
        "slice": "Tranco top-1M ranks 200,001-500,000 (inclusive), all TLDs",
        "tranco_list_id": TRANCO_ID,
        "generated_utc": now(),
        "inputs_in_slice": n_slice,
        "screened": stats["screened_total"],
        "screen_outcomes": {k: v for k, v in stats.items() if k != "screened_total"},
        "fast_skipped_non_retail": stats.get("skipped", 0),
        "store_hits": len(out),
        "store_hits_unique_storefronts": len(groups),
        "verified": st.get("verified", 0),
        "verified_secondary_evidence": st.get("verified_secondary_evidence", 0),
        "unverified": st.get("unverified", 0),
        "rejected": st.get("rejected", 0),
        "duplicates_marked_rejected": sum(1 for r in out if r["reason"].startswith("duplicate_of:")),
        "errors": stats.get("error", 0) + stats.get("http_error", 0),
        "blocked_bot_wall_or_403": stats.get("blocked", 0),
        "robots_disallowed": stats.get("robots_disallowed", 0),
        "runtime_minutes": runtime_min,
        "finished": bool(finished),
        "concurrency_used": "4 worker processes x 130 concurrent domains (asyncio/aiohttp, max 2 connections and >=0.4 s gap per host, "
                            "robots.txt honored, 18 s request cap, 150 s per-domain cap); secondary pass 12 concurrent",
        "verified_by_platform": dict(Counter(r["platform"] for r in ver).most_common()),
        "verified_by_category": dict(Counter(r["category"] for r in ver).most_common()),
        "rejection_reasons": dict(Counter(r["reason"].split(" ")[0].split(":")[0] for r in out if r["status"] == "rejected").most_common(25)),
        "unverified_reasons": dict(Counter(r["reason"].split(" ")[0].split(":")[0] for r in out if r["status"] == "unverified").most_common(25)),
        "files": files,
    }
    with open(OUT_DIR / f"{SHARD}_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps({k: summary[k] for k in ("screened", "store_hits", "verified", "verified_secondary_evidence", "unverified", "rejected", "errors", "runtime_minutes")}))


if __name__ == "__main__":
    main()
