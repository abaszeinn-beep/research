"""Common Crawl columnar-index (parquet over HTTPS) scan for non-Shopify platform URL fingerprints.

Each `subset=warc` part file of a crawl is queried with DuckDB (only the url/host/status/mime/language
columns are read via HTTP range requests). Hosts whose crawled URLs match a platform-specific path
fingerprint, or which live on a platform hosting suffix, become candidates. Resumable per part file.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import io
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import httpx

from . import db
from .common_us import MARKETPLACE_ROOTS, identity

BASE = "https://data.commoncrawl.org/"

HOSTED = [
    ("mybigcommerce.com", "bigcommerce"), ("bigcartel.com", "bigcartel"), ("square.site", "square"),
    ("company.site", "ecwid"), ("3dcartstores.com", "shift4shop"), ("myvolusion.com", "volusion"),
    ("volusion.store", "volusion"),
]

# (platform, SQL condition on p=lower(url_path), q=lower(url_query)); RE2 syntax.
RULES = [
    ("salesforce-commerce", r"regexp_matches(p, '/on/demandware\.store/|/demandware\.static/')"),
    ("magento", r"regexp_matches(p, '^/(?:[a-z]{2}(?:[-_][a-z]{2})?/)?(?:customer/account/(?:login|create)|catalog/product/view/|catalogsearch/result)')"),
    ("bigcommerce", r"((regexp_matches(p, '^/(?:giftcertificates|cart)\.php$') and q not like 'a=%' and q not like '%&a=%') or (p = '/login.php' and q like '%action=create_account%'))"),
    ("volusion", r"regexp_matches(p, '-p/[^/]+\.htm$|-s/\d+\.htm$|^/productdetails\.asp$|^/shoppingcart\.asp$')"),
    ("shift4shop", r"regexp_matches(p, '_p_\d+\.html$|_c_\d+\.html$|^/view_cart\.asp$')"),
    ("prestashop", r"(regexp_matches(q, '(?:^|&)id_product=\d') or regexp_matches(q, '(?:^|&)controller=(?:cart|authentication|order)(?:&|$)') or regexp_matches(p, '^/(?:[a-z]{2}/)?content/\d+-[a-z]'))"),
    ("opencart", r"regexp_matches(q, '(?:^|&)route=(?:product/product|product/category|checkout/cart|account/login)')"),
    ("shopware", r"(regexp_matches(p, '^/detail/[0-9a-f]{32}$|^/widgets/(?:checkout|listing)/') or q like '%sviewport=%')"),
    ("wix", r"regexp_matches(p, '/product-page/[^/]+/?$')"),
    ("ecwid", r"regexp_matches(p, '-p\d{6,}$|-c\d{6,}$')"),
    ("squarespace", r"regexp_matches(p, '^/[a-z0-9-]+/p/[a-z0-9-]+$')"),
    ("square", r"regexp_matches(p, '^/s/(?:shop|order|search)$|^/product/[a-z0-9-]+/[0-9a-z]{1,30}$')"),
    ("woocommerce", r"(regexp_matches(p, '/product-category/[^/]+') or regexp_matches(q, '(?:^|&)add-to-cart=\d') or p like '/wp-json/wc/%')"),
]
PLAT_WEIGHT = {"salesforce-commerce": 3, "bigcommerce": 3, "magento": 2, "volusion": 3, "shift4shop": 3, "bigcartel": 2,
               "square": 1.5, "ecwid": 2, "wix": 2, "squarespace": 1.5, "prestashop": 1, "opencart": 1, "shopware": 1,
               "woocommerce": 1.5}


def build_sql(url: str) -> str:
    hosted = " ".join(f"when h like '%.{suf}' then '{plat}'" for suf, plat in HOSTED)
    rules = " ".join(f"when {cond} then '{plat}'" for plat, cond in RULES)
    return f"""
    with t as (
      select url_host_name h, url_host_tld tld, lower(url_path) p, lower(coalesce(url_query,'')) q, url,
             coalesce(content_languages,'') lang
      from read_parquet('{url}')
      where fetch_status = 200 and content_mime_detected in ('text/html','application/xhtml+xml')
        and (length(url_host_tld) > 2 or url_host_tld in ('us','co','io','me','ai','tv','ly','gg','to','cc','la','ws','fm'))
        and (content_languages is null or content_languages like 'eng%')
    ), m as (
      select h, tld, lang, url, case {hosted} {rules} else null end plat from t
    )
    select h, tld, plat, count(*) n, min(url) smp, max(lang) lng from m where plat is not null group by h, tld, plat
    """


def crawl_parts(client, crawl):
    r = client.get(f"{BASE}crawl-data/{crawl}/cc-index-table.paths.gz", timeout=60)
    r.raise_for_status()
    lines = gzip.GzipFile(fileobj=io.BytesIO(r.content)).read().decode().split()
    return [x for x in lines if "/subset=warc/" in x]


_local = threading.local()


def _con():
    if not hasattr(_local, "con"):
        c = duckdb.connect()
        c.execute("INSTALL httpfs; LOAD httpfs; SET threads=2; SET memory_limit='600MB'; SET preserve_insertion_order=false; SET http_timeout=120000; SET http_retries=6;")
        _local.con = c
    return _local.con


def scan_part(path):
    url = BASE + path
    delay = 5
    for attempt in range(6):
        try:
            return _con().execute(build_sql(url)).fetchall()
        except (duckdb.ParserException, duckdb.BinderException, duckdb.InvalidInputException):
            raise
        except Exception as e:  # network hiccups / 503 from CloudFront
            err = e
            time.sleep(delay + random.random() * 3)
            delay = min(delay * 2, 90)
    raise err


def to_candidates(rows, crawl):
    agg = {}
    for h, tld, plat, n, sample, lang in rows:
        ident = identity(sample)
        if not ident or ident["root_domain"] in MARKETPLACE_ROOTS:
            continue
        k = ident["key"]
        hint = ident["platform_hint"] or plat
        a = agg.setdefault(k, {**ident, "platform_hint": hint, "hits": 0, "sample_url": sample, "lang": lang[:20], "tld": tld,
                               "plats": collections.Counter()})
        a["hits"] += n
        a["plats"][plat] += n
    out = []
    for k, a in agg.items():
        plat = a["plats"].most_common(1)[0][0]
        if a["platform_hint"] in (None, "") or a["platform_hint"] not in a["plats"]:
            a["platform_hint"] = a["platform_hint"] or plat
        n = a["hits"]
        pr = PLAT_WEIGHT.get(a["platform_hint"], 1) + (2 if n >= 20 else 1 if n >= 3 else 0) + (1 if a["tld"] == "us" else 0)
        a["priority"] = pr
        a.pop("plats")
        out.append(a)
    return out


def main(crawls, workers, limit_parts):
    con = db.connect()
    lock = threading.Lock()
    stats = collections.Counter()
    with httpx.Client(headers={"User-Agent": "usa-ecom-directory-research/1.0"}) as client:
        jobs = []
        for crawl in crawls:
            parts = crawl_parts(client, crawl)
            if limit_parts:
                parts = parts[:limit_parts]
            for p in parts:
                job = f"{crawl}|{p.rsplit('/', 1)[-1][:10]}"
                if not db.job_done(con, "ccparquet", job):
                    jobs.append((crawl, p, job))
    print(f"[ccpq] {len(jobs)} part files to scan", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(scan_part, p): (crawl, p, job) for crawl, p, job in jobs}
        for fu in as_completed(futs):
            crawl, p, job = futs[fu]
            try:
                rows = fu.result()
            except Exception as e:
                print(f"[ccpq] FAILED {job}: {str(e)[:200]}", flush=True)
                stats["failed"] += 1
                continue
            cands = to_candidates(rows, crawl)
            with lock:
                new = db.add_candidates(con, cands, source="commoncrawl-columnar", detail=crawl)
                db.mark_job(con, "ccparquet", job, "done", len(cands), new)
            stats["parts"] += 1
            stats["new"] += new
            by = collections.Counter(c["platform_hint"] for c in cands)
            print(f"[ccpq] {job} rows={len(rows)} keys={len(cands)} new={new} total_new={stats['new']} "
                  f"{dict(by.most_common(6))} ({(time.time() - t0) / stats['parts']:.1f}s/part)", flush=True)
    print("[ccpq] done", dict(stats), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawls", default="CC-MAIN-2026-39,CC-MAIN-2026-34,CC-MAIN-2026-30")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-parts", type=int, default=0)
    a = ap.parse_args()
    main(a.crawls.split(","), a.workers, a.limit_parts)
