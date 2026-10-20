"""Internet Archive Wayback CDX discovery (paged with resumeKey; resumable via jobs table)."""
from __future__ import annotations

import argparse
import asyncio
import random

import httpx

from . import db
from .discover_cc import harvest  # noqa: F401  (same priority heuristics)
from .common import identity
from .discover_cc import ECOM_PATH

CDX = "http://web.archive.org/cdx/search/cdx"
UA = {"User-Agent": "market-ecom-directory-research/1.0 (polite CDX client)"}

PATTERNS = {
    # name: (url, matchType, extra filters, base priority)
    "com.kw": ("com.kw", "domain", ["mimetype:text/html", "statuscode:200"], 3),
    "kw": ("kw", "domain", ["!original:.*\\.(?:gov|edu|org|net)\\.kw.*", "mimetype:text/html", "statuscode:200"], 2),
    "ordable.com": ("ordable.com", "domain", ["mimetype:text/html"], 3),
    "salla.sa": ("salla.sa/", "prefix", [], 0),
}


async def run(pattern, since, page_lines, max_pages):
    con = db.connect()
    url, mt, filters, base_pr = PATTERNS[pattern]
    src = f"wayback:{pattern}"
    db.register_source(con, src, "index", f"Internet Archive Wayback CDX ({url}, matchType={mt}, from={since})")
    state_key = f"{pattern}|{since}"
    row = con.execute("SELECT info, n, n_new, status FROM jobs WHERE kind='wayback' AND job=?", (state_key,)).fetchone()
    resume = row[0] if row and row[0] else None
    total, total_new = (row[1] or 0, row[2] or 0) if row else (0, 0)
    if row and row[3] == "done":
        print(f"[wayback] {pattern} already done", flush=True)
        return
    pages = 0
    async with httpx.AsyncClient(headers=UA, timeout=300) as client:
        while pages < max_pages:
            params = [("url", url), ("matchType", mt), ("fl", "original"), ("collapse", "urlkey"),
                      ("limit", str(page_lines)), ("showResumeKey", "true"), ("from", since)]
            params += [("filter", f) for f in filters]
            if resume:
                params.append(("resumeKey", resume))
            r = None
            delay = 5
            for _ in range(6):
                try:
                    r = await client.get(CDX, params=params)
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(delay + random.random() * 3)
                delay = min(delay * 2, 120)
            if r is None or r.status_code != 200:
                print(f"[wayback] {pattern} failed page {pages}", flush=True)
                db.mark_job(con, "wayback", state_key, "partial", total, total_new, resume or "")
                return
            lines = r.text.splitlines()
            next_resume = None
            if len(lines) >= 2 and lines[-2].strip() == "":
                next_resume = lines[-1].strip()
                lines = lines[:-2]
            urls = {}
            hits = {}
            for u in lines:
                ident = identity(u.strip())
                if not ident:
                    continue
                k = ident["key"]
                urls.setdefault(k, u.strip())
                if ECOM_PATH.search(u):
                    hits[k] = hits.get(k, 0) + 1
            items = [(u, base_pr + (3 if hits.get(k, 0) >= 3 else 2 if hits.get(k) else 0)) for k, u in urls.items()]
            new = db.add_candidates(con, items, source=src, detail=f"from={since}")
            total += len(items)
            total_new += new
            pages += 1
            resume = next_resume
            db.mark_job(con, "wayback", state_key, "done" if not resume else "partial", total, total_new, resume or "")
            print(f"[wayback] {pattern} page={pages} lines={len(lines)} keys={len(items)} new={new} total_new={total_new}", flush=True)
            db.heartbeat(con, f"wayback:{pattern}", "code-worker(asyncio)", 1, {"pages": pages, "total_new": total_new})
            if not resume:
                break
            await asyncio.sleep(2)
    print(f"[wayback] {pattern} finished: keys={total} new={total_new}", flush=True)


async def main(patterns, since, page_lines, max_pages):
    await asyncio.gather(*[run(p, since, page_lines, max_pages) for p in patterns])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patterns", default="com.kw,ordable.com")
    ap.add_argument("--since", default="2024")
    ap.add_argument("--page-lines", type=int, default=50000)
    ap.add_argument("--max-pages", type=int, default=1000)
    a = ap.parse_args()
    asyncio.run(main(a.patterns.split(","), a.since, a.page_lines, a.max_pages))
