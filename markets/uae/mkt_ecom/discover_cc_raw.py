"""Common Crawl discovery straight from the sorted CDX shards on data.commoncrawl.org.

Used when the index.commoncrawl.org CDX API is unavailable. cluster.idx is
binary-searched with HTTP range requests for the market ccTLD SURT prefix
(e.g. "ae,"); only the matching gzip blocks are range-fetched. Blocks whose
first host equals the next block's first host hold a single host and are not
fetched. Resumable per crawl/chunk via the jobs table.
"""
from __future__ import annotations

import argparse
import collections
import random
import time
import zlib

import httpx

from . import db
from .common import identity
from .discover_cc import ECOM_PATH
from .market import M

BASE = "https://data.commoncrawl.org/"
UA = {"User-Agent": "mkt-ecom-directory-research/1.0 (polite CC shard reader)"}
CHUNK_BYTES = 24_000_000


def get(client, url, headers=None, tries=6):
    delay = 4
    for _ in range(tries):
        try:
            r = client.get(url, headers=headers or {}, timeout=300)
            if r.status_code in (200, 206):
                return r
            if r.status_code == 404:
                return None
        except httpx.HTTPError:
            pass
        time.sleep(delay + random.random() * 2)
        delay = min(delay * 2, 32)
    return None


def crawl_ids(client, n):
    r = get(client, BASE + "crawl-data/index.html")
    import re
    ids = sorted(set(re.findall(r"CC-MAIN-20\d\d-\d\d", r.text)), reverse=True)
    return ids[:n]


def surt_host(key: str) -> str:
    return ".".join(reversed(key.split(")")[0].split(",")))


def find_offset(client, url, size, key: bytes):
    lo, hi = 0, size
    while hi - lo > 16384:
        mid = (lo + hi) // 2
        r = get(client, url, {"Range": f"bytes={mid}-{mid + 8191}"})
        chunk = r.content
        nl = chunk.find(b"\n")
        line = chunk[nl + 1:].split(b"\n")[0]
        if line.split(b" ")[0] < key:
            lo = mid
        else:
            hi = mid
    return lo


def index_lines(client, crawl, tld):
    url = f"{BASE}cc-index/collections/{crawl}/indexes/cluster.idx"
    h = client.head(url, timeout=60)
    size = int(h.headers["content-length"])
    start = find_offset(client, url, size, f"{tld},".encode())
    end = find_offset(client, url, size, f"{tld}-".encode()) + 32768
    r = get(client, url, {"Range": f"bytes={start}-{min(end, size - 1)}"})
    out = []
    for raw in r.text.split("\n"):
        parts = raw.split("\t")
        if len(parts) < 4:
            continue
        key = parts[0].split(" ")[0]
        out.append((key, parts[1], int(parts[2]), int(parts[3])))
    # include one block before the first match: it may end with tld records
    first = next((i for i, l in enumerate(out) if l[0].startswith(tld + ",")), None)
    if first is None:
        return []
    last = max(i for i, l in enumerate(out) if l[0].startswith(tld + ","))
    return out[max(first - 1, 0): last + 1]


def plan_chunks(lines, tld):
    singles, fetch = set(), []
    for i, (key, f, off, ln) in enumerate(lines):
        nxt = lines[i + 1][0] if i + 1 < len(lines) else None
        h = surt_host(key)
        if key.startswith(tld + ",") and nxt and nxt.startswith(tld + ",") and surt_host(nxt) == h:
            singles.add(h)
            continue
        fetch.append((f, off, ln))
    chunks, cur = [], []
    for f, off, ln in fetch:
        if cur and (cur[-1][0] != f or cur[-1][1] + cur[-1][2] != off or sum(c[2] for c in cur) > CHUNK_BYTES):
            chunks.append(cur)
            cur = []
        cur.append((f, off, ln))
    if cur:
        chunks.append(cur)
    return singles, chunks


def decode_members(data: bytes):
    while data:
        d = zlib.decompressobj(31)
        yield d.decompress(data)
        data = d.unused_data


def harvest_chunk(client, crawl, chunk, tld):
    f, off = chunk[0][0], chunk[0][1]
    end = chunk[-1][1] + chunk[-1][2] - 1
    r = get(client, f"{BASE}cc-index/collections/{crawl}/indexes/{f}", {"Range": f"bytes={off}-{end}"})
    if r is None:
        return None
    hits = collections.Counter()
    seen = {}
    for text in decode_members(r.content):
        for line in text.split(b"\n"):
            if not line.startswith(tld.encode() + b","):
                continue
            surt = line.split(b" ", 1)[0].decode("utf-8", "replace")
            host = surt_host(surt)
            path = surt.split(")", 1)[1] if ")" in surt else "/"
            seen.setdefault(host, f"https://{host}/")
            if ECOM_PATH.search(path):
                hits[host] += 1
    return seen, hits


def main(n_crawls, tld, base_pr):
    con = db.connect()
    db.register_source(con, "commoncrawl_raw", "index", "Common Crawl CDX shards via data.commoncrawl.org (cluster.idx range reads)")
    db.heartbeat(con, "discover_cc_raw", "code-worker", 1, {"tld": tld})
    client = httpx.Client(headers=UA, follow_redirects=True, http2=False)
    total_new = 0
    for crawl in crawl_ids(client, n_crawls):
        if db.job_done(con, "ccraw", f"{crawl}|{tld}|all"):
            continue
        lines = index_lines(client, crawl, tld)
        singles, chunks = plan_chunks(lines, tld)
        items = [(f"https://{h}/", base_pr) for h in singles]
        new = db.add_candidates(con, items, source=f"commoncrawl:{tld}", detail=crawl)
        total_new += new
        print(f"[ccraw] {crawl} blocks={len(lines)} single_host={len(singles)} new={new} chunks={len(chunks)}", flush=True)
        for ci, ch in enumerate(chunks):
            job = f"{crawl}|{tld}|{ci}"
            if db.job_done(con, "ccraw", job):
                continue
            res = harvest_chunk(client, crawl, ch, tld)
            if res is None:
                db.mark_job(con, "ccraw", job, "failed")
                continue
            seen, hits = res
            items = []
            for h, u in seen.items():
                if not identity(u):
                    continue
                pr = base_pr + (3 if hits[h] >= 3 else 2 if hits[h] else 0)
                items.append((u, pr))
            new = db.add_candidates(con, items, source=f"commoncrawl:{tld}", detail=crawl)
            total_new += new
            db.mark_job(con, "ccraw", job, "done", len(items), new)
            print(f"[ccraw] {job} hosts={len(items)} new={new} total_new={total_new}", flush=True)
            time.sleep(0.5)
        db.mark_job(con, "ccraw", f"{crawl}|{tld}|all", "done", 0, total_new)
        db.heartbeat(con, "discover_cc_raw", "code-worker", 1, {"tld": tld, "total_new": total_new})
    print("[ccraw] done total_new", total_new, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawls", type=int, default=8)
    ap.add_argument("--tld", default=M.cctld)
    ap.add_argument("--priority", type=int, default=2)
    a = ap.parse_args()
    main(a.crawls, a.tld, a.priority)
