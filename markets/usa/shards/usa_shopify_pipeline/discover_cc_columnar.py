"""Common Crawl columnar (Parquet) index discovery over plain HTTPS (no Athena, no AWS account).

Per crawl and per Parquet part (resumable via jobs table):
  * `*.myshopify.com` captures (warc + crawldiagnostics subsets) incl. `fetch_redirect` targets, which
    reveal the custom primary domain of many myshopify stores;
  * custom-domain hosts whose captured URL paths carry Shopify-specific storefront fingerprints:
    `/collections/<c>/products/<p>`, `/cdn/shop/...`, `/products/<p>?variant=<id>`, or `/products/<p>` together
    with `/collections/...` on the same host.
Only url_* / fetch_* / content_languages columns are read (DuckDB httpfs range requests).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import os
import sys
import time
import urllib.request

import duckdb

sys.path.insert(0, os.path.dirname(__file__))
from common import FOREIGN_CC, add_candidates, connect, job_done, mark_job, set_meta, get_meta  # noqa: E402

BASE = "https://data.commoncrawl.org/"

CUSTOM_SQL = """
SELECT url_host_name, any_value(url_host_tld) tld, count(*) n,
  count(*) FILTER (WHERE regexp_matches(url_path, '^/(?:[a-z]{2}(?:-[a-z]{2})?/)?collections/[^/]+/products/[^/]+')) cp,
  count(*) FILTER (WHERE starts_with(url_path, '/cdn/shop/')) cdn,
  count(*) FILTER (WHERE regexp_matches(url_path, '^/(?:[a-z]{2}(?:-[a-z]{2})?/)?products/[^/]+/?$')) p,
  count(*) FILTER (WHERE regexp_matches(url_path, '^/(?:[a-z]{2}(?:-[a-z]{2})?/)?products/[^/]+/?$') AND url_query LIKE '%variant=%') pv,
  count(*) FILTER (WHERE regexp_matches(url_path, '^/(?:[a-z]{2}(?:-[a-z]{2})?/)?collections/')) c,
  count(*) FILTER (WHERE regexp_matches(url_path, '^/en-us(?:/|$)')) enus,
  mode(content_languages) lang
FROM read_parquet('{url}')
WHERE url_host_registered_domain IS DISTINCT FROM 'myshopify.com'
GROUP BY 1
HAVING cp > 0 OR cdn > 0 OR pv > 0 OR (p > 0 AND c > 0)
"""

MYSHOP_SQL = """
SELECT url_host_name, fetch_status, fetch_redirect, content_languages
FROM read_parquet('{url}')
WHERE url_surtkey >= 'com,myshopify,' AND url_surtkey < 'com,myshopify-'
"""


def list_parts(crawl):
    with urllib.request.urlopen(f"{BASE}crawl-data/{crawl}/cc-index-table.paths.gz", timeout=120) as r:
        data = gzip.decompress(r.read()).decode()
    return [p for p in data.splitlines() if p.strip()]


def duck():
    c = duckdb.connect()
    c.sql("INSTALL httpfs; LOAD httpfs;")
    c.sql("SET threads=4")
    c.sql("SET enable_progress_bar=false")
    c.sql("SET http_retries=6; SET http_retry_wait_ms=2000; SET http_timeout=120000")
    return c


def custom_items(rows):
    items = []
    for host, tld, n, cp, cdn, p, pv, c, enus, lang in rows:
        pr = 2.0
        strength = cp + cdn + pv
        pr += 2 if strength >= 3 or cdn else 1 if strength else 0
        lang = lang or ""
        if lang.startswith("eng"):
            pr += 1
        elif lang:
            pr -= 1.5
        if enus:
            pr += 0.5
        if (tld or "") in ("com", "us", "shop", "store", "co"):
            pr += 0.5
        items.append((host, pr, f"cc-columnar n={n} cp={cp} cdn={cdn} pv={pv} p={p} c={c} lang={lang[:20]}"))
    return items


def myshop_items(rows):
    items = []
    for host, status, redirect, lang in rows:
        lang = lang or ""
        pr = 1.5 + (1 if lang.startswith("eng") else -1 if lang else 0)
        items.append((host, pr, f"cc-columnar status={status}"))
        if redirect and status and 300 <= int(status) < 400:
            items.append((redirect, pr + 1.5, f"myshopify-redirect from {host}"))
    return items


def run_part(path, kind):
    url = BASE + path
    c = duck()
    err = None
    for attempt in range(5):
        try:
            if kind == "custom":
                return custom_items(c.sql(CUSTOM_SQL.replace("{url}", url)).fetchall())
            return myshop_items(c.sql(MYSHOP_SQL.replace("{url}", url)).fetchall())
        except Exception as e:
            err = e
            time.sleep(min(60, 4 * 2 ** attempt))
    raise err


def main(crawls, workers, myshop_only, skip):
    con = connect()
    req = urllib.request.Request("https://index.commoncrawl.org/collinfo.json", headers={"User-Agent": "usa-ecom-research"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                info = json.loads(r.read())
            break
        except Exception:
            time.sleep(5 * 2 ** attempt)
    ids = [x["id"] for x in info][skip:skip + crawls]
    used = set(get_meta(con, "columnar_crawls", []))
    for crawl in ids:
        parts = list_parts(crawl)
        warc = [p for p in parts if "/subset=warc/" in p]
        diag = [p for p in parts if "/subset=crawldiagnostics/" in p]
        jobs = [(p, "myshop") for p in warc + diag]
        if not myshop_only:
            jobs += [(p, "custom") for p in warc]
        todo = [(p, k) for p, k in jobs if not job_done(con, "columnar", f"{k}|{p}")]
        print(f"[columnar] {crawl}: {len(todo)} part-jobs to run", flush=True)
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(run_part, p, k): (p, k) for p, k in todo}
            for fu in cf.as_completed(futs):
                p, k = futs[fu]
                try:
                    items = fu.result()
                except Exception as e:
                    print(f"[columnar] FAIL {k} {p}: {e}", flush=True)
                    mark_job(con, "columnar", f"{k}|{p}", "failed", info=str(e)[:200])
                    continue
                src = "cc-columnar-myshopify" if k == "myshop" else "cc-columnar-shopify-paths"
                new = add_candidates(con, items, f"{src}:{crawl}")
                mark_job(con, "columnar", f"{k}|{p}", "done", len(items), new)
                if items:
                    print(f"[columnar] {crawl} {k} {p.rsplit('/', 1)[-1][:10]} items={len(items)} new={new}", flush=True)
        used.add(crawl)
        set_meta(con, "columnar_crawls", sorted(used))
    print("[columnar] done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawls", type=int, default=8)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--myshop-only", action="store_true")
    a = ap.parse_args()
    main(a.crawls, a.workers, a.myshop_only, a.skip)
