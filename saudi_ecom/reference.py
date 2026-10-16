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
CDX_PREFIXES = ["{d}/sa", "{d}/en-sa", "{d}/ar-sa", "sa.{d}/", "{d}/en_sa", "{d}/ar_sa"]
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
    sem = asyncio.Semaphore(4)
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
                for d in blocked:
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

        pool = asyncio.Semaphore(32)
        done = 0

        async def pooled(r):
            nonlocal done
            async with pool:
                await one(*r)
            done += 1
            if done % 10 == 0 or done == len(refs):
                print(f"[reference] {done}/{len(refs)} {stats}", flush=True)
        await asyncio.gather(*(pooled(r) for r in refs))
    await f.client.aclose()


async def retry_none(con):
    """Second pass for refs where live variants found nothing (often geo-redirects from this non-Saudi VM):
    look for recent archived captures under Saudi paths of every known domain."""
    refs = con.execute("SELECT r.ref_id, r.domains FROM reference_stores r JOIN reference_urls u ON u.ref_id=r.ref_id AND u.via='none' WHERE r.kind='brand'").fetchall()
    print(f"[reference] cdx retry for {len(refs)} refs", flush=True)
    sem = asyncio.Semaphore(4)
    found = 0
    async with httpx.AsyncClient(headers={"User-Agent": "saudi-ecom-directory-research/1.0 (polite CDX client)"}) as client:
        async def one(ref_id, doms):
            nonlocal found
            for d in doms.split():
                if await cdx_probe(client, sem, con, ref_id, d):
                    con.execute("DELETE FROM reference_urls WHERE ref_id=? AND via='none'", (ref_id,))
                    found += 1
                    break
            con.commit()
        pool = asyncio.Semaphore(8)

        async def pooled(r):
            async with pool:
                await one(*r)
        await asyncio.gather(*(pooled(r) for r in refs))
    print(f"[reference] cdx retry found {found}/{len(refs)}", flush=True)


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


EXCLUDE_REASONS = [
    (re.compile(r"^excluded_marketplace"), "excluded: marketplace / aggregator"),
    (re.compile(r"digital_products_only|likely_digital_only"), "excluded: digital goods only"),
    (re.compile(r"services_only|mostly_services|likely_services"), "excluded: services only"),
    (re.compile(r"restaurant_or_food_service"), "excluded: restaurant / food service"),
    (re.compile(r"redirects_to_non_saudi_storefront|not_saudi_relevant|non_saudi_shopify"), "excluded: no Saudi storefront (site serves another country)"),
    (re.compile(r"no_ecommerce_evidence"), "excluded: no online ordering on Saudi site (brand/info site)"),
    (re.compile(r"store_closed|store_not_launched|parked"), "excluded: store closed / not launched"),
    (re.compile(r"charity_or_donations"), "excluded: charity"),
]


def audit(con, previous_csv=None):
    """Assign each reference store a coverage status. Returns list of dict rows for the audit sheet."""
    from .common import MARKETPLACE_ROOTS
    prev = set()
    if previous_csv and os.path.exists(previous_csv):
        with open(previous_csv, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                prev.add(r["Root Domain / Storefront URL"].rstrip("/"))
    ver = {}
    for key, root, st, vst, dup, furl, curl, reason, method, ev_url, vat in con.execute(
            """SELECT c.key, c.root_domain, c.status, v.status, v.duplicate_of, v.final_url, c.url, v.reason, v.method, v.evidence_url, v.verified_at
               FROM candidates c LEFT JOIN verifications v USING(key)"""):
        ver[key] = dict(key=key, root=root, cstatus=st, vstatus=vst, dup=dup, final=furl, url=curl, reason=reason or "", method=method,
                        ev_url=ev_url, ts=vat)
    by_root = {}
    for k, r in ver.items():
        by_root.setdefault(r["root"], []).append(k)
    mapped = {}
    for ref_id, key, via in con.execute("SELECT ref_id, key, via FROM reference_urls WHERE key IS NOT NULL"):
        mapped.setdefault(ref_id, []).append(key)
    sec = {k: (v, e) for k, v, e in con.execute("SELECT key, verdict, evidence FROM secondary_evidence")} if con.execute(
        "SELECT name FROM sqlite_master WHERE name='secondary_evidence'").fetchone() else {}
    nones = {r[0]: json.loads(r[1] or "{}") for r in con.execute("SELECT ref_id, info FROM reference_urls WHERE via='none'")}

    def master_of(k):
        r = ver.get(k)
        while r and r["cstatus"] == "duplicate" and r["dup"] and r["dup"] in ver and r["dup"] != r["key"]:
            r = ver[r["dup"]]
        return r

    rows = []
    for ref_id, name, cat, tier, doms, sources, rank, kind in con.execute(
            "SELECT ref_id, name, category, tier, domains, sources, tranco_rank, kind FROM reference_stores"):
        domains = doms.split()
        roots = {registrable_domain(d) for d in domains}
        labels = {r.split(".")[0] for r in roots}
        alt = set(roots) | {f"{l}.sa" for l in labels} | {f"{l}.com.sa" for l in labels} | {f"{l}-sa.com" for l in labels} | {f"{l}sa.com" for l in labels} | {f"{l}ksa.com" for l in labels}
        keys = set(mapped.get(ref_id, []))
        for r in alt:
            keys.update(by_root.get(r, []))
        cands = [master_of(k) for k in keys if k in ver]
        cands = [c for c in cands if c]
        good = [c for c in cands if c["cstatus"] == "verified" and c["vstatus"] in ("verified", "verified_secondary_evidence")]
        status, url, reason, evidence, key = None, "", "", "", None
        if any(r in MARKETPLACE_ROOTS for r in roots):
            status, reason = "excluded", "excluded: marketplace / aggregator (" + MARKETPLACE_ROOTS[[r for r in roots if r in MARKETPLACE_ROOTS][0]] + ")"
        elif good:
            good.sort(key=lambda c: (c["vstatus"] != "verified", not SA_GEO.search(c["final"] or c["url"] or ""), len(c["key"])))
            g = good[0]
            key = g["key"]
            url = g["final"] or g["url"]
            from .export import master_url
            murl = master_url({"final_url": g["final"], "url": g["url"]})
            url = murl
            primary = g["vstatus"] == "verified"
            status = "in_directory_primary" if primary else "in_directory_secondary"
            was = murl.rstrip("/") in prev
            reason = ("already present before reference audit" if was else "added by reference audit") + ("" if primary else " (secondary evidence)")
            evidence = (g["reason"] or "") + (f" | evidence: {g['ev_url']}" if g["ev_url"] else "") + f" | checked {g['ts']}"
        else:
            exc = None
            for c in cands:
                for rx, label in EXCLUDE_REASONS:
                    if rx.search(c["reason"] or ""):
                        exc = (label, c)
                        break
                if exc:
                    break
            blocked = [c for c in cands if re.search(r"blocked|challenge|robots|rate_limited|js_rendered|partial|insufficient|weak|timeout|fetch_failed|http_5", c["reason"] or "")]
            if blocked:
                b = blocked[0]
                key = b["key"]
                url = b["final"] or b["url"]
                s = sec.get(b["key"])
                ev_types = [e["type"] for e in json.loads(s[1])] if s else []
                oks = [e for e in json.loads(s[1]) if e.get("ok")] if s else []
                status = "unresolved"
                reason = f"unresolved: live check '{b['reason'][:60]}'" + (f"; secondary evidence insufficient ({', '.join(e['type'] for e in oks) or 'none'} of {', '.join(ev_types)})" if s else "; secondary evidence not yet collected")
                evidence = " | ".join(f"{e['type']}: {e.get('detail')} ({e.get('url')}, {e.get('date')})" for e in oks)
            elif exc:
                status, reason = "excluded", exc[0]
                key, url, evidence = exc[1]["key"], exc[1]["final"] or exc[1]["url"], exc[1]["reason"][:200]
            elif cands:
                c = cands[0]
                status, key, url = "excluded", c["key"], c["final"] or c["url"]
                reason = "excluded: no working Saudi storefront found (" + (c["reason"] or c["cstatus"])[:80] + ")"
            else:
                status = "excluded"
                info = nones.get(ref_id, {})
                reason = "excluded: no Saudi storefront found (Saudi URL variants" + (", Wayback CDX" if info.get("blocked") else "") + " checked)"
        if kind in ("tranco_sa", "wikidata") and status != "in_directory_primary" and status != "in_directory_secondary":
            status = "screened_out"
        con.execute("UPDATE reference_stores SET status=?, best_key=?, best_url=?, reason=?, evidence=?, checked_at=? WHERE ref_id=?",
                    (status, key, url, reason, evidence, db.now(), ref_id))
        rows.append(dict(ref_id=ref_id, name=name, category=cat, tier=tier, domains=doms, sources=", ".join(json.loads(sources)),
                         tranco_rank=rank, kind=kind, status=status, url=url, key=key, reason=reason, evidence=evidence))
    con.commit()
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "resolve", "retry-none", "link", "audit"])
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
    elif a.cmd == "retry-none":
        asyncio.run(retry_none(con))
    elif a.cmd == "audit":
        import collections
        rows = audit(con, os.path.join(HERE, "..", "data", "previous_master_16cd9b5.csv"))
        print(collections.Counter((r["kind"], r["status"]) for r in rows))
    else:
        link(con)
