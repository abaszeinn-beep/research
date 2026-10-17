"""Common Crawl CDX API + Internet Archive Wayback CDX discovery for `*.myshopify.com` (resumable).

CC CDX: every page of `*.myshopify.com` for the most recent N crawls (JSON output carries `redirect` for 3xx
captures, which yields the store's custom domain). Wayback CDX: `myshopify.com` matchType=domain, collapsed by
urlkey, paged via resumeKey from a start date.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from common import INDEX_UA, add_candidates, connect, get_meta, job_done, mark_job, set_meta  # noqa: E402


def get(client, url, params, tries=7, timeout=180):
    delay = 5
    for _ in range(tries):
        try:
            r = client.get(url, params=params, timeout=timeout)
            if r.status_code in (200, 404):
                return r
        except httpx.HTTPError:
            pass
        time.sleep(delay + random.random() * 3)
        delay = min(delay * 2, 120)
    return None


def cc_cdx(con, crawls):
    with httpx.Client(headers=INDEX_UA) as c:
        info = get(c, "https://index.commoncrawl.org/collinfo.json", None).json()
        used = set(get_meta(con, "cdx_crawls", []))
        for crawl in info[:crawls]:
            api = crawl["cdx-api"]
            key = f"pages|{crawl['id']}"
            r = con.execute("SELECT info FROM jobs WHERE kind='cdxpages' AND job=?", (key,)).fetchone()
            if r:
                n = int(r[0])
            else:
                rr = get(c, api, {"url": "*.myshopify.com", "output": "json", "showNumPages": "true"})
                if rr is None or rr.status_code != 200:
                    print(f"[cdx] cannot size {crawl['id']}", flush=True)
                    continue
                n = int(rr.json()["pages"])
                mark_job(con, "cdxpages", key, "done", n, 0, str(n))
            ok = True
            for p in range(n):
                job = f"{crawl['id']}|{p}"
                if job_done(con, "cdx", job):
                    continue
                rr = get(c, api, {"url": "*.myshopify.com", "output": "json", "fl": "url,status,redirect,languages", "page": str(p)})
                if rr is None:
                    mark_job(con, "cdx", job, "failed")
                    ok = False
                    continue
                items = []
                for line in rr.text.splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    lang = rec.get("languages", "")
                    pr = 1.5 + (1 if lang.startswith("eng") else -1 if lang else 0)
                    items.append((rec.get("url", ""), pr, f"cc-cdx status={rec.get('status')}"))
                    red = rec.get("redirect")
                    if red and str(rec.get("status", "")).startswith("3"):
                        items.append((red, pr + 1.5, "myshopify-redirect (cc-cdx)"))
                new = add_candidates(con, items, f"cc-cdx-myshopify:{crawl['id']}")
                mark_job(con, "cdx", job, "done", len(items), new)
                print(f"[cdx] {job} items={len(items)} new={new}", flush=True)
                time.sleep(1.5)
            if ok:
                used.add(crawl["id"])
                set_meta(con, "cdx_crawls", sorted(used))


def wayback(con, since, page_lines, max_pages):
    state = f"myshopify.com|{since}"
    r = con.execute("SELECT info, status FROM jobs WHERE kind='wayback' AND job=?", (state,)).fetchone()
    if r and r[1] == "done":
        return
    resume = r[0] if r and r[0] else None
    total = new_total = 0
    with httpx.Client(headers=INDEX_UA) as c:
        for page in range(max_pages):
            params = [("url", "myshopify.com"), ("matchType", "domain"), ("fl", "original,statuscode"),
                      ("collapse", "urlkey"), ("limit", str(page_lines)), ("showResumeKey", "true"), ("from", since),
                      ("filter", "!original:.*(?:\\.js|\\.css|\\.png|\\.jpg|\\.gif|\\.svg|\\.woff2?)(?:\\?.*)?$")]
            if resume:
                params.append(("resumeKey", resume))
            rr = get(c, "http://web.archive.org/cdx/search/cdx", params, tries=6, timeout=300)
            if rr is None or rr.status_code != 200:
                print(f"[wayback] failed page {page}", flush=True)
                mark_job(con, "wayback", state, "partial", total, new_total, resume or "")
                return
            lines = rr.text.splitlines()
            nxt = None
            if len(lines) >= 2 and lines[-2].strip() == "":
                nxt = lines[-1].strip()
                lines = lines[:-2]
            items = []
            for ln in lines:
                parts = ln.split(" ")
                if parts and parts[0]:
                    items.append((parts[0], 1.0, f"wayback status={parts[1] if len(parts) > 1 else ''}"))
            new = add_candidates(con, items, f"wayback-myshopify:from{since}")
            total += len(items)
            new_total += new
            resume = nxt
            mark_job(con, "wayback", state, "done" if not resume else "partial", total, new_total, resume or "")
            print(f"[wayback] page={page} lines={len(lines)} new={new} total_new={new_total}", flush=True)
            if not resume:
                break
            time.sleep(3)
    ranges = set(get_meta(con, "wayback_ranges", []))
    ranges.add(f"myshopify.com from {since}")
    set_meta(con, "wayback_ranges", sorted(ranges))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", default="cdx,wayback")
    ap.add_argument("--crawls", type=int, default=8)
    ap.add_argument("--since", default="2025")
    ap.add_argument("--page-lines", type=int, default=50000)
    ap.add_argument("--max-pages", type=int, default=400)
    a = ap.parse_args()
    con = connect()
    if "wayback" in a.what:
        wayback(con, a.since, a.page_lines, a.max_pages)
    if "cdx" in a.what:
        cc_cdx(con, a.crawls)
