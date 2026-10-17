#!/usr/bin/env python3
"""Export shard CSV + summary from worker JSONL, and snapshot/restore raw progress for git.

    python3 export.py                # write CSV, summary, raw snapshot
    python3 export.py --restore      # rebuild data/work files from the committed raw snapshot
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from worker import HI, LO, WORK  # noqa: E402

SHARD = "usa_tranco_500k_1m"
OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
RAW_GZ = os.path.join(OUT_DIR, "work", f"{SHARD}_raw.jsonl.gz")
COLS = ["store_name", "canonical_storefront_url", "root_domain", "platform", "category", "status", "us_evidence",
        "verification_url", "verification_utc", "discovery_source", "tranco_rank", "reason"]
STATUS_RANK = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
FILE_PRIORITY = {"results_w": 0, "results_shopify": 1, "results_secondary": 2}
PENDING = {"deferred_shopify"}
ERROR_STATES = {"unreachable", "error", "robots_5xx"}


def load_all():
    recs = []
    if not os.path.isdir(WORK):
        return recs
    for fn in sorted(os.listdir(WORK)):
        if not (fn.startswith("results_") and fn.endswith(".jsonl")):
            continue
        prio = next((p for k, p in FILE_PRIORITY.items() if fn.startswith(k)), 0)
        with open(os.path.join(WORK, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if "d" in r:
                    r["_f"] = fn
                    r["_p"] = prio
                    recs.append(r)
    return recs


def latest(recs):
    best = {}
    for r in recs:
        cur = best.get(r["d"])
        if cur is None or (r["_p"], r.get("t", 0)) >= (cur["_p"], cur.get("t", 0)):
            best[r["d"]] = r
    return best


def snapshot(recs):
    os.makedirs(os.path.dirname(RAW_GZ), exist_ok=True)
    with gzip.open(RAW_GZ, "wt", compresslevel=9) as f:
        for r in recs:
            r = {k: v for k, v in r.items() if k != "_p"}
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def restore():
    if not os.path.exists(RAW_GZ):
        print("no snapshot")
        return
    os.makedirs(WORK, exist_ok=True)
    have = {fn for fn in os.listdir(WORK) if fn.endswith(".jsonl")}
    if have:
        print("work dir not empty; refusing to restore over", have)
        return
    handles = {}
    n = 0
    with gzip.open(RAW_GZ, "rt") as f:
        for line in f:
            r = json.loads(line)
            fn = r.pop("_f", "results_w_restored.jsonl")
            if fn not in handles:
                handles[fn] = open(os.path.join(WORK, fn), "a")
            handles[fn].write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    for h in handles.values():
        h.close()
    print(f"restored {n} records into {sorted(handles)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--concurrency-note", default="4 main workers x 200-300 concurrent domains; 1 Shopify-edge worker with adaptive global rate 0.2-4 req/s")
    args = ap.parse_args()
    if args.restore:
        restore()
        return
    recs = load_all()
    snapshot(recs)
    best = latest(recs)
    states = Counter(r["s"] for r in best.values())
    rows = [dict(r["row"]) for r in best.values() if r.get("s") == "hit" and r.get("row")]

    groups = defaultdict(list)
    for row in rows:
        key = row["canonical_storefront_url"].replace("https://www.", "https://").rstrip("/")
        groups[key].append(row)
    final = []
    for key, g in groups.items():
        g.sort(key=lambda x: (STATUS_RANK.get(x["status"], 9), int(x["tranco_rank"] or 10**9)))
        keep = g[0]
        if len(g) > 1:
            others = sorted({x["tranco_rank"] for x in g[1:]})
            keep["discovery_source"] += f" (+{len(g) - 1} duplicate Tranco entries merged, ranks {','.join(map(str, others[:5]))})"
        final.append(keep)
    final.sort(key=lambda x: (STATUS_RANK.get(x["status"], 9), int(x["tranco_rank"] or 10**9)))

    csv_path = os.path.join(OUT_DIR, f"{SHARD}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(final)

    st = Counter(r["status"] for r in final)
    ver = [r for r in final if r["status"] in ("verified", "verified_secondary_evidence")]
    ts = [r.get("t", 0) for r in best.values() if r.get("t")]
    pending = sum(states[s] for s in PENDING)
    summary = {
        "shard": SHARD,
        "slice": f"Tranco top-1M ranks {LO:,}-{HI:,} inclusive, all TLDs",
        "tranco_list_id": "64VVX (downloaded 2026-10-17)",
        "inputs_in_slice": HI - LO + 1,
        "screened": len(best) - pending,
        "pending_shopify_edge_queue": pending,
        "store_hits": len(final),
        "verified": st["verified"],
        "verified_secondary_evidence": st["verified_secondary_evidence"],
        "unverified": st["unverified"],
        "rejected": st["rejected"],
        "errors": sum(states[s] for s in ERROR_STATES),
        "screen_outcomes": dict(states.most_common()),
        "verified_by_platform": dict(Counter(r["platform"] for r in ver).most_common()),
        "verified_by_category": dict(Counter(r["category"] for r in ver).most_common()),
        "runtime_seconds_of_recorded_work": (max(ts) - min(ts)) if ts else 0,
        "first_record_utc": min(ts) if ts else None,
        "last_record_utc": max(ts) if ts else None,
        "concurrency": args.concurrency_note,
    }
    with open(os.path.join(OUT_DIR, f"{SHARD}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("verified_by_category",)}, indent=1))


if __name__ == "__main__":
    main()
