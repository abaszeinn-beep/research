"""Reference universe of major/medium online stores for the active market and its resolution to market storefront URLs.

  python3 -m market_ecom.reference load       # TSV + Tranco + Wikidata + Wikipedia sources -> reference_stores
  python3 -m market_ecom.reference resolve    # find market storefront URLs (live variants, DuckDuckGo, Wayback CDX)
  python3 -m market_ecom.reference link       # map refs to candidate keys / existing verified rows

Every resolved URL is queued as a normal candidate (source reference:<id>) and decided by market_ecom.verify /
market_ecom.secondary; nothing here marks a store verified by itself.
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
from .discover_search import DDG
from .verify import Fetcher, MARKET_GEO, FOREIGN_GEO
from .market import M

HERE = os.path.dirname(__file__)
TSV = os.path.join(HERE, "data", "reference_brands.tsv")
FRANCHISE_TSV = os.path.join(HERE, "data", "franchise_groups.tsv")
RAW = os.path.join(HERE, "..", "data", "raw")
TRANCO_ID = "64VVX"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_stores(
  ref_id INTEGER PRIMARY KEY, name TEXT, category TEXT, tier TEXT, domains TEXT, sources TEXT,
  tranco_rank INTEGER, kind TEXT, status TEXT, best_key TEXT, best_url TEXT, reason TEXT,
  evidence TEXT, checked_at TEXT, UNIQUE(name, domains));
CREATE TABLE IF NOT EXISTS reference_urls(
  ref_id INTEGER, url TEXT, key TEXT, via TEXT, http_status INTEGER, final_url TEXT, info TEXT, ts TEXT,
  PRIMARY KEY(ref_id, url));
"""

_c, _w = M.code, M.path_words[0]
PATH_VARIANTS = [f"/{_c}/en/", f"/{_c}-en/", f"/en-{_c}/", f"/{_c}/ar/", f"/ar-{_c}/", f"/{_c}-ar/", f"/en_{_c}/", f"/ar_{_c}/",
                 f"/{_w}-en/", f"/{_c}_en/", f"/en/{_c}/", f"/{_c}/", f"/{_w}/", f"/{_w}-ar/"]
HOST_VARIANTS = [f"{_c}.{{d}}", f"{_w}.{{d}}", f"en-{_c}.{{d}}"]
CDX_PREFIXES = [f"{{d}}/{_c}", f"{{d}}/en-{_c}", f"{{d}}/ar-{_c}", f"{_c}.{{d}}/", f"{{d}}/{_w}", f"{{d}}/en_{_c}"]
NOT_FOUND = re.compile(r"<title>[^<]{0,80}(?:404|not found|page not found|غير موجود|الصفحة غير)", re.I)
NON_STORE_CC = re.compile(r"\.(?:gov|edu|med|sch|net|org|mil)\." + M.tld + r"$|^(?:google|bing|yahoo|registry|domains)\.", re.I)


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
    row = con.execute("SELECT ref_id, sources, domains FROM reference_stores WHERE name=? AND domains=?", (name, domains)).fetchone()
    if not row and kind in ("brand", "mall"):
        row = con.execute("SELECT ref_id, sources, domains FROM reference_stores WHERE name=? AND kind=?", (name, kind)).fetchone()
    if row:
        old = json.loads(row[1] or "[]")
        merged = old + [s for s in sources if s not in old]
        old_doms = (row[2] or "").split()
        new_doms = domains.split()
        labels = {d.split(".")[0].replace("-", "") for d in new_doms}
        extra = []
        for d in old_doms:
            lab = d.split(".")[0].replace("-", "")
            if d not in new_doms and (lab in labels or M.is_cctld_host(d)) and d not in extra:
                extra.append(d)
        con.execute("UPDATE reference_stores SET sources=?, domains=?, category=CASE WHEN ?!='' THEN ? ELSE category END, tier=?, tranco_rank=coalesce(?, tranco_rank) WHERE ref_id=?",
                    (json.dumps(merged, ensure_ascii=False), " ".join(new_doms + extra), category, category, tier, rank, row[0]))
        return row[0]
    cur = con.execute("INSERT INTO reference_stores(name,category,tier,domains,sources,tranco_rank,kind,status) VALUES(?,?,?,?,?,?,?,'pending')",
                      (name, category, tier, domains, json.dumps(sources, ensure_ascii=False), rank, kind))
    return cur.lastrowid


def load(con):
    ranks = tranco_ranks()
    n = 0
    for path in (TSV, FRANCHISE_TSV):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
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
    # Tranco ccTLD domains: only become part of the universe once verification shows a store (kind=tranco_cc)
    t = 0
    for d, r in ranks.items():
        if M.is_cctld_host(d) and not NON_STORE_CC.search(d):
            upsert(con, d, "", "major" if r <= 200_000 else "medium", d, [f"tranco:{TRANCO_ID}#rank{r}"], r, "tranco_cc")
            t += 1
    w = 0
    wpath = os.path.join(RAW, f"wikidata_{M.code}_companies.json")
    for path in (wpath, os.path.join(RAW, f"wikidata_{M.code}_retail.json")):
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
    print(f"loaded brands={n} tranco_cc={t} wikidata={w}")


def probe_urls(domain):
    d = domain.lower()
    if M.is_cctld_host(d):
        return [f"https://www.{d}/", f"https://{d}/"] if not d.startswith("www.") else [f"https://{d}/"]
    host = d if d.count(".") >= 2 and not re.search(r"\.(?:co|com)\.[a-z]{2}$", d) else f"www.{d}"
    label = registrable_domain(d).split(".")[0]
    urls = [f"https://{host}{p}" for p in PATH_VARIANTS]
    urls += [f"https://{h.format(d=registrable_domain(d))}/" for h in HOST_VARIANTS]
    urls += [f"https://www.{label}.{M.tld}/", f"https://www.{label}.com.{M.tld}/"]
    return urls


def accept(st, final, html):
    if st != 200 or not final:
        return False
    host = (urlsplit(final).hostname or "").lower()
    if NOT_FOUND.search(html[:5000]):
        return False
    if FOREIGN_GEO.search(final) and not MARKET_GEO.search(final):
        return False
    return bool(MARKET_GEO.search(final) or M.is_cctld_host(host))


def record(con, ref_id, url, via, st, final, info=None):
    ident = identity(final or url) or identity(url)
    con.execute("INSERT OR REPLACE INTO reference_urls VALUES(?,?,?,?,?,?,?,?)",
                (ref_id, url, ident["key"] if ident else None, via, st, final, json.dumps(info or {}, ensure_ascii=False), db.now()))


async def live_probe(f, con, ref_id, domains):
    """Try market variants per domain, stop at the first accepted one. Returns (accepted, blocked_domains)."""
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
            if len(parts) == 2 and MARKET_GEO.search(parts[1]):
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
            if MARKET_GEO.search("/" + "/".join(keep) + "/"):
                break
        base = f"https://{sp.hostname}/" + ("/".join(keep) + "/" if keep and MARKET_GEO.search("/" + "/".join(keep) + "/") else "")
        record(con, ref_id, base, "wayback_cdx", None, base, {"captures": hits[:10]})
        return base
    return None


async def ddg_probe(engine, con, ref_id, name, domains):
    labels = {registrable_domain(d).split(".")[0] for d in domains}
    clean = re.sub(r"^[^:]+:\s*", "", name.split("/")[0]).strip()
    found = []
    for q in (f"{clean} {M.country} online store", f"{clean} {M.country_ar} تسوق اونلاين"):
        urls = await engine.search(q) or []
        for u in urls:
            host = (urlsplit(u).hostname or "").lower()
            root = registrable_domain(host)
            if not (root in {registrable_domain(d) for d in domains} or any(l and len(l) >= 4 and l in host for l in labels)):
                continue
            if MARKET_GEO.search(u) or M.is_cctld_host(host):
                found.append(u)
        if found:
            break
    for u in found[:2]:
        record(con, ref_id, u, "ddg", None, u)
    return found[:2]


async def resolve(con, kinds, limit, use_bing, use_cdx):
    refs = con.execute(f"SELECT ref_id, name, domains FROM reference_stores WHERE kind IN ({','.join('?'*len(kinds))}) "
                       "AND ref_id NOT IN (SELECT DISTINCT ref_id FROM reference_urls) ORDER BY tranco_rank IS NULL, tranco_rank LIMIT ?",
                       (*kinds, limit)).fetchall()
    print(f"[reference] resolving {len(refs)} refs", flush=True)
    f = Fetcher(48, 2)
    sem = asyncio.Semaphore(4)
    stats = {"accepted": 0, "blocked": 0, "cdx": 0, "bing": 0, "none": 0}
    async with httpx.AsyncClient(headers=M.ua_research) as cdx_client, \
            httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                                       "Accept-Language": M.accept_language}, follow_redirects=True) as bclient:
        bing = DDG(bclient)

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
                if await ddg_probe(bing, con, ref_id, name, domains):
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
    """Second pass for refs where live variants found nothing (often geo-redirects from this out-of-market VM):
    look for recent archived captures under market paths of every known domain."""
    refs = con.execute("SELECT r.ref_id, r.domains FROM reference_stores r JOIN reference_urls u ON u.ref_id=r.ref_id AND u.via='none' WHERE r.kind IN ('brand','mall')").fetchall()
    print(f"[reference] cdx retry for {len(refs)} refs", flush=True)
    sem = asyncio.Semaphore(4)
    found = 0
    async with httpx.AsyncClient(headers=M.ua_research) as client:
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


MALL_TSV = os.path.join(HERE, "data", "mall_tenants.tsv")


def load_malls(con):
    """Mall tenant directories: tenants matching a brand ref add the mall as a source; the rest become kind='mall' refs."""
    brands = con.execute("SELECT ref_id, name, domains, sources FROM reference_stores WHERE kind IN ('brand','mall')").fetchall()
    index = {}
    for ref_id, name, doms, _ in brands:
        for part in name.split(":")[-1].split("/"):
            index.setdefault(_norm(part), ref_id)
        for d in doms.split():
            index.setdefault(_norm(d.split(".")[0]), ref_id)
    merged = new = 0
    with open(MALL_TSV, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            slug, name, cat, src = line.rstrip("\n").split("\t")
            srcs = [s.strip() for s in src.split("|")]
            ref_id = index.get(_norm(name)) or index.get(_norm(slug))
            if ref_id:
                old = json.loads(con.execute("SELECT sources FROM reference_stores WHERE ref_id=?", (ref_id,)).fetchone()[0] or "[]")
                con.execute("UPDATE reference_stores SET sources=? WHERE ref_id=?",
                            (json.dumps(old + [s for s in srcs if s not in old], ensure_ascii=False), ref_id))
                merged += 1
                continue
            label = slug.replace("-", "")
            doms = f"{label}.com {label}.{M.tld} {label}.com.{M.tld}"
            upsert(con, name, cat or "Fashion & Apparel", "medium", doms, srcs + ["domains guessed from tenant name"], None, "mall")
            new += 1
    con.commit()
    print(f"[malls] merged into existing refs: {merged}, new mall refs: {new}")


APPSTORE_GENRES = {"Shopping", "Food & Drink", "Lifestyle", "Health & Fitness", "Medical"}


def _norm(s):
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", (s or "").lower().replace("&", "and"))


def appstore_domains(con, limit=1000):
    """Official storefront domains from the market App Store (iTunes Search API sellerUrl) for brands with no
    working market storefront yet; matched refs get the new domains and are queued for resolve again."""
    from .common import MARKETPLACE_ROOTS, NON_STORE_ROOTS
    refs = con.execute("SELECT ref_id, name, domains, sources FROM reference_stores WHERE kind IN ('brand','mall') AND status IN ('excluded','unresolved') "
                       "AND reason NOT LIKE 'excluded: marketplace%' LIMIT ?", (limit,)).fetchall()
    print(f"[appstore] {len(refs)} refs", flush=True)
    added = 0
    with httpx.Client(timeout=30) as client:
        for i, (ref_id, name, doms, sources) in enumerate(refs):
            term = name.split(":")[-1].split("/")[0].strip()
            tok = _norm(term)
            if len(tok) < 3:
                continue
            for attempt in range(3):
                try:
                    r = client.get("https://itunes.apple.com/search", params={"term": term, "country": M.itunes_country, "entity": "software", "limit": 8})
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(20)
            else:
                continue
            time.sleep(3.2)
            have = set(doms.split())
            new = []
            for app in r.json().get("results", []):
                if app.get("primaryGenreName") not in APPSTORE_GENRES or not app.get("sellerUrl"):
                    continue
                if tok not in _norm(app.get("trackName")) and tok not in _norm(app.get("sellerName")):
                    continue
                host = (urlsplit(app["sellerUrl"]).hostname or "").lower()
                root = registrable_domain(host)
                if not root or root in NON_STORE_ROOTS or root in MARKETPLACE_ROOTS or root in have:
                    continue
                if tok[:4] not in _norm(root) and tok not in _norm(app.get("sellerName")):
                    continue
                cand = host[4:] if host.startswith("www.") else host
                for d in {cand, root}:
                    if d not in have:
                        have.add(d)
                        new.append(d)
                src = f"appstore:{app.get('trackId')} ({app.get('trackName')[:40]}; sellerUrl {app['sellerUrl']})"
                srcs = json.loads(sources or "[]")
                if src not in srcs:
                    srcs.append(src)
                    sources = json.dumps(srcs, ensure_ascii=False)
            if new:
                added += 1
                con.execute("UPDATE reference_stores SET domains=?, sources=? WHERE ref_id=?", (" ".join(sorted(have, key=lambda d: d not in new)), sources, ref_id))
                con.execute("DELETE FROM reference_urls WHERE ref_id=? AND via IN ('none','live_variant','wayback_cdx')", (ref_id,))
                con.commit()
                print(f"[appstore] {name}: +{' '.join(new)}", flush=True)
            if i % 25 == 0:
                print(f"[appstore] {i}/{len(refs)} added={added}", flush=True)
    print(f"[appstore] done added={added}", flush=True)


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
    # Tranco ccTLD and Wikidata entries are verified directly from their root domain
    for ref_id, doms, kind in con.execute("SELECT ref_id, domains, kind FROM reference_stores WHERE kind IN ('tranco_cc','wikidata')").fetchall():
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
    (re.compile(r"redirects_to_non_market_storefront|not_market_relevant|non_market_shopify"), f"excluded: no {M.country} storefront (site serves another country)"),
    (re.compile(r"no_ecommerce_evidence"), f"excluded: no online ordering on {M.country} site (brand/info site)"),
    (re.compile(r"store_closed|store_not_launched|parked"), "excluded: store closed / not launched"),
    (re.compile(r"charity_or_donations"), "excluded: charity"),
]


PLATFORM_ROOTS = {"salla.com", "salla.sa", "zid.sa", "tryzid.com", "shopify.com", "expandcart.com", "youcan.shop", "wuilt.com", "matjrah.com"}


def audit(con, previous_csv=None):
    """Assign each reference store a coverage status. Returns list of dict rows for the audit sheet."""
    from .common import MARKETPLACE_ROOTS, NON_STORE_ROOTS
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
        "SELECT name FROM sqlite_master WHERE name='secondary_evidence'").fetchall() else {}
    nones = {r[0]: json.loads(r[1] or "{}") for r in con.execute("SELECT ref_id, info FROM reference_urls WHERE via='none'")}

    def master_of(k):
        r = ver.get(k)
        while r and r["cstatus"] == "duplicate" and r["dup"] and r["dup"] in ver and r["dup"] != r["key"]:
            r = ver[r["dup"]]
        return r

    rows = []
    has_ov = bool(con.execute("SELECT name FROM sqlite_master WHERE name='ref_overrides'").fetchall())
    for ref_id, name, cat, tier, doms, sources, rank, kind in con.execute(
            "SELECT ref_id, name, category, tier, domains, sources, tranco_rank, kind FROM reference_stores").fetchall():
        domains = doms.split()
        roots = {registrable_domain(d) for d in domains}
        labels = {r.split(".")[0] for r in roots}
        alt = set(roots) | {f"{l}.{M.tld}" for l in labels} | {f"{l}.com.{M.tld}" for l in labels} | {f"{l}-{M.code}.com" for l in labels} | {f"{l}{M.code}.com" for l in labels} | {f"{l}{M.path_words[0]}.com" for l in labels}
        keys = set(mapped.get(ref_id, []))
        for r in alt - NON_STORE_ROOTS:
            keys.update(by_root.get(r, []))
        cands = [master_of(k) for k in keys if k in ver]
        cands = [c for c in cands if c]
        good = [c for c in cands if c["cstatus"] == "verified" and c["vstatus"] in ("verified", "verified_secondary_evidence")]
        status, url, reason, evidence, key = None, "", "", "", None
        if roots and roots <= PLATFORM_ROOTS:
            status, reason = "excluded", "excluded: ecommerce platform / non-store site, not a merchant"
        elif any(r in MARKETPLACE_ROOTS for r in roots):
            status, reason = "excluded", "excluded: marketplace / aggregator (" + MARKETPLACE_ROOTS[[r for r in roots if r in MARKETPLACE_ROOTS][0]] + ")"
        elif good:
            good.sort(key=lambda c: (c["vstatus"] != "verified", not MARKET_GEO.search(c["final"] or c["url"] or ""), len(c["key"])))
            g = good[0]
            key = g["key"]
            url = g["final"] or g["url"]
            from .export import master_url
            murl = master_url({"final_url": g["final"], "url": g["url"]})
            url = murl
            primary = g["vstatus"] == "verified"
            status = "in_directory_primary" if primary else "in_directory_secondary"
            was = murl.rstrip("/") in prev
            reason = ("found by general discovery" if not was else "already present before reference audit") + ("" if primary else " (secondary evidence)")
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
            pend = [c for c in cands if c["cstatus"] in ("pending", "in_progress")]
            if pend and not blocked:
                status, key, url = "unresolved", pend[0]["key"], pend[0]["url"]
                reason = "unresolved: live verification still queued"
            elif blocked:
                b = blocked[0]
                key = b["key"]
                url = b["final"] or b["url"]
                s = sec.get(b["key"])
                ev_types = [e["type"] for e in json.loads(s[1])] if s else []
                oks = [e for e in json.loads(s[1]) if e.get("ok")] if s else []
                status = "unresolved"
                reason = f"unresolved: live check '{b['reason'][:60]}'" + (f"; secondary evidence insufficient ({', '.join(e['type'] for e in oks) or 'none'} of {', '.join(ev_types)})" if s else "; secondary evidence not yet collected")
                evidence = " | ".join(f"{e['type']}: {e.get('detail')} ({e.get('url')}, {e.get('date')})" for e in oks)
            elif exc and ("no online ordering" in exc[0] or "serves another country" in exc[0]) and exc[1]["key"] not in sec:
                # static HTML of a JS storefront, or a geo-redirect seen from this out-of-market VM, is not proof of absence
                status, key, url = "unresolved", exc[1]["key"], exc[1]["final"] or exc[1]["url"]
                reason = f"unresolved: live check '{exc[1]['reason'][:60]}'; secondary evidence not yet collected"
            elif exc:
                status, reason = "excluded", exc[0]
                key, url, evidence = exc[1]["key"], exc[1]["final"] or exc[1]["url"], exc[1]["reason"][:200]
                if key in sec:
                    reason += "; secondary evidence (archives, app store, sitemap) also insufficient"
            elif cands:
                c = cands[0]
                status, key, url = "excluded", c["key"], c["final"] or c["url"]
                reason = f"excluded: no working {M.country} storefront found (" + (c["reason"] or c["cstatus"])[:80] + ")"
            else:
                status = "excluded"
                info = nones.get(ref_id, {})
                reason = f"excluded: no {M.country} storefront found ({M.country} URL variants" + (", Wayback CDX" if info.get("blocked") else "") + " checked)"
        if kind in ("tranco_cc", "wikidata") and status != "in_directory_primary" and status != "in_directory_secondary":
            status = "screened_out"
        ov = con.execute("SELECT status, reason, evidence, url, key FROM ref_overrides WHERE ref_id=?", (ref_id,)).fetchone() if has_ov else None
        if ov and status not in ("in_directory_primary", "in_directory_secondary"):
            status, reason, evidence, url, key = ov[0], ov[1], ov[2], ov[3] or url, ov[4] or key
        con.execute("UPDATE reference_stores SET status=?, best_key=?, best_url=?, reason=?, evidence=?, checked_at=? WHERE ref_id=?",
                    (status, key, url, reason, evidence, db.now(), ref_id))
        rows.append(dict(ref_id=ref_id, name=name, category=cat, tier=tier, domains=doms, sources=", ".join(json.loads(sources)),
                         tranco_rank=rank, kind=kind, status=status, url=url, key=key, reason=reason, evidence=evidence))
    con.commit()
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "load-malls", "resolve", "retry-none", "appstore", "link", "audit"])
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
    elif a.cmd == "load-malls":
        load_malls(con)
    elif a.cmd == "appstore":
        appstore_domains(con, a.limit)
    elif a.cmd == "retry-none":
        asyncio.run(retry_none(con))
    elif a.cmd == "audit":
        import collections
        rows = audit(con, None)
        print(collections.Counter((r["kind"], r["status"]) for r in rows))
    else:
        link(con)
