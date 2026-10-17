"""Secondary-evidence verification for storefronts the live checker could not read (bot walls, JS-only pages).

No challenge is bypassed. Evidence types (each recorded with URL + date):
  commoncrawl_product  product-page capture from a recent Common Crawl crawl (WARC byte range) showing market-currency
                       prices and an ordering control (add to cart / Offer)
  wayback_product      same check on a recent Wayback Machine capture (short timeout; Wayback CDX is slow from this VM)
  sitemap              robots-allowed live sitemap listing product URLs (under the market path for multi-country domains)
  app_store            shopping app by the brand in the market's Apple App Store (iTunes Search API), updated within 450 days
A store becomes `verified_secondary_evidence` with >=2 independent evidence types, at least one storefront-level
(commoncrawl_product, wayback_product or sitemap).

  python3 -m mktecom.secondary [--keys k1,k2] [--limit N] [--concurrency 4]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import re
from urllib.parse import urlsplit

import httpx

from . import db
from .common import registrable_domain
from .market import M
from .reference import connect

ITUNES_LOCK = asyncio.Lock()
UA_RESEARCH = {"User-Agent": "mkt-ecom-directory-research/1.0 (polite archive client)"}
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
              "Accept-Language": M.accept_language}
STOREFRONT_TYPES = {"commoncrawl_product", "wayback_product", "wayback_jsonld", "sitemap", "live_storefront"}
PRODUCT_URL = re.compile(
    r"/p/|/p\d{4,}|-p\d{5,}|[-_]p[-_]?\d{5,}|/products?/|/product-[a-z0-9]|/catalog/product/|/dp/|/pd/|/ip/|/sku/|"
    r"\d{6,}\.html|/buy-|/item/|/prd/|\.p\d+|/\d{7,}|/style/|/shop/[a-z0-9-]+/[a-z0-9-]+-\d{4,}", re.I)
LOCAL_PRICE = re.compile(r'"(?:priceCurrency|currency|currencyCode|currency_code)"\s*:\s*"%s"|(?:US)?\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})' % M.currency, re.I)
FOREIGN_CUR = re.compile(r'"(?:priceCurrency|currency|currencyCode)"\s*:\s*"(?!%s)[A-Z]{3}"' % M.currency)
CART = re.compile(r"add[\s_-]?to[\s_-]?(?:cart|bag|basket)|addToCart|buy now|\"@type\"\s*:\s*\"Offer\"|add-to-cart", re.I)
SHOP_GENRES = {"Shopping", "Food & Drink", "Lifestyle", "Health & Fitness", "Medical", "Sports"}
NOW = dt.datetime.now(dt.timezone.utc)
NON_PRODUCT = re.compile(r"/(?:account|login|cart|checkout|help|faq|about|contact|privacy|terms|careers|blog|news|stores?-locator|search)\b|\.(?:js|css|png|jpe?g|svg|webp|json|xml|pdf)(?:$|\?)", re.I)


def days_ago(ts14):
    try:
        t = dt.datetime.strptime(ts14[:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
        return (NOW - t).days
    except ValueError:
        return 9999


def storefront_prefix(url):
    """host[/market-path/] for the storefront."""
    sp = urlsplit(url)
    host = sp.hostname or ""
    m = M.locale_path_re.search((sp.path or "/")[:20])
    if m and m.start() <= 1:
        return host + sp.path[: m.end()].rstrip("/") + "/"
    return host + "/"


def page_ok(body):
    n_loc = len(LOCAL_PRICE.findall(body))
    cart = bool(CART.search(body))
    foreign = bool(FOREIGN_CUR.search(body)) and not re.search(r'"priceCurrency"\s*:\s*"%s"' % M.currency, body)
    return n_loc, cart, foreign


async def cc_crawls(client):
    try:
        r = await client.get("https://index.commoncrawl.org/collinfo.json", timeout=30)
        return [c["id"] for c in r.json()[:3]]
    except Exception:
        return ["CC-MAIN-2026-39", "CC-MAIN-2026-34"]


async def cc_product(client, prefix, crawls):
    host = prefix.split("/")[0]
    hosts = [host] if host.startswith("www.") or host.count(".") >= 2 else ["www." + host, host]
    path = prefix[len(host):]
    rows = []
    for crawl in crawls[:2]:
        for h in hosts:
            for attempt in range(3):
                try:
                    r = await client.get(f"https://index.commoncrawl.org/{crawl}-index", params={
                        "url": h + path + "*", "output": "json", "filter": ["status:200", "mime:text/html"], "limit": "400"}, timeout=90)
                except httpx.HTTPError:
                    await asyncio.sleep(4)
                    continue
                if r.status_code in (502, 503, 504):
                    await asyncio.sleep(6)
                    continue
                break
            else:
                continue
            for line in r.text.splitlines():
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if "url" in j and not NON_PRODUCT.search(j["url"]):
                    rows.append(j)
            if rows:
                break
        if rows:
            break
    prods = [j for j in rows if PRODUCT_URL.search(j["url"])]
    if rows and not prods:
        # first page of the index is alphabetical (often /brands/, /c/ ...); ask the index for product-like paths only
        h = urlsplit("https://" + rows[0]["url"].split("://", 1)[-1]).hostname or hosts[0]
        for crawl in crawls[:2]:
            try:
                r = await client.get(f"https://index.commoncrawl.org/{crawl}-index", params={
                    "url": h + path + "*", "output": "json", "limit": "60",
                    "filter": ["status:200", "mime:text/html", r"~url:.*(/p/|/s/|/products?/|/ip/|/dp/|/pd/|/prd/|/item/|/sku/|/style/|\d{6,}\.html|-p\d{5,}).*"]}, timeout=120)
            except httpx.HTTPError:
                continue
            for line in r.text.splitlines():
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if "url" in j and not NON_PRODUCT.search(j["url"]):
                    prods.append(j)
            if prods:
                break
    out = {"type": "commoncrawl_product", "ok": False, "captures": len(rows), "product_captures": len(prods)}
    for j in (prods[:6] or rows[-3:]):
        off, ln = int(j["offset"]), int(j["length"])
        try:
            w = await client.get("https://data.commoncrawl.org/" + j["filename"], headers={"Range": f"bytes={off}-{off + ln - 1}"}, timeout=60)
            body = gzip.decompress(w.content).decode("utf-8", "replace")
        except Exception:
            continue
        n_loc, cart, foreign = page_ok(body)
        if n_loc and cart and not foreign:
            out.update({"ok": True, "url": j["url"], "date": j["timestamp"][:8], "age_days": days_ago(j["timestamp"]),
                        "detail": f"Common Crawl {j['filename'].split('/')[1]} capture of product page with {n_loc} {M.currency} price strings and ordering control",
                        "warc": f"{j['filename']}@{off}+{ln}"})
            return out
        out.setdefault("checked", []).append({"url": j["url"], "local": n_loc, "cart": cart, "foreign": foreign})
    return out


async def wayback_product(client, prefix):
    host = prefix.split("/")[0]
    try:
        r = await client.get("https://web.archive.org/cdx/search/cdx", params={
            "url": prefix, "matchType": "prefix", "from": (NOW - dt.timedelta(days=400)).strftime("%Y%m%d"),
            "filter": ["statuscode:200", "mimetype:text/html"], "collapse": "urlkey", "limit": "300",
            "fl": "timestamp,original,length"}, timeout=45)
        rows = [l.split(" ") for l in r.text.splitlines() if len(l.split(" ")) >= 2]
    except httpx.HTTPError:
        rows = []
    prods = sorted([x for x in rows if PRODUCT_URL.search(x[1]) and not NON_PRODUCT.search(x[1])], reverse=True)[:4]
    if not prods:
        try:
            r2 = await client.get("https://web.archive.org/cdx/search/cdx", params={
                "url": prefix, "matchType": "prefix", "from": (NOW - dt.timedelta(days=400)).strftime("%Y%m%d"),
                "filter": ["statuscode:200", "mimetype:text/html",
                           "original:.*(/p/|/pd/|/ip/|/dp/|/product|/products/|/prod[0-9]|/sku|/item|/itm/|\\.p\\?|/pdp/).*"],
                "collapse": "urlkey", "limit": "60", "fl": "timestamp,original,length"}, timeout=120)
            rows2 = [l.split(" ") for l in r2.text.splitlines() if len(l.split(" ")) >= 2]
            prods = sorted([x for x in rows2 if not NON_PRODUCT.search(x[1])], reverse=True)[:4]
            rows = rows + rows2
        except httpx.HTTPError:
            pass
    out = {"type": "wayback_product", "ok": False, "captures": len(rows), "product_captures": len(prods)}
    for x in prods:
        ts, orig = x[0], x[1]
        try:
            s = await client.get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=45, follow_redirects=True)
        except httpx.HTTPError:
            continue
        n_loc, cart, foreign = page_ok(s.text[:2_000_000])
        if n_loc and cart and not foreign:
            out.update({"ok": True, "url": f"https://web.archive.org/web/{ts}/{orig}", "date": ts[:8], "age_days": days_ago(ts),
                        "detail": f"archived product page with {n_loc} {M.currency} price strings and ordering control"})
            return out
    return out


def _xml_text(resp):
    raw = resp.content or b""
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw).decode("utf-8", "replace")
        except Exception:
            return resp.text or ""
    return resp.text or ""


async def sitemap_ev(client, prefix):
    host = prefix.split("/")[0]
    path = prefix[len(host):]
    geo = len(path.strip("/")) > 0
    try:
        r = await client.get(f"https://{host}/robots.txt", timeout=20)
    except httpx.HTTPError:
        return {"type": "sitemap", "ok": False, "detail": "robots_fetch_failed"}
    if r.status_code != 200 or "<html" in r.text[:300].lower():
        return {"type": "sitemap", "ok": False, "detail": f"robots_http_{r.status_code}"}
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
    if geo:
        maps = [m for m in maps if path.strip("/").split("/")[0] in m.lower()] or maps

    def productish(locs):
        return [l for l in locs if PRODUCT_URL.search(l) and (not geo or path.rstrip("/") in l)]

    async def read_map(url):
        try:
            s = await client.get(url, timeout=40)
        except httpx.HTTPError:
            return None
        if s.status_code != 200:
            return None
        text = _xml_text(s)
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text) if "<loc>" in text else None

    for sm in maps[:4]:
        locs = await read_map(sm)
        if not locs:
            continue
        prods = productish(locs)
        if len(prods) >= 5:
            return {"type": "sitemap", "ok": True, "url": sm, "date": NOW.strftime("%Y%m%d"),
                    "detail": f"{len(prods)} product URLs in robots-listed sitemap", "sample": prods[:3]}
        children = [l for l in locs if re.search(r"\.xml(?:\.gz)?$", l, re.I) or "sitemap" in l.lower()]
        preferred = [c for c in children if re.search(r"product|pdp|item|sku", c, re.I) and not re.search(r"sitemaps?\.xml$", c)]
        for ch in (preferred or children)[:3]:
            cl = await read_map(ch) or []
            cp = [l for l in cl if not geo or path.rstrip("/") in l] if re.search(r"product|pdp|sku", ch, re.I) else productish(cl)
            if len(cp) >= 5:
                return {"type": "sitemap", "ok": True, "url": ch, "date": NOW.strftime("%Y%m%d"),
                        "detail": f"{len(cp)} product URLs in robots-listed sitemap", "sample": cp[:3]}
    return {"type": "sitemap", "ok": False, "detail": "no product URLs in accessible sitemaps"}


def name_tokens(name):
    base = re.split(r"[/(]", re.sub(r"\b(?:US|USA)\b", "", name))[0]
    return [t for t in re.findall(r"[a-z0-9&']{3,}", base.lower()) if t not in {"the", "and", "store", "online", "shop", "com", "net", "inc", "usa"}]


async def app_store(client, name, domain):
    toks = name_tokens(name) or [domain.split(".")[0]]
    term = " ".join(toks[:3])
    res = None
    for attempt in range(4):
        async with ITUNES_LOCK:
            await asyncio.sleep(3.5)  # iTunes Search API allows roughly 20 calls/minute
            try:
                r = await client.get("https://itunes.apple.com/search", params={"term": term, "country": M.appstore_country, "entity": "software", "limit": "10"}, timeout=30)
                if r.status_code == 200:
                    res = r.json().get("results", [])
            except Exception:
                pass
        if res is not None:
            break
        await asyncio.sleep(4 * 2 ** attempt)
    if res is None:
        return {"type": "app_store", "ok": False, "detail": "itunes_error"}
    label = domain.split(".")[0]
    generic = {"toys", "fashion", "beauty", "home", "kids", "baby", "market", "shop", "store", "online", "mall", "sport", "sports", "wear", "outlet", "depot"}
    strong_toks = [t for t in toks if t not in generic] or toks
    for a in res:
        title = (a.get("trackName") or "").lower()
        seller = (a.get("sellerName") or "").lower()
        surl = (a.get("sellerUrl") or "").lower()
        match = (len(label) >= 4 and label in surl) or (all(t in title or t in seller for t in strong_toks[:2]) and len("".join(strong_toks[:2])) >= 4)
        if not match or a.get("primaryGenreName") not in SHOP_GENRES:
            continue
        rel = (a.get("currentVersionReleaseDate") or "")[:10]
        try:
            age = (NOW.date() - dt.date.fromisoformat(rel)).days
        except ValueError:
            age = 9999
        if age <= 450:
            return {"type": "app_store", "ok": True, "url": a.get("trackViewUrl"), "date": rel.replace("-", ""),
                    "detail": f"{M.appstore_country.upper()} App Store {a.get('primaryGenreName')} app '{a.get('trackName')}' by {a.get('sellerName')}, updated {rel}"}
    return {"type": "app_store", "ok": False, "detail": f"no current shopping app matching {term!r}"}


EDGAR_UA = {"User-Agent": "mkt-ecom-directory-research research-contact@example.com", "Accept-Encoding": "gzip, deflate"}
EDGAR_ALIASES = {
    "marshalls.com": "TJX COMPANIES", "homegoods.com": "TJX COMPANIES", "tjx.com": "TJX COMPANIES", "tjmaxx.com": "TJX COMPANIES",
    "ralphs.com": "KROGER", "fredmeyer.com": "KROGER", "kingsoopers.com": "KROGER", "harristeeter.com": "KROGER",
    "frysfood.com": "KROGER", "smithsfoodanddrug.com": "KROGER", "familydollar.com": "DOLLAR TREE",
    "oldnavy.com": "GAP INC", "gap.com": "GAP INC", "bananarepublic.com": "GAP INC", "athleta.com": "GAP INC",
    "potterybarn.com": "WILLIAMS SONOMA", "westelm.com": "WILLIAMS SONOMA", "williams-sonoma.com": "WILLIAMS SONOMA",
    "rh.com": "RH", "dell.com": "DELL TECHNOLOGIES", "samsclub.com": "WALMART", "walmart.com": "WALMART",
    "safeway.com": "ALBERTSONS COMPANIES", "albertsons.com": "ALBERTSONS COMPANIES", "bjs.com": "BJS WHOLESALE CLUB HOLDINGS",
    "oreillyauto.com": "O REILLY AUTOMOTIVE", "ikea.com": "", "hp.com": "HP INC", "ray-ban.com": "",
    "victoriassecret.com": "VICTORIAS SECRET", "bathandbodyworks.com": "BATH & BODY WORKS", "harborfreight.com": "",
    "gamestop.com": "GAMESTOP", "jcpenney.com": "", "dillards.com": "DILLARDS", "academy.com": "ACADEMY SPORTS",
    "autozone.com": "AUTOZONE", "petco.com": "PETCO HEALTH", "sweetwater.com": "", "guitarcenter.com": "",
    "garmin.com": "GARMIN", "dyson.com": "", "lenovo.com": "", "sony.com": "", "lg.com": "",
}
_EDGAR = {"tickers": None}


def _norm_co(n):
    n = re.sub(r"[^a-z0-9& ]", " ", n.lower().replace("'", ""))
    n = re.sub(r"\b(inc|corp|corporation|co|company|companies|holdings|the|new|de|plc|ltd|group|stores|class a|us|usa)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


async def sec_edgar(client, name, root, brand_url_name=None):
    if _EDGAR["tickers"] is None:
        try:
            r = await client.get("https://www.sec.gov/files/company_tickers.json", headers=EDGAR_UA, timeout=40)
            _EDGAR["tickers"] = [(_norm_co(v["title"]), v["cik_str"], v["title"]) for v in r.json().values()]
        except Exception:
            _EDGAR["tickers"] = []
    alias = EDGAR_ALIASES.get(root)
    if alias == "":
        return {"type": "sec_edgar", "ok": False, "detail": "not an SEC registrant (private or foreign filer)"}
    want = _norm_co(alias or re.split(r"[(/]", name)[0])
    if not want:
        return {"type": "sec_edgar", "ok": False, "detail": "no name"}
    hits = [t for t in _EDGAR["tickers"] if t[0] == want] or [t for t in _EDGAR["tickers"] if t[0].startswith(want + " ") or want.startswith(t[0] + " ") and len(t[0]) >= 4]
    if not hits:
        return {"type": "sec_edgar", "ok": False, "detail": f"no SEC registrant matching {want!r}"}
    _, cik, title = hits[0]
    try:
        r = await client.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", headers=EDGAR_UA, timeout=40)
        rec = r.json()["filings"]["recent"]
    except Exception:
        return {"type": "sec_edgar", "ok": False, "detail": "submissions_fetch_failed"}
    for form, fdate, doc, acc in zip(rec["form"], rec["filingDate"], rec["primaryDocument"], rec["accessionNumber"]):
        if form != "10-K":
            continue
        age = (NOW.date() - dt.date.fromisoformat(fdate)).days
        if age > 550:
            break
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
        await asyncio.sleep(0.3)
        try:
            d = await client.get(url, headers=EDGAR_UA, timeout=90)
        except httpx.HTTPError:
            return {"type": "sec_edgar", "ok": False, "detail": "10k_fetch_failed"}
        txt = re.sub(r"<[^>]+>", " ", d.text).lower()
        txt = re.sub(r"\s+", " ", txt)
        label = root.split(".")[0]
        brand = want.split(" ")[0]
        mention = [m.start() for m in re.finditer(re.escape(label) + r"\.com|" + re.escape(label.replace("-", " ")) + r"\b", txt)]
        us = "united states" in txt
        for i in mention:
            window = txt[max(0, i - 1200): i + 1200]
            if us and re.search(r"e-commerce|ecommerce|online sales|digital sales|online channel|online stores?|our websites?|website", window):
                snippet = txt[max(0, i - 150): i + 200]
                return {"type": "sec_edgar", "ok": True, "url": url, "date": fdate.replace("-", ""),
                        "detail": f"{title} 10-K filed {fdate} mentions {label} next to e-commerce/website language (US operations): ...{snippet}..."}
        return {"type": "sec_edgar", "ok": False, "detail": f"10-K {fdate} of {title} does not name {label}.com with ecommerce language"}
    return {"type": "sec_edgar", "ok": False, "detail": "no recent 10-K"}


async def google_play(client, name, domain):
    toks = name_tokens(name) or [domain.split(".")[0]]
    label = domain.split(".")[0]
    try:
        r = await client.get("https://play.google.com/store/search", params={"q": " ".join(toks[:3]), "c": "apps", "hl": "en", "gl": "US"}, timeout=30)
    except httpx.HTTPError:
        return {"type": "google_play", "ok": False, "detail": "play_fetch_failed"}
    ids = []
    for i in re.findall(r"details\?id=([A-Za-z0-9._]+)", r.text):
        if i not in ids:
            ids.append(i)
    for pid in ids[:5]:
        await asyncio.sleep(1.5)
        try:
            d = await client.get("https://play.google.com/store/apps/details", params={"id": pid, "hl": "en", "gl": "US"}, timeout=30)
        except httpx.HTTPError:
            continue
        if d.status_code != 200:
            continue
        t = d.text.lower()
        if len(label) >= 4 and re.search(r"https?://[a-z0-9.-]*" + re.escape(label) + r"\.", t) and ("shopping" in t or "shop" in t):
            return {"type": "google_play", "ok": True, "url": f"https://play.google.com/store/apps/details?id={pid}", "date": NOW.strftime("%Y%m%d"),
                    "detail": f"Google Play listing {pid} (US) links to {label} domain; listing live on check date"}
    return {"type": "google_play", "ok": False, "detail": "no matching Google Play listing"}


def live_storefront(con, key):
    row = con.execute("SELECT final_url, ecom_evidence, market_evidence, verified_at, reason FROM verifications WHERE key=?", (key,)).fetchone()
    if not row or not row[1]:
        return {"type": "live_storefront", "ok": False, "detail": "no live evidence"}
    try:
        e = json.loads(row[1])
        m = json.loads(row[2] or "{}")
    except ValueError:
        return {"type": "live_storefront", "ok": False, "detail": "bad json"}
    foreign = any(k in m for k in ("other_currency", "foreign_prices", "foreign_cctld"))
    if e.get("product_evidence") and e.get("purchase_evidence") and not foreign:
        return {"type": "live_storefront", "ok": True, "url": row[0], "date": (row[3] or "")[:10].replace("-", ""),
                "detail": "live homepage shows products (" + "; ".join(e["product_evidence"][:2]) + ") and purchase controls (" + "; ".join(e["purchase_evidence"][:2]) + ")"}
    return {"type": "live_storefront", "ok": False, "detail": "no product+purchase evidence on live homepage"}


async def check(clients, item, crawls, con=None):
    arch, live = clients
    prefix = re.sub(r"^www\d+\.", "www.", storefront_prefix(item["url"]))
    evs = await asyncio.gather(cc_product(arch, prefix, crawls), sitemap_ev(live, prefix), app_store(live, item["name"], item["root"]))
    ok = {e["type"] for e in evs if e.get("ok")}
    if len(ok) == 1 and ok & {"sitemap", "app_store"}:
        evs = list(evs) + [await wayback_product(arch, prefix)]
    ok = {e["type"] for e in evs if e.get("ok")}
    if len(ok) < 2 or not (ok & STOREFRONT_TYPES):
        extra = await asyncio.gather(sec_edgar(live, item["name"], item["root"]), google_play(live, item["name"], item["root"]))
        evs = list(evs) + list(extra)
        if con is not None:
            evs.append(live_storefront(con, item["key"]))
    ok = {e["type"] for e in evs if e.get("ok")}
    storefront = ok & STOREFRONT_TYPES
    verdict = "verified_secondary_evidence" if len(ok) >= 2 and (storefront or "sec_edgar" in ok or {"app_store", "google_play"} <= ok) else "insufficient_secondary_evidence"
    return {"key": item["key"], "prefix": prefix, "verdict": verdict, "evidence": evs}


def save(con, item, res):
    evs = [e for e in res["evidence"] if e.get("ok")]
    ev_text = " | ".join(f"{e['type']}: {e['detail']} ({e.get('url')}, {e.get('date')})" for e in evs)
    con.execute("CREATE TABLE IF NOT EXISTS secondary_evidence(key TEXT PRIMARY KEY, prefix TEXT, verdict TEXT, evidence TEXT, ts TEXT)")
    if res["verdict"] == "verified_secondary_evidence":
        sf = "https://" + res["prefix"]
        prod = next((e.get("url") for e in evs if e["type"] in ("commoncrawl_product", "wayback_product", "live_storefront")), None) or evs[0].get("url")
        n = con.execute("""UPDATE verifications SET status='verified_secondary_evidence', method='secondary', reason=?, product_evidence=?,
                       evidence_url=?, verified_at=?, store_name=CASE WHEN coalesce(store_name,'')='' THEN ? ELSE store_name END, final_url=?,
                       final_key=coalesce(final_key, key) WHERE key=?""",
                        ("verified_secondary_evidence: " + ev_text, prod, prod, db.now(), item["name"], sf, item["key"])).rowcount
        if n == 0:
            con.execute("INSERT OR REPLACE INTO verifications(key, final_url, final_key, store_name, status, reason, evidence_url, product_evidence, verified_at, method) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (item["key"], sf, item["key"], item["name"], "verified_secondary_evidence", "verified_secondary_evidence: " + ev_text, prod, prod, db.now(), "secondary"))
        con.execute("UPDATE candidates SET status='verified' WHERE key=?", (item["key"],))
    con.execute("INSERT OR REPLACE INTO secondary_evidence VALUES(?,?,?,?,?)", (item["key"], res["prefix"], res["verdict"], json.dumps(res["evidence"]), db.now()))


SECONDARY_REASONS = ("blocked_or_challenge%", "js_rendered%", "partial_ecommerce%", "insufficient_ecommerce%", "robots_disallowed%",
                     "fetch_failed%", "verification_timeout%", "rate_limited%", "weak_ecommerce%", "http_5%", "physical_goods_unclear%",
                     "weak_market%", "insufficient_market%", "no_ecommerce_evidence%", "service_style%", "likely_services%")


def targets(con, keys, limit, include_wikidata):
    if keys:
        q = f"SELECT c.key, coalesce(v.final_url, c.url), coalesce(r.name, v.store_name, c.key), c.root_domain FROM candidates c LEFT JOIN verifications v USING(key) LEFT JOIN reference_stores r ON r.key=c.key WHERE c.key IN ({','.join('?' * len(keys))})"
        rows = con.execute(q, keys).fetchall()
    else:
        cond = " OR ".join("v.reason LIKE ?" for _ in SECONDARY_REASONS)
        kinds = "('brand','wikidata')" if include_wikidata else "('brand')"
        rows = con.execute(f"""SELECT r.key, coalesce(v.final_url, r.url), r.name, r.root_domain FROM reference_stores r
            JOIN candidates c ON c.key=r.key LEFT JOIN verifications v ON v.key=r.key
            WHERE r.kind IN {kinds} AND coalesce(r.note,'')='' AND c.status IN ('unverified','rejected') AND ({cond})
            AND r.key NOT IN (SELECT key FROM secondary_evidence)
            ORDER BY CASE r.tier WHEN 'huge' THEN 0 WHEN 'large' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END LIMIT ?""", (*SECONDARY_REASONS, limit)).fetchall()
    return [{"key": k, "url": u if u.startswith("http") else "https://" + u, "name": n, "root": d or registrable_domain(urlsplit(u).hostname or "")} for k, u, n, d in rows]


async def main(keys, limit, concurrency, include_wikidata):
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS secondary_evidence(key TEXT PRIMARY KEY, prefix TEXT, verdict TEXT, evidence TEXT, ts TEXT)")
    items = targets(con, keys, limit, include_wikidata)
    print(f"[secondary] {len(items)} targets", flush=True)
    sem = asyncio.Semaphore(concurrency)
    stats = {"verified_secondary_evidence": 0, "insufficient_secondary_evidence": 0}
    async with httpx.AsyncClient(headers=UA_RESEARCH, follow_redirects=True) as arch, \
            httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True, verify=False) as live:
        crawls = await cc_crawls(arch)

        async def one(it):
            async with sem:
                try:
                    res = await asyncio.wait_for(check((arch, live), it, crawls, con), 600)
                except Exception as e:
                    print("[secondary] error", it["key"], type(e).__name__, str(e)[:120], flush=True)
                    return
            save(con, it, res)
            stats[res["verdict"]] += 1
            oks = [e["type"] for e in res["evidence"] if e.get("ok")]
            print(f"[secondary] {it['key']} -> {res['verdict']} {oks} {stats}", flush=True)
        await asyncio.gather(*(one(i) for i in items))
    print("[secondary] done", stats, flush=True)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--include-wikidata", action="store_true")
    a = ap.parse_args()
    asyncio.run(main([k for k in a.keys.split(",") if k], a.limit, a.concurrency, a.include_wikidata))
