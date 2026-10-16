"""Secondary-evidence verification for storefronts the live checker could not read (bot walls, JS-only pages).

No challenge is bypassed. Evidence types (each recorded with URL + date):
  wayback_product  recent (<=180 days) Wayback Machine capture of a product page under the Saudi storefront path
                   showing SAR prices and an add-to-cart/ordering control
  commoncrawl_product  same check on a product-page capture from a recent Common Crawl crawl (WARC byte range)
  sitemap          robots-allowed sitemap listing product URLs under the Saudi storefront path
  app_store        current (<=365 days) shopping app by the brand in the Saudi Apple App Store (iTunes Search API)
  bing_indexed     search-engine indexed product pages under the Saudi storefront with SAR prices in the snippet
A store becomes `verified_secondary_evidence` with >=2 independent evidence types, at least one of which is
storefront-level (wayback_product, commoncrawl_product, sitemap or bing_indexed).

  python3 -m saudi_ecom.secondary [--keys k1,k2] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import html as htmlmod
import json
import re
from urllib.parse import quote, urlsplit

import httpx

from . import db
from . import signals as S
from .common import identity, registrable_domain
from .discover_search import bing_decode
from .reference import connect
from .verify import SA_GEO

UA_RESEARCH = {"User-Agent": "saudi-ecom-directory-research/1.0 (polite archive client)"}
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
              "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"}
PRODUCT_URL = re.compile(r"/p/|/p\d{4,}|-p\d{5,}|[-_]p[-_]?\d{5,}|/product[s]?/|/dp/|/pd/|\d{6,}\.html|/buy-|/item/|/prd/|\.p\d+|/\d{7,}", re.I)
SAR = re.compile(r'(?:SAR|ر\.?\s?س|ريال|﷼)(?:\s|&nbsp;|<[^<>]{0,120}>){0,6}\d|\d[\d,.]*(?:\s|&nbsp;|<[^<>]{0,120}>){0,6}(?:SAR|ر\.?\s?س|ريال|﷼)|"(?:priceCurrency|currency|currencyCode|currency_code)"\s*:\s*"SAR"', re.I)
CART = re.compile(r"add[\s_-]?to[\s_-]?(?:cart|bag|basket)|addToCart|أضف إلى (?:السلة|الحقيبة)|اضف للسلة|أضف للسلة|إضافة إلى (?:السلة|الحقيبة)|buy now|اشتر[يِ]? الآن|\"@type\"\s*:\s*\"Offer\"", re.I)
SHOP_GENRES = {"Shopping", "Food & Drink", "Lifestyle", "Health & Fitness", "Medical"}
NOW = dt.datetime.now(dt.timezone.utc)


def days_ago(ts14):
    try:
        t = dt.datetime.strptime(ts14[:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
        return (NOW - t).days
    except ValueError:
        return 9999


NON_PRODUCT = re.compile(r"/(?:account|login|cart|checkout|help|faq|about|contact|privacy|terms|careers|blog|news|stores?-locator|search)\b|\.(?:js|css|png|jpe?g|svg|webp|json|xml|pdf)(?:$|\?)", re.I)


def pick_pages(urls, prefix):
    """Product-looking URLs first, then other deep pages; host-only storefronts accept any page on the host."""
    need_geo = "/" in prefix.strip("/")
    ok = [u for u in urls if not NON_PRODUCT.search(u[1]) and (not need_geo or SA_GEO.search(u[1]) or ".sa/" in u[1])]
    prods = sorted([u for u in ok if PRODUCT_URL.search(u[1])], reverse=True)
    deep = sorted([u for u in ok if not PRODUCT_URL.search(u[1]) and len([x for x in urlsplit(u[1]).path.split("/") if x]) >= 2], reverse=True)
    return prods[:3] + deep[:2], len(prods)


def storefront_prefix(url):
    sp = urlsplit(url)
    segs = [s for s in sp.path.split("/") if s]
    keep = []
    for s in segs[:2]:
        keep.append(s)
        if SA_GEO.search("/" + "/".join(keep) + "/"):
            return f"{sp.hostname}/" + "/".join(keep) + "/"
    return f"{sp.hostname}/"


async def wayback_product(client, prefix):
    for attempt in range(2):
        try:
            r = await client.get("https://web.archive.org/cdx/search/cdx", params={
                "url": prefix, "matchType": "prefix", "from": (NOW - dt.timedelta(days=180)).strftime("%Y%m%d"),
                "filter": "statuscode:200", "collapse": "urlkey", "limit": "400", "fl": "timestamp,original"}, timeout=90)
            break
        except httpx.HTTPError:
            await asyncio.sleep(5)
    else:
        return {"type": "wayback_product", "ok": False, "detail": "cdx_error"}
    rows = [l.split(" ", 1) for l in r.text.splitlines() if " " in l]
    prods, n_prod = pick_pages(rows, prefix)
    out = {"type": "wayback_product", "ok": False, "captures": len(rows), "product_captures": n_prod}
    for ts, orig in prods:
        snap = f"https://web.archive.org/web/{ts}id_/{orig}"
        try:
            s = await client.get(snap, timeout=60, follow_redirects=True)
        except httpx.HTTPError:
            continue
        await asyncio.sleep(1.5)
        if s.status_code != 200:
            continue
        txt = s.text[:2_000_000]
        n_sar, cart = len(SAR.findall(txt)), bool(CART.search(txt))
        if n_sar and cart:
            out.update({"ok": True, "url": f"https://web.archive.org/web/{ts}/{orig}", "date": ts[:8], "age_days": days_ago(ts),
                        "detail": f"archived product page with {n_sar} SAR price strings and ordering control"})
            return out
        out.setdefault("checked", []).append({"url": orig, "ts": ts, "sar": n_sar, "cart": cart})
    if rows and not prods:
        out["detail"] = "captures exist but none look like product pages"
    return out


CC_CRAWLS = ["CC-MAIN-2026-39", "CC-MAIN-2026-34"]


async def cc_product(client, prefix):
    """Product page under the Saudi storefront in a recent Common Crawl crawl (WARC record fetched by byte range)."""
    import gzip
    host_prefix = prefix if re.match(r"^www\.", prefix) or prefix.count(".") >= 2 else "www." + prefix
    rows = []
    for crawl in CC_CRAWLS:
        for attempt in range(4):
            try:
                r = await client.get(f"https://index.commoncrawl.org/{crawl}-index", params={
                    "url": host_prefix + "*", "output": "json", "filter": "status:200", "limit": "300"}, timeout=90)
            except httpx.HTTPError:
                await asyncio.sleep(5)
                continue
            if r.status_code in (502, 503, 504):
                await asyncio.sleep(8)
                continue
            break
        else:
            continue
        for line in r.text.splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if "url" in j:
                rows.append(j)
        if rows:
            break
    by_url = {j["url"]: j for j in rows}
    picked, n_prod = pick_pages([(j["timestamp"], j["url"]) for j in rows], prefix)
    out = {"type": "commoncrawl_product", "ok": False, "captures": len(rows), "product_captures": n_prod}
    for _, u in picked:
        j = by_url[u]
        off, ln = int(j["offset"]), int(j["length"])
        try:
            w = await client.get("https://data.commoncrawl.org/" + j["filename"], headers={"Range": f"bytes={off}-{off + ln - 1}"}, timeout=60)
            body = gzip.decompress(w.content).decode("utf-8", "replace")
        except Exception:
            continue
        n_sar, cart = len(SAR.findall(body)), bool(CART.search(body))
        if n_sar and cart:
            out.update({"ok": True, "url": j["url"], "date": j["timestamp"][:8], "age_days": days_ago(j["timestamp"]),
                        "detail": f"Common Crawl capture ({j['filename'].split('/')[1]}) of product page with {n_sar} SAR price strings and ordering control",
                        "warc": f"{j['filename']}@{off}+{ln}"})
            return out
        out.setdefault("checked", []).append({"url": j["url"], "sar": n_sar, "cart": cart})
    return out


async def sitemap_ev(client, base_host, prefix):
    try:
        r = await client.get(f"https://{base_host}/robots.txt", timeout=20)
    except httpx.HTTPError:
        return {"type": "sitemap", "ok": False, "detail": "robots_fetch_failed"}
    if r.status_code != 200 or "<html" in r.text[:300].lower():
        return {"type": "sitemap", "ok": False, "detail": f"robots_http_{r.status_code}"}
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
    sa_maps = [m for m in maps if SA_GEO.search(m) or "sa" in m.lower()] or maps
    for sm in sa_maps[:4]:
        try:
            s = await client.get(sm, timeout=30)
        except httpx.HTTPError:
            continue
        if s.status_code != 200 or "<loc>" not in s.text:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", s.text)
        prods = [l for l in locs if PRODUCT_URL.search(l) and (SA_GEO.search(l) or ".sa/" in l)]
        if len(prods) >= 5:
            return {"type": "sitemap", "ok": True, "url": sm, "date": NOW.strftime("%Y%m%d"),
                    "detail": f"{len(prods)} Saudi-storefront product URLs in sitemap", "sample": prods[:3]}
        children = [l for l in locs if l.endswith(".xml") or "sitemap" in l.lower()]
        for ch in [c for c in children if SA_GEO.search(c) or "product" in c.lower()][:2]:
            try:
                c = await client.get(ch, timeout=30)
            except httpx.HTTPError:
                continue
            cl = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", c.text) if c.status_code == 200 else []
            cp = [l for l in cl if PRODUCT_URL.search(l) and (SA_GEO.search(l) or ".sa/" in l)]
            if len(cp) >= 5:
                return {"type": "sitemap", "ok": True, "url": ch, "date": NOW.strftime("%Y%m%d"),
                        "detail": f"{len(cp)} Saudi-storefront product URLs in sitemap", "sample": cp[:3]}
    return {"type": "sitemap", "ok": False, "detail": "no Saudi product URLs in accessible sitemaps"}


def name_tokens(name):
    base = re.sub(r"^[^:]+:\s*", "", name)
    base = re.split(r"[/(]", base)[0]
    return [t for t in re.findall(r"[a-z0-9&']{3,}", base.lower()) if t not in {"the", "and", "store", "online", "shop", "ksa", "saudi", "com", "net", "org", "www"}]


async def app_store(client, name, domains):
    toks = name_tokens(name)
    if not toks:
        return {"type": "app_store", "ok": False, "detail": "no name tokens"}
    term = " ".join(toks[:3])
    try:
        r = await client.get("https://itunes.apple.com/search", params={"term": term, "country": "sa", "entity": "software", "limit": "10"}, timeout=30)
        res = r.json().get("results", [])
    except Exception:
        return {"type": "app_store", "ok": False, "detail": "itunes_error"}
    labels = {d.split(".")[0] for d in domains}
    for a in res:
        title = (a.get("trackName") or "").lower()
        seller = (a.get("sellerName") or "").lower()
        surl = (a.get("sellerUrl") or "").lower()
        name_match = all(t in title or t in seller for t in toks[:2]) or any(l and l in surl for l in labels)
        if not name_match or a.get("primaryGenreName") not in SHOP_GENRES:
            continue
        rel = (a.get("currentVersionReleaseDate") or "")[:10]
        try:
            age = (NOW.date() - dt.date.fromisoformat(rel)).days
        except ValueError:
            age = 9999
        if age <= 365:
            return {"type": "app_store", "ok": True, "url": a.get("trackViewUrl"), "date": rel.replace("-", ""),
                    "detail": f"Saudi App Store {a.get('primaryGenreName')} app '{a.get('trackName')}' by {a.get('sellerName')}, updated {rel}"}
    return {"type": "app_store", "ok": False, "detail": f"no current shopping app matching {term!r}"}


async def bing_indexed(client, prefix):
    q = f"site:{prefix.rstrip('/')} SAR"
    try:
        r = await client.get("https://www.bing.com/search", params={"q": q, "cc": "SA", "setlang": "en"}, timeout=30)
    except httpx.HTTPError:
        return {"type": "bing_indexed", "ok": False, "detail": "bing_error"}
    await asyncio.sleep(3)
    hits = []
    for block in r.text.split('class="b_algo"')[1:]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"', block)
        if not m:
            continue
        u = bing_decode(m.group(1)) or ""
        text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", block[:4000]))
        if prefix.split("/")[0] in u and (SA_GEO.search(u) or ".sa/" in u) and SAR.search(text):
            hits.append(u)
    if len(hits) >= 2:
        return {"type": "bing_indexed", "ok": True, "url": f"https://www.bing.com/search?q={quote(q)}", "date": NOW.strftime("%Y%m%d"),
                "detail": f"{len(hits)} indexed Saudi-storefront pages with SAR prices", "sample": hits[:3]}
    return {"type": "bing_indexed", "ok": False, "detail": f"{len(hits)} indexed pages with SAR"}


async def check(clients, item):
    arch, live, brw = clients
    prefix = storefront_prefix(item["url"])
    host = prefix.split("/")[0]
    prefix = re.sub(r"^www\d+\.", "", prefix)
    evs = await asyncio.gather(wayback_product(arch, prefix), cc_product(arch, prefix), sitemap_ev(live, host, prefix),
                               app_store(live, item["name"], item["domains"]))
    ok = [e for e in evs if e.get("ok")]
    types = {e["type"] for e in ok}
    storefront = types & {"wayback_product", "commoncrawl_product", "sitemap", "bing_indexed"}
    verdict = "verified_secondary_evidence" if len(types) >= 2 and storefront else "insufficient_secondary_evidence"
    return {"key": item["key"], "prefix": prefix, "verdict": verdict, "evidence": evs}


def save(con, item, res, ref_name):
    evs = [e for e in res["evidence"] if e.get("ok")]
    ev_text = " | ".join(f"{e['type']}: {e['detail']} ({e.get('url')}, {e.get('date')})" for e in evs)
    if res["verdict"] == "verified_secondary_evidence":
        sf = item["url"]
        for e in evs:
            if e["type"] in ("wayback_product", "commoncrawl_product", "sitemap") and e.get("url"):
                orig = re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", e["url"])
                sf = "https://" + storefront_prefix(orig)
                break
        con.execute("""UPDATE verifications SET status='verified_secondary_evidence', method='secondary',
                       reason=?, product_evidence=?, evidence_url=?, verified_at=?, store_name=CASE WHEN coalesce(store_name,'')='' THEN ? ELSE store_name END,
                       final_url=? WHERE key=?""",
                    ("verified_secondary_evidence: " + ev_text, evs[0].get("url"), evs[0].get("url"), db.now(), ref_name, sf, item["key"]))
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.execute("INSERT OR REPLACE INTO verifications(key, final_url, final_key, store_name, status, reason, evidence_url, product_evidence, verified_at, method) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (item["key"], sf, item["key"], ref_name, "verified_secondary_evidence", "verified_secondary_evidence: " + ev_text, evs[0].get("url"), evs[0].get("url"), db.now(), "secondary"))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (item["key"],))
    con.execute("CREATE TABLE IF NOT EXISTS secondary_evidence(key TEXT PRIMARY KEY, prefix TEXT, verdict TEXT, evidence TEXT, ts TEXT)")
    con.execute("INSERT OR REPLACE INTO secondary_evidence VALUES(?,?,?,?,?)", (item["key"], res["prefix"], res["verdict"], json.dumps(res["evidence"], ensure_ascii=False), db.now()))
    con.commit()


SECONDARY_REASONS = ("blocked_or_challenge%", "js_rendered%", "partial_ecommerce%", "insufficient_ecommerce%", "robots_disallowed%",
                     "fetch_failed%", "verification_timeout%", "rate_limited%", "weak_ecommerce%", "http_5%", "http_403%")


def unresolved_targets(con, per_ref=2):
    """Brand refs the audit left unresolved: their existing non-verified candidates (Saudi-path keys first), else root domains."""
    seen = {r[0] for r in con.execute("SELECT key FROM secondary_evidence")}
    rows = []
    for ref_id, name, doms in con.execute("SELECT ref_id, name, domains FROM reference_stores WHERE kind IN ('brand','mall') AND status='unresolved'").fetchall():
        ds = doms.split()
        if not ds:
            continue
        qs = ",".join("?" * len(ds))
        cands = con.execute(f"SELECT key, url FROM candidates WHERE (root_domain IN ({qs}) OR key IN ({qs})) AND status NOT IN ('verified','in_progress')",
                            (*ds, *ds)).fetchall()
        if not cands:
            for d in ds:
                ident = identity(f"https://{d}/")
                if ident:
                    db.add_candidates(con, [(f"https://{d}/", 5)], "reference:secondary_fallback", f"ref {ref_id}", 5)
                    cands.append((ident["key"], f"https://{d}/"))
            con.commit()
        cands.sort(key=lambda kv: (not ("|" in kv[0] or re.match(r"(?:sa|ksa|saudi|en-sa|ar-sa)\.", kv[0]) or kv[0].endswith(".sa")), len(kv[0])))
        rows += [(k, u, name, doms) for k, u in cands[:per_ref] if k not in seen]
    return rows


def targets(con, keys, limit):
    """Reference-linked candidates the live checker couldn't confirm (plus explicit keys)."""
    if keys:
        q = f"""SELECT c.key, c.url, (SELECT r.name FROM reference_urls ru JOIN reference_stores r USING(ref_id) WHERE ru.key=c.key LIMIT 1),
                (SELECT r.domains FROM reference_urls ru JOIN reference_stores r USING(ref_id) WHERE ru.key=c.key LIMIT 1),
                (SELECT store_name FROM verifications v WHERE v.key=c.key)
                FROM candidates c WHERE c.key IN ({','.join('?'*len(keys))})"""
        rows = [(k, u, n or sn or k, d or (registrable_domain(urlsplit(u).hostname or ""))) for k, u, n, d, sn in con.execute(q, keys).fetchall()]
    else:
        cond = " OR ".join("v.reason LIKE ?" for _ in SECONDARY_REASONS)
        rows = con.execute(f"""SELECT DISTINCT ru.key, coalesce(ru.final_url, ru.url), r.name, r.domains FROM reference_urls ru
            JOIN reference_stores r ON r.ref_id=ru.ref_id JOIN candidates c ON c.key=ru.key LEFT JOIN verifications v ON v.key=ru.key
            WHERE r.kind IN ('brand','mall') AND c.status IN ('unverified','rejected') AND (v.key IS NULL OR {cond})
            AND ru.key NOT IN (SELECT key FROM secondary_evidence) LIMIT ?""", (*SECONDARY_REASONS, limit)).fetchall()
        rows += unresolved_targets(con)
    return [{"key": k, "url": u if u.startswith("http") else "https://" + u, "name": n or k, "domains": (d or "").split()} for k, u, n, d in rows if k]


async def main(keys, limit, concurrency):
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS secondary_evidence(key TEXT PRIMARY KEY, prefix TEXT, verdict TEXT, evidence TEXT, ts TEXT)")
    items = targets(con, keys, limit)
    print(f"[secondary] {len(items)} targets", flush=True)
    sem = asyncio.Semaphore(concurrency)
    stats = {"verified_secondary_evidence": 0, "insufficient_secondary_evidence": 0}
    async with httpx.AsyncClient(headers=UA_RESEARCH, follow_redirects=True) as arch, \
            httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True) as live, \
            httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True) as brw:
        async def one(it):
            async with sem:
                try:
                    res = await check((arch, live, brw), it)
                except Exception as e:
                    print("[secondary] error", it["key"], type(e).__name__, flush=True)
                    return
            save(con, it, res, it["name"])
            stats[res["verdict"]] += 1
            oks = [e["type"] for e in res["evidence"] if e.get("ok")]
            print(f"[secondary] {it['key']} -> {res['verdict']} {oks} {stats}", flush=True)
        await asyncio.gather(*(one(i) for i in items))
    print("[secondary] done", stats, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(main([k for k in a.keys.split(",") if k], a.limit, a.concurrency))
