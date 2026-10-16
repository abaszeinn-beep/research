"""Reference universe of major/medium Saudi online stores and its resolution to Saudi storefront URLs.

  python3 -m saudi_ecom.reference load       # TSV + Tranco + Wikidata + Wikipedia sources -> reference_stores
  python3 -m saudi_ecom.reference resolve    # find Saudi storefront URLs (live variants, Bing, Wayback CDX)
  python3 -m saudi_ecom.reference link       # map refs to candidate keys / existing verified rows

Every resolved URL is queued as a normal candidate (source reference:<id>) and decided by saudi_ecom.verify /
saudi_ecom.secondary; nothing here marks a store verified by itself.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import time
from urllib.parse import urlsplit

import httpx

from . import db
from .common import identity, registrable_domain
from .discover_search import Bing
from .verify import Fetcher, SA_GEO, FOREIGN_GEO

HERE = os.path.dirname(__file__)
TSV = os.path.join(HERE, "data", "reference_brands.tsv")
RAW = os.path.join(HERE, "..", "data", "raw")
TRANCO_ID = "Y8JGG"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_stores(
  ref_id INTEGER PRIMARY KEY, name TEXT, category TEXT, tier TEXT, domains TEXT, sources TEXT,
  tranco_rank INTEGER, kind TEXT, status TEXT, best_key TEXT, best_url TEXT, reason TEXT,
  evidence TEXT, checked_at TEXT, UNIQUE(name, domains));
CREATE TABLE IF NOT EXISTS reference_urls(
  ref_id INTEGER, url TEXT, key TEXT, via TEXT, http_status INTEGER, final_url TEXT, info TEXT, ts TEXT,
  PRIMARY KEY(ref_id, url));
"""

PATH_VARIANTS = ["/sa/en/", "/sa-en/", "/en-sa/", "/sa/ar/", "/ar-sa/", "/sa-ar/", "/en_sa/", "/ar_sa/", "/saudi-en/",
                 "/sa_en/", "/ksa/en/", "/en/sa/", "/sa/", "/saudi/", "/ksa/", "/saudi-arabia/"]
HOST_VARIANTS = ["sa.{d}", "ksa.{d}", "saudi.{d}", "en-sa.{d}"]
CDX_PREFIXES = ["{d}/sa", "{d}/en-sa", "{d}/ar-sa", "{d}/en_sa", "{d}/ar_sa", "{d}/ksa", "{d}/en/sa", "{d}/ar/sa",
                "{d}/saudi", "sa.{d}/", "ksa.{d}/"]
NOT_FOUND = re.compile(r"<title>[^<]{0,80}(?:404|not found|page not found|غير موجود|الصفحة غير)", re.I)
NON_STORE_SA = re.compile(r"\.(?:gov|edu|med|sch|net|org)\.sa$|^(?:google|bing|yahoo|absher|nusuk)\.", re.I)


def connect():
    con = db.connect()
    con.executescript(SCHEMA)
    return con


def tranco_ranks():
    path = os.path.join(RAW, "tranco.csv")
    ranks = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                r, d = line.strip().split(",", 1)
                ranks[d] = int(r)
    return ranks


def upsert(con, name, category, tier, domains, sources, rank, kind):
    row = con.execute("SELECT ref_id, sources FROM reference_stores WHERE name=? AND domains=?", (name, domains)).fetchone()
    if row:
        old = json.loads(row[1] or "[]")
        merged = old + [s for s in sources if s not in old]
        con.execute("UPDATE reference_stores SET sources=?, tranco_rank=coalesce(?, tranco_rank) WHERE ref_id=?",
                    (json.dumps(merged, ensure_ascii=False), rank, row[0]))
        return row[0]
    cur = con.execute("INSERT INTO reference_stores(name,category,tier,domains,sources,tranco_rank,kind,status) VALUES(?,?,?,?,?,?,?,'pending')",
                      (name, category, tier, domains, json.dumps(sources, ensure_ascii=False), rank, kind))
    return cur.lastrowid


def load(con):
    ranks = tranco_ranks()
    n = 0
    with open(TSV, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            name, cat, tier, doms, src = line.rstrip("\n").split("\t")
            dl = doms.split()
            rank = min([ranks[registrable_domain(d)] for d in dl if registrable_domain(d) in ranks] or [None]) if ranks else None
            srcs = [src]
            if rank:
                srcs.append(f"tranco:{TRANCO_ID}#rank{rank}")
            upsert(con, name, cat, tier, " ".join(dl), srcs, rank, "brand")
            n += 1
    # Tranco .sa domains: only become part of the universe once verification shows a store (kind=tranco_sa)
    t = 0
    for d, r in ranks.items():
        if d.endswith(".sa") and not NON_STORE_SA.search(d):
            upsert(con, d, "", "major" if r <= 200_000 else "medium", d, [f"tranco:{TRANCO_ID}#rank{r}"], r, "tranco_sa")
            t += 1
    w = 0
    wpath = os.path.join(RAW, "wikidata_sa_companies.json")
    for path in (wpath, os.path.join(RAW, "wikidata_sa_retail.json")):
        if not os.path.exists(path):
            continue
        for b in json.load(open(path)):
            site = b["site"]["value"]
            d = registrable_domain(urlsplit(site).hostname or "")
            if not d:
                continue
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            upsert(con, b["itemLabel"]["value"], "", "medium", d, [f"wikidata:{qid}"], ranks.get(d), "wikidata")
            w += 1
    con.commit()
    print(f"loaded brands={n} tranco_sa={t} wikidata={w}")


def probe_urls(domain):
    d = domain.lower()
    if d.endswith(".sa"):
        return [f"https://www.{d}/", f"https://{d}/"] if not d.startswith("www.") else [f"https://{d}/"]
    host = d if d.count(".") >= 2 and not re.search(r"\.(?:co|com)\.[a-z]{2}$", d) else f"www.{d}"
    label = registrable_domain(d).split(".")[0]
    urls = [f"https://{host}{p}" for p in PATH_VARIANTS]
    urls += [f"https://{h.format(d=registrable_domain(d))}/" for h in HOST_VARIANTS]
    urls += [f"https://www.{label}.sa/", f"https://www.{label}.com.sa/"]
    return urls


def accept(st, final, html):
    if st != 200 or not final:
        return False
    host = (urlsplit(final).hostname or "").lower()
    if NOT_FOUND.search(html[:5000]):
        return False
    if FOREIGN_GEO.search(final) and not SA_GEO.search(final):
        return False
    return bool(SA_GEO.search(final) or host.endswith(".sa"))


def record(con, ref_id, url, via, st, final, info=None):
    ident = identity(final or url) or identity(url)
    con.execute("INSERT OR REPLACE INTO reference_urls VALUES(?,?,?,?,?,?,?,?)",
                (ref_id, url, ident["key"] if ident else None, via, st, final, json.dumps(info or {}, ensure_ascii=False), db.now()))


async def live_probe(f, con, ref_id, domains):
    """Try Saudi variants per domain, stop at the first accepted one. Returns (accepted, blocked_domains)."""
    accepted, blocked = [], []
    for d in domains:
        n403 = 0
        for u in probe_urls(d):
            st, final, html, _, err = await f.get(u, tries=1)
            if st in (403, 429, 503) or err == "robots_disallowed":
                n403 += 1
                if n403 >= 3:
                    blocked.append(d)
                    break
                continue
            if accept(st, final, html or ""):
                record(con, ref_id, u, "live_variant", st, final)
                accepted.append(final)
                break
    return accepted, blocked


async def cdx_probe(client, sem, con, ref_id, domain):
    d = registrable_domain(domain)
    hits = []
    for pat in CDX_PREFIXES:
        q = pat.format(d=d)
        async with sem:
            try:
                r = await client.get("https://web.archive.org/cdx/search/cdx", params={
                    "url": q, "matchType": "prefix", "from": "202604", "filter": "statuscode:200",
                    "collapse": "urlkey", "limit": "40", "fl": "timestamp,original"}, timeout=60)
            except httpx.HTTPError:
                await asyncio.sleep(3)
                continue
            await asyncio.sleep(1.0)
        if r.status_code != 200:
            continue
        for line in r.text.splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2 and SA_GEO.search(parts[1]):
                hits.append(parts)
        if hits:
            break
    if hits:
        hits.sort(reverse=True)
        sp = urlsplit(hits[0][1])
        segs = [s for s in sp.path.split("/") if s][:2]
        keep = []
        for s in segs:
            keep.append(s)
            if SA_GEO.search("/" + "/".join(keep) + "/"):
                break
        base = f"https://{sp.hostname}/" + ("/".join(keep) + "/" if keep and SA_GEO.search("/" + "/".join(keep) + "/") else "")
        record(con, ref_id, base, "wayback_cdx", None, base, {"captures": hits[:10]})
        return base
    return None


async def bing_probe(bing, con, ref_id, name, domains):
    labels = {registrable_domain(d).split(".")[0] for d in domains}
    clean = re.sub(r"^[^:]+:\s*", "", name.split("/")[0]).strip()
    found = []
    for q in (f"{clean} السعودية متجر اونلاين", f"{clean} Saudi Arabia online store"):
        urls = await bing.search(q) or []
        for u in urls:
            host = (urlsplit(u).hostname or "").lower()
            root = registrable_domain(host)
            if not (root in {registrable_domain(d) for d in domains} or any(l and len(l) >= 4 and l in host for l in labels)):
                continue
            if SA_GEO.search(u) or host.endswith(".sa"):
                found.append(u)
        if found:
            break
    for u in found[:2]:
        record(con, ref_id, u, "bing", None, u)
    return found[:2]


async def resolve(con, kinds, limit, use_bing, use_cdx):
    refs = con.execute(f"SELECT ref_id, name, domains FROM reference_stores WHERE kind IN ({','.join('?'*len(kinds))}) "
                       "AND ref_id NOT IN (SELECT DISTINCT ref_id FROM reference_urls) ORDER BY tranco_rank IS NULL, tranco_rank LIMIT ?",
                       (*kinds, limit)).fetchall()
    print(f"[reference] resolving {len(refs)} refs", flush=True)
    f = Fetcher(48, 2)
    sem = asyncio.Semaphore(2)
    stats = {"accepted": 0, "blocked": 0, "cdx": 0, "bing": 0, "none": 0}
    async with httpx.AsyncClient(headers={"User-Agent": "saudi-ecom-directory-research/1.0 (polite CDX client)"}) as cdx_client, \
            httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                                       "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"}, follow_redirects=True) as bclient:
        bing = Bing(bclient)

        async def one(ref_id, name, doms):
            domains = doms.split()
            acc, blocked = await live_probe(f, con, ref_id, domains)
            if acc:
                stats["accepted"] += 1
            if blocked:
                stats["blocked"] += 1
            if not acc and use_cdx:
                for d in blocked or domains:
                    if await cdx_probe(cdx_client, sem, con, ref_id, d):
                        stats["cdx"] += 1
                        acc = [d]
                        break
            if not acc and use_bing:
                if await bing_probe(bing, con, ref_id, name, domains):
                    stats["bing"] += 1
                    acc = ["bing"]
            if not acc:
                stats["none"] += 1
                con.execute("INSERT OR REPLACE INTO reference_urls VALUES(?,?,?,?,?,?,?,?)",
                            (ref_id, "-", None, "none", None, None, json.dumps({"blocked": blocked}), db.now()))
            con.commit()

        tasks = [one(*r) for r in refs]
        done = 0
        for chunk in range(0, len(tasks), 24):
            await asyncio.gather(*tasks[chunk:chunk + 24])
            done += len(tasks[chunk:chunk + 24])
            print(f"[reference] {done}/{len(refs)} {stats}", flush=True)
    await f.client.aclose()


def link(con):
    """Queue resolved URLs as candidates (source reference:<id>), re-verifying ones not yet verified."""
    rows = con.execute("SELECT ref_id, url, final_url, via FROM reference_urls WHERE url!='-'").fetchall()
    n = 0
    for ref_id, url, final, via in rows:
        u = final or url
        ident = identity(u)
        if not ident:
            continue
        db.add_candidates(con, [(u, 10)], f"reference:{via}", f"ref {ref_id}", 10)
        st = con.execute("SELECT status FROM candidates WHERE key=?", (ident["key"],)).fetchone()
        if st and st[0] in ("rejected", "unverified"):
            con.execute("UPDATE candidates SET status='pending', priority=10 WHERE key=? AND status IN ('rejected','unverified')", (ident["key"],))
        con.execute("UPDATE reference_urls SET key=? WHERE ref_id=? AND url=?", (ident["key"], ref_id, url))
        n += 1
    # Tranco .sa and Wikidata entries are verified directly from their root domain
    for ref_id, doms, kind in con.execute("SELECT ref_id, domains, kind FROM reference_stores WHERE kind IN ('tranco_sa','wikidata')").fetchall():
        d = doms.split()[0]
        u = f"https://{d}/"
        ident = identity(u)
        if ident:
            db.add_candidates(con, [(u, 8)], f"reference:{kind}", f"ref {ref_id}", 8)
            con.execute("INSERT OR IGNORE INTO reference_urls VALUES(?,?,?,?,?,?,?,?)", (ref_id, u, ident["key"], kind, None, u, "{}", db.now()))
            n += 1
    con.commit()
    print(f"linked {n} urls")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "resolve", "link"])
    ap.add_argument("--kinds", default="brand")
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--no-bing", action="store_true")
    ap.add_argument("--no-cdx", action="store_true")
    a = ap.parse_args()
    con = connect()
    if a.cmd == "load":
        load(con)
    elif a.cmd == "resolve":
        asyncio.run(resolve(con, a.kinds.split(","), a.limit, not a.no_bing, not a.no_cdx))
    else:
        link(con)
