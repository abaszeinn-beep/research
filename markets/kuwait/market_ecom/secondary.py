"""Secondary-evidence verification for storefronts the live checker could not read (bot walls, JS-only pages).

No challenge is bypassed. Evidence types (each recorded with URL + date):
  wayback_product  Wayback Machine capture of a product page under the market storefront path
                   showing market-currency prices and an add-to-cart/ordering control. The lookup uses the
                   newest captures (window widened from 180 to 640 days); the capture date is stored.
  commoncrawl_product  same check on a product-page capture from a recent Common Crawl crawl (WARC byte range)
  sitemap          robots-allowed sitemap listing product URLs under the market storefront path
  app_store        shopping app by the brand in the market Apple App Store (iTunes Search API),
                   updated within 450 days (widened from 365; the store listing date is stored)
  bing_indexed     search-engine indexed product pages under the market storefront with market-currency prices in the snippet
A store becomes `verified_secondary_evidence` with >=2 independent evidence types, at least one of which is
storefront-level (wayback_product, commoncrawl_product, sitemap or bing_indexed).

  python3 -m market_ecom.secondary [--keys k1,k2] [--limit N]
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
from .verify import FOREIGN_GEO, SA_GEO
from . import market as MK

UA_RESEARCH = {"User-Agent": "market-ecom-directory-research/1.0 (polite archive client)"}
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
              "Accept-Language": MK.ACCEPT_LANGUAGE}
PRODUCT_URL = re.compile(
    r"/p/|/p\d{4,}|-p\d{5,}|[-_]p[-_]?\d{5,}|/products?/|/product-[a-z0-9]|/catalog/product/|/dp/|/pd/|"
    r"\d{6,}\.html|/buy-|/item/|/prd/|\.p\d+|/\d{7,}|/style/[a-z]{2}\d{4,}|-l\d{5,}|"
    r"/(?:kw-en|en-kw|ar-kw)/[a-z0-9]+(?:-[a-z0-9]+){4,}\.html",
    re.I)
CUR = MK.CUR_TOKENS
SAR = re.compile(rf'(?:{CUR})(?:\s|&nbsp;|<[^<>]{{0,120}}>){{0,6}}\d|\d[\d,.]*(?:\s|&nbsp;|<[^<>]{{0,120}}>){{0,6}}(?:{CUR})|"(?:priceCurrency|currency|currencyCode|currency_code)"\s*:\s*"{MK.CURRENCY}"', re.I)
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
    ok = [u for u in urls if not NON_PRODUCT.search(u[1]) and (not need_geo or SA_GEO.search(u[1]) or MK.on_market_tld(urlsplit(u[1]).hostname or ""))]
    prods = sorted([u for u in ok if PRODUCT_URL.search(u[1])], reverse=True)
    deep = sorted([u for u in ok if not PRODUCT_URL.search(u[1]) and len([x for x in urlsplit(u[1]).path.split("/") if x]) >= 2], reverse=True)
    return prods[:8] + deep[:2], len(prods)


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
                "url": prefix, "matchType": "prefix", "from": (NOW - dt.timedelta(days=640)).strftime("%Y%m%d"),
                "filter": ["statuscode:200", "mimetype:text/html"], "collapse": "urlkey", "limit": "400",
                "fl": "timestamp,original,length"}, timeout=90)
            break
        except httpx.HTTPError:
            await asyncio.sleep(5)
    else:
        return {"type": "wayback_product", "ok": False, "detail": "cdx_error"}
    rows = []
    for line in r.text.splitlines():
        parts = line.split(" ")
        if len(parts) < 2:
            continue
        # Skip tiny captures (challenge shells and empty replays). Fall back to them only when nothing larger exists.
        length = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        if length and length < 3500:
            continue
        rows.append((parts[0], parts[1]))
    if not rows:
        rows = [(p[0], p[1]) for line in r.text.splitlines() if len(p := line.split(" ")) >= 2]
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
                        "detail": f"archived product page with {n_sar} {MK.CURRENCY} price strings and ordering control"})
            return out
        out.setdefault("checked", []).append({"url": orig, "ts": ts, "sar": n_sar, "cart": cart})
    if not out.get("ok"):
        # Newest month first. Fetch as we go so a later month with a priced page is not dropped
        # once a handful of priceless replays have already filled the sample.
        seen = {u for _, u in prods}
        fetched = 0
        for months_ago in range(0, 21):
            if fetched >= 30:
                break
            start = (NOW - dt.timedelta(days=30 * months_ago)).replace(day=1)
            end = (start + dt.timedelta(days=32)).replace(day=1)
            try:
                mr = await client.get("https://web.archive.org/cdx/search/cdx", params={
                    "url": prefix, "matchType": "prefix",
                    "from": start.strftime("%Y%m%d"), "to": end.strftime("%Y%m%d"),
                    "filter": ["statuscode:200", "mimetype:text/html",
                               r"original:.*(/p/|/product/|/buy-|/products/|-l[0-9]{5,}).*"],
                    "fl": "timestamp,original,length", "limit": "8"}, timeout=70)
            except httpx.HTTPError:
                continue
            month_rows = []
            for line in mr.text.splitlines():
                parts = line.split(" ")
                if len(parts) < 2 or parts[1] in seen or "Mozilla" in parts[1] or "archive.org_bot" in parts[1]:
                    continue
                if not PRODUCT_URL.search(parts[1]):
                    continue
                length = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                if length and length < 3500:
                    continue
                month_rows.append((length, parts[0], parts[1]))
            month_rows.sort(reverse=True)
            for _, ts, orig in month_rows[:2]:
                seen.add(orig)
                fetched += 1
                snap = f"https://web.archive.org/web/{ts}id_/{orig}"
                try:
                    s = await client.get(snap, timeout=60, follow_redirects=True)
                except httpx.HTTPError:
                    continue
                await asyncio.sleep(1.2)
                if s.status_code != 200 or len(s.text) < 3500:
                    continue
                txt = s.text[:2_000_000]
                n_sar, cart = len(SAR.findall(txt)), bool(CART.search(txt))
                if n_sar and cart:
                    out.update({"ok": True, "url": f"https://web.archive.org/web/{ts}/{orig}", "date": ts[:8], "age_days": days_ago(ts),
                                "detail": f"archived product page with {n_sar} {MK.CURRENCY} price strings and ordering control"})
                    return out
                out.setdefault("checked", []).append({"url": orig, "ts": ts, "sar": n_sar, "cart": cart})
    if rows and not prods and not out.get("ok"):
        out["detail"] = "captures exist but none look like product pages"
    return out


CC_CRAWLS = ["CC-MAIN-2026-39", "CC-MAIN-2026-34"]


async def cc_product(client, prefix):
    """Product page under the market storefront in a recent Common Crawl crawl (WARC record fetched by byte range)."""
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
                        "detail": f"Common Crawl capture ({j['filename'].split('/')[1]}) of product page with {n_sar} {MK.CURRENCY} price strings and ordering control",
                        "warc": f"{j['filename']}@{off}+{ln}"})
            return out
        out.setdefault("checked", []).append({"url": j["url"], "sar": n_sar, "cart": cart})
    return out


def _xml_text(resp):
    raw = resp.content or b""
    if raw[:2] == b"\x1f\x8b":
        import gzip
        try:
            return gzip.decompress(raw).decode("utf-8", "replace")
        except Exception:
            return resp.text or ""
    return resp.text or ""


async def sitemap_ev(client, base_host, prefix):
    try:
        r = await client.get(f"https://{base_host}/robots.txt", timeout=20)
    except httpx.HTTPError:
        return {"type": "sitemap", "ok": False, "detail": "robots_fetch_failed"}
    if r.status_code != 200 or "<html" in r.text[:300].lower():
        return {"type": "sitemap", "ok": False, "detail": f"robots_http_{r.status_code}"}
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
    sa_maps = [m for m in maps if SA_GEO.search(m) or MK.ISO2 in m.lower()] or maps

    def productish(locs):
        return [l for l in locs if PRODUCT_URL.search(l) and (SA_GEO.search(l) or MK.on_market_tld(urlsplit(l).hostname or ""))]

    async def read_map(url):
        try:
            s = await client.get(url, timeout=40)
        except httpx.HTTPError:
            return None
        if s.status_code != 200:
            return None
        text = _xml_text(s)
        if "<loc>" not in text:
            return None
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)

    for sm in sa_maps[:4]:
        locs = await read_map(sm)
        if not locs:
            continue
        prods = productish(locs)
        if len(prods) >= 5:
            return {"type": "sitemap", "ok": True, "url": sm, "date": NOW.strftime("%Y%m%d"),
                    "detail": f"{len(prods)} {MK.NAME}-storefront product URLs in sitemap", "sample": prods[:3]}
        children = [l for l in locs if re.search(r"\.xml(?:\.gz)?$", l, re.I) or "sitemap" in l.lower()]
        preferred = [c for c in children if re.search(r"product", c, re.I)]
        rest = [c for c in children if c not in preferred and (SA_GEO.search(c) or MK.ISO2 in c.lower())]
        ordered = preferred or rest or children
        for ch in ordered[:3]:
            cl = await read_map(ch) or []
            cp = productish(cl) if not re.search(r"product", ch, re.I) else [l for l in cl if SA_GEO.search(l) or MK.on_market_tld(urlsplit(l).hostname or "")]
            if not cp and re.search(r"product", ch, re.I):
                cp = productish(cl)
            if len(cp) >= 5:
                return {"type": "sitemap", "ok": True, "url": ch, "date": NOW.strftime("%Y%m%d"),
                        "detail": f"{len(cp)} {MK.NAME}-storefront product URLs in sitemap", "sample": cp[:3]}
    return {"type": "sitemap", "ok": False, "detail": f"no {MK.NAME} product URLs in accessible sitemaps"}


# Brand search terms that the market App Store lists under a different title than the reference name.
APP_ALIASES = {"6thstreet": ["AIVI"], "6thstreet aivi": ["AIVI"], "american eagle": ["AE Aerie"]}


def name_tokens(name):
    base = re.sub(r"^[^:]+:\s*", "", name)
    base = re.split(r"[/(]", base)[0]
    return [t for t in re.findall(r"[a-z0-9&']{3,}", base.lower()) if t not in {"the", "and", "store", "online", "shop", "kuwait", "kw", "com", "net", "org", "www", "alshaya", "landmark", "chalhoub", "apparel", "group", "alghanim"}]


async def app_store(client, name, domains):
    toks = name_tokens(name)
    if not toks:
        toks = [d.split(".")[0] for d in domains[:1]]
    if not toks:
        return {"type": "app_store", "ok": False, "detail": "no name tokens"}
    term = " ".join(toks[:3]) if name_tokens(name) else name
    alias_key = re.sub(r"[^a-z0-9 ]", "", term.lower()).strip()
    terms = [term] + APP_ALIASES.get(alias_key, [])
    res = []
    try:
        for t in terms:
            r = await client.get("https://itunes.apple.com/search", params={"term": t, "country": MK.ISO2, "entity": "software", "limit": "8"}, timeout=30)
            res.extend(r.json().get("results", []))
    except Exception:
        return {"type": "app_store", "ok": False, "detail": "itunes_error"}
    labels = {d.split(".")[0] for d in domains}
    alias_tokens = [t for alias in terms[1:] for t in name_tokens(alias)]
    generic = {"toys", "fashion", "beauty", "home", "kids", "baby", "market", "shop", "store", "online", "mall", "sport", "sports", "wear"}
    toks = [t for t in toks if t not in generic] or toks
    for a in res:
        title = (a.get("trackName") or "").lower()
        seller = (a.get("sellerName") or "").lower()
        surl = (a.get("sellerUrl") or "").lower()
        norm_title = re.sub(r"[^a-z0-9]", "", title)
        alias_match = bool(alias_tokens) and all(t in title or t in seller for t in alias_tokens[:2])
        token_match = all(t in title or t in seller for t in toks[:2]) and (len(toks) >= 2 or (toks and toks[0] not in generic and len(toks[0]) >= 4))
        name_match = (token_match or alias_match or any(l and len(l) >= 4 and l in surl for l in labels)
                      or (len(norm_title) >= 5 and any(norm_title in l or l in norm_title for l in labels)))
        if not name_match or a.get("primaryGenreName") not in SHOP_GENRES:
            continue
        rel = (a.get("currentVersionReleaseDate") or "")[:10]
        try:
            age = (NOW.date() - dt.date.fromisoformat(rel)).days
        except ValueError:
            age = 9999
        if age <= 450:
            return {"type": "app_store", "ok": True, "url": a.get("trackViewUrl"), "date": rel.replace("-", ""),
                    "detail": f"{MK.NAME} App Store {a.get('primaryGenreName')} app '{a.get('trackName')}' by {a.get('sellerName')}, updated {rel}"}
    return {"type": "app_store", "ok": False, "detail": f"no current shopping app matching {term!r}"}


async def bing_indexed(client, prefix):
    q = f"site:{prefix.rstrip('/')} {MK.CURRENCY}"
    try:
        r = await client.get("https://www.bing.com/search", params={"q": q, "cc": MK.CC, "setlang": "en"}, timeout=30)
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
        if prefix.split("/")[0] in u and (SA_GEO.search(u) or MK.on_market_tld(urlsplit(u).hostname or "")) and SAR.search(text):
            hits.append(u)
    if len(hits) >= 2:
        return {"type": "bing_indexed", "ok": True, "url": f"https://www.bing.com/search?q={quote(q)}", "date": NOW.strftime("%Y%m%d"),
                "detail": f"{len(hits)} indexed market-storefront pages with market-currency prices", "sample": hits[:3]}
    return {"type": "bing_indexed", "ok": False, "detail": f"{len(hits)} indexed pages with market-currency prices"}


async def check(clients, item):
    arch, live, brw = clients
    prefix = storefront_prefix(item["url"])
    host = prefix.split("/")[0]
    prefix = re.sub(r"^www\d+\.", "", prefix)
    evs = await asyncio.gather(wayback_product(arch, prefix), cc_product(arch, prefix), sitemap_ev(live, host, prefix),
                               app_store(live, item["name"], item["domains"]))
    if "/" not in prefix.strip("/") and not MK.on_market_tld(host) and host.split(".")[0] not in MK.LOCALE_LABELS:
        # a multi-country root domain: archived pages only count if they are market-path pages or clearly priced in the market currency
        for e in evs:
            orig = re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", e.get("url") or "")
            if not (item.get("global_root") or FOREIGN_GEO.search(orig)):
                continue
            if e.get("ok") and e["type"] in ("wayback_product", "commoncrawl_product") and not SA_GEO.search(orig):
                m = re.search(rf"with (\d+) {MK.CURRENCY}", e.get("detail", ""))
                if not m or int(m.group(1)) < 5:
                    e["ok"] = False
                    e["detail"] += f" (rejected: global root domain, not {MK.NAME}-specific)"
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
            if e["type"] in ("wayback_product", "commoncrawl_product") and e.get("url"):
                orig = re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", e["url"])
                sf = "https://" + storefront_prefix(orig)
                break
            if e["type"] == "sitemap":
                sample = (e.get("sample") or [None])[0]
                if sample:
                    sf = "https://" + storefront_prefix(sample)
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
    """Brand refs the audit left unresolved: their existing non-verified candidates (market-path keys first), else root domains."""
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
        cands.sort(key=lambda kv: (not ("|" in kv[0] or kv[0].split(".")[0] in MK.LOCALE_LABELS or MK.on_market_tld(kv[0])), len(kv[0])))
        rows += [(k, u, name, doms) for k, u in cands[:per_ref] if k not in seen]
    return rows


def targets(con, keys, limit):
    """Reference-linked candidates the live checker couldn't confirm (plus explicit keys)."""
    if keys:
        q = f"""SELECT c.key, c.url, coalesce((SELECT r.name FROM reference_urls ru JOIN reference_stores r USING(ref_id) WHERE ru.key=c.key LIMIT 1),
                                              (SELECT r.name FROM reference_stores r WHERE r.best_key=c.key LIMIT 1)),
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
    for it in items:
        k = it["key"]
        it["global_root"] = "|" not in k and bool(con.execute("SELECT 1 FROM candidates WHERE key IN (?,?,?)", (k + "|" + MK.ISO2, MK.ISO2 + "." + k, "kuwait." + k)).fetchone())
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
