"""Async live verifier for US non-Shopify stores.

Per candidate: robots.txt (cached), homepage, one platform probe (the public endpoint the storefront's own JS
uses: WooCommerce Store API, Big Cartel store.json/products.json, Magento GraphQL storeConfig, Squarespace
?format=json) and one product page. Bounded global concurrency, per-host / per-platform-bucket semaphores
with gaps, short timeouts and bounded exponential backoff; one slow host cannot block others.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import time
import urllib.robotparser
from collections import Counter, OrderedDict, defaultdict
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from . import db
from . import usignals as S
from .common_us import MARKETPLACE_ROOTS, identity

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
MAX_BYTES = 1_500_000
CHALLENGE = re.compile(r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|access denied|"
                       r"request could not be satisfied|pardon our interruption|captcha|are you a robot|incapsula|perimeterx|"
                       r"px-captcha|distil_r|ddos-guard|sucuri website firewall|_Incapsula_Resource|datadome", re.I)
TZ = re.compile(r"[\"'](?:time_?zone|timeZone|tz|timezone_string|iana_timezone)[\"']\s*:\s*[\"']((?:America|US|Pacific)/[A-Za-z_/]+)[\"']")
WIX_PTYPE = re.compile(r"[\"']productType[\"']\s*:\s*[\"'](physical|digital)[\"']", re.I)
SQ_PTYPE = re.compile(r"[\"'](?:product_type|productType|type)[\"']\s*:\s*[\"'](physical|digital|service|event|donation|prepared_food_and_beverage|food_and_beverage|membership)[\"']", re.I)
PRODUCT_URL = re.compile(r"/products?/[^/?#]+|/product-page/|/[a-z0-9-]+/p/[a-z0-9-]+|_p_\d+\.html|-p/[^/]+\.htm|productdetails\.asp|"
                         r"/catalog/product/view/|route=product/product|id_product=\d+|-p\d{6,}$|/item/|\.html$", re.I)
NON_PRODUCT_URL = re.compile(r"/product-category/|/category/|/collections?/?$|/tag/|/page/\d+|/cart|/checkout|/account|/login|/blog|"
                             r"/wp-content/|\.(?:jpg|jpeg|png|gif|webp|svg|pdf|css|js)(?:\?|$)", re.I)
WOO_DEMO = re.compile(r"^(?:hoodie(?: with (?:logo|zipper|pocket))?|beanie(?: with logo)?|album|single|t-shirt(?: with logo)?|cap|sunglasses|polo|belt|long sleeve tee|v-neck t-shirt|logo collection|wordpress pennant|sample product.*|product name|test product.*|product \d+)$", re.I)

MENU = re.compile(r"\b(?:americano|latte|cappuccino|espresso|macchiato|mocha|frapp[eé]|smoothie|milkshake|shake|lemonade|soda|iced tea|burrito|quesadilla|nachos|"
                  r"sandwich|sub|hoagie|wrap|salad|bowl|combo|meal|platter|fries|wings|burger|pizza|calzone|taco|entr[eé]e|appetizer|breakfast|lunch|dinner|"
                  r"plates?|omelet|pancakes?|waffles?|bagel|toast|soup|noodles?|ramen|pho|sushi|roll|curry|kebab|gyro|bbq plate|side of|add on|catering tray)\b", re.I)

BUCKETS = {"wix-edge": (14, 0.05), "square-edge": (10, 0.05), "sqs-edge": (12, 0.05), "wixsite.com": (6, 0.2), "square.site": (6, 0.2), "bigcartel.com": (4, 0.3), "mybigcommerce.com": (4, 0.3),
           "company.site": (4, 0.3), "squarespace.com": (4, 0.3), "3dcartstores.com": (3, 0.4), "weebly.com": (4, 0.3)}


SHARED_EDGE: dict[str, str] = {}


def bucket(host: str) -> str:
    if host in SHARED_EDGE:
        return SHARED_EDGE[host]
    for suf in BUCKETS:
        if host == suf or host.endswith("." + suf):
            return suf
    return host


class LRU(OrderedDict):
    def __init__(self, cap):
        super().__init__()
        self.cap = cap

    def put(self, k, v):
        self[k] = v
        self.move_to_end(k)
        while len(self) > self.cap:
            self.popitem(last=False)


class Fetcher:
    def __init__(self, concurrency: int, per_host: int):
        limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency // 2,
                              keepalive_expiry=10)
        self.client = httpx.AsyncClient(headers=HEADERS, follow_redirects=True, limits=limits, max_redirects=8,
                                        timeout=httpx.Timeout(15.0, connect=8.0), verify=False)
        self.global_sem = asyncio.Semaphore(concurrency)
        self.per_host = per_host
        self.host_sems: dict[str, asyncio.Semaphore] = {}
        self.host_last: dict[str, float] = defaultdict(float)
        self.host_gap: dict[str, float] = {}
        self.robots = LRU(20000)
        self.robots_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.stats = Counter()

    def _sem(self, b):
        if b not in self.host_sems:
            n, gap = BUCKETS.get(b, (self.per_host, 0.4))
            self.host_gap[b] = gap
            self.host_sems[b] = asyncio.Semaphore(n)
        return self.host_sems[b]

    async def _raw(self, url, headers=None, limit=MAX_BYTES):
        async with self.client.stream("GET", url, headers=headers) as r:
            chunks, size = [], 0
            async for ch in r.aiter_bytes():
                chunks.append(ch)
                size += len(ch)
                if size >= limit:
                    break
            body = b"".join(chunks)
            enc = r.encoding or "utf-8"
            try:
                text = body.decode(enc, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return r.status_code, str(r.url), text, r.headers

    async def allowed(self, url) -> bool:
        sp = urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        async with self.robots_lock[base]:
            if base not in self.robots:
                rp = None
                try:
                    async with self.global_sem:
                        st, _, txt, _ = await asyncio.wait_for(self._raw(base + "/robots.txt", limit=200_000), 12)
                    self.stats["requests"] += 1
                    if st == 200 and "<html" not in txt[:400].lower():
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(txt.splitlines())
                        try:
                            cd = rp.crawl_delay("*")
                        except Exception:
                            cd = None
                        if cd:
                            b = bucket(sp.hostname or "")
                            self._sem(b)
                            self.host_gap[b] = max(self.host_gap[b], min(float(cd), 10.0))
                    elif st in (401, 403):
                        rp = "deny"
                except Exception:
                    rp = None
                self.robots.put(base, rp)
            self.robots_lock.pop(base, None)
        rp = self.robots.get(base)
        if rp is None:
            return True
        if rp == "deny":
            return False
        try:
            return rp.can_fetch("*", url) or rp.can_fetch(UA, url)
        except Exception:
            return True

    async def get(self, url, headers=None, tries=2, check_robots=True, timeout=20):
        """Return (status, final_url, text, headers, error)."""
        if check_robots and not await self.allowed(url):
            self.stats["robots_disallowed"] += 1
            return None, url, "", {}, "robots_disallowed"
        b = bucket(urlsplit(url).hostname or "")
        delay = 2.0
        last = None
        for attempt in range(tries):
            async with self._sem(b):
                async with self.global_sem:
                    gap = time.monotonic() - self.host_last[b]
                    if gap < self.host_gap[b]:
                        await asyncio.sleep(self.host_gap[b] - gap)
                    self.host_last[b] = time.monotonic()
                    try:
                        st, final, text, hdrs = await asyncio.wait_for(self._raw(url, headers), timeout)
                        self.stats["requests"] += 1
                        if st == 429:
                            self.stats["http_429"] += 1
                            self.host_gap[b] = min(self.host_gap[b] * 1.6 + 0.3, 8.0)
                        if st in (429, 502, 503, 504) and attempt < tries - 1 and not CHALLENGE.search(text[:4000]):
                            last = f"http_{st}"
                        else:
                            return st, final, text, hdrs, None
                    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                        m = str(e)
                        if "Name or service not known" in m or "No address associated" in m or "nodename nor servname" in m:
                            return None, url, "", {}, "dns_not_resolved"
                        last = "connect_error" + (":" + re.sub(r"\s+", " ", m)[:60] if m else "")
                        if "SSL" in m and "WRONG_VERSION" not in m and attempt >= 1:
                            break
                    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, asyncio.TimeoutError):
                        last = "timeout"
                        break
                    except httpx.TooManyRedirects:
                        return None, url, "", {}, "too_many_redirects"
                    except (httpx.HTTPError, UnicodeError, ValueError, OSError) as e:
                        last = f"http_error:{type(e).__name__}"
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, 10)
        self.stats["failed_fetch"] += 1
        return None, url, "", {}, last


def jload(txt):
    try:
        return json.loads(txt)
    except ValueError:
        return None


async def probe_woo(f, base):
    st, fin, txt, _, err = await f.get(urljoin(base, "/wp-json/wc/store/v1/products?per_page=20"), tries=1)
    if st != 200 or not txt.lstrip().startswith("["):
        st, fin, txt, _, err = await f.get(urljoin(base, "/wp-json/wc/store/products?per_page=20"), tries=1)
    if st != 200 or not txt.lstrip().startswith("["):
        return None
    prods = jload(txt) or []
    if not isinstance(prods, list):
        return None
    cur = sorted({(p.get("prices") or {}).get("currency_code") for p in prods if isinstance(p, dict) and p.get("prices")} - {None, ""})
    names = [S.clean(p.get("name")) for p in prods if isinstance(p, dict)]
    return {"api": "woocommerce_store_api", "url": fin, "n": len(prods), "currency": cur, "names": names[:20],
            "purchasable": sum(1 for p in prods if isinstance(p, dict) and p.get("is_purchasable")),
            "demo": sum(1 for n in names if WOO_DEMO.match(n)),
            "sample_url": next((p.get("permalink") for p in prods if isinstance(p, dict) and p.get("permalink")), None),
            "priced": sum(1 for p in prods if isinstance(p, dict) and str((p.get("prices") or {}).get("price") or "0") not in ("0", ""))}


async def probe_bigcartel(f, base):
    out = {}
    st, fin, txt, _, _ = await f.get(urljoin(base, "/store.json"), tries=1, check_robots=False)
    if st == 200 and txt.lstrip().startswith("{"):
        d = jload(txt) or {}
        out.update({"api": "bigcartel_store_json", "url": fin, "store_name": d.get("name"),
                    "currency": ((d.get("currency") or {}).get("code")), "country": ((d.get("country") or {}).get("code")),
                    "products_count": d.get("products_count")})
    st, fin, txt, _, _ = await f.get(urljoin(base, "/products.json"), tries=1, check_robots=False)
    if st == 200 and txt.lstrip().startswith("["):
        prods = jload(txt) or []
        out["n"] = len(prods)
        out["names"] = [S.clean(p.get("name")) for p in prods][:20]
        out["purchasable"] = sum(1 for p in prods if p.get("status") == "active")
        out["sample_url"] = urljoin(base, prods[0].get("url")) if prods and prods[0].get("url") else None
    return out or None


async def probe_magento(f, base):
    q = "{storeConfig{base_currency_code default_display_currency_code locale timezone weight_unit store_name}}"
    st, fin, txt, _, _ = await f.get(urljoin(base, "/graphql?query=" + q), headers={"Accept": "application/json"}, tries=1)
    if st == 200 and txt.lstrip().startswith("{"):
        d = ((jload(txt) or {}).get("data") or {}).get("storeConfig") or {}
        if d:
            return {"api": "magento_graphql_storeConfig", "url": fin, "currency": d.get("default_display_currency_code") or d.get("base_currency_code"),
                    "timezone": d.get("timezone"), "weight_unit": d.get("weight_unit"), "locale": d.get("locale")}
    return None


async def probe_squarespace(f, url):
    st, fin, txt, _, _ = await f.get(url + ("&" if "?" in url else "?") + "format=json", tries=1)
    if st != 200 or not txt.lstrip().startswith("{"):
        return None
    d = jload(txt) or {}
    ws = d.get("websiteSettings") or {}
    web = d.get("website") or {}
    store = ws.get("storeSettings") or {}
    loc = store.get("contactLocation") or web.get("location") or {}
    item = d.get("item") or {}
    out = {"api": "squarespace_format_json", "url": fin, "currency": store.get("selectedCurrency"),
           "country": ws.get("country") or (loc.get("addressCountry") if isinstance(loc, dict) else None),
           "timezone": web.get("timeZone")}
    if item:
        out["product_type"] = {1: "physical", 2: "digital", 3: "service", 4: "gift_card"}.get(item.get("productType"), item.get("productType"))
    return out


SQ_COUNTRY = re.compile(r'"isSquareSyncUser":(?:true|false),"country":"([A-Z]{2})"|"properties":\{[^{}]{0,200}"country":"([A-Z]{2})"')
SQ_STORE = re.compile(r'"storeInfo":\{"merchant_id":"([A-Z0-9]+)"[^{}]{0,200}?"currency":"([A-Z]{3})"')


async def probe_square(f, html, base):
    out = {}
    m = SQ_STORE.search(html)
    if m:
        out.update({"api": "square_online_storeInfo", "merchant_id": m.group(1), "currency": m.group(2)})
    m = SQ_COUNTRY.search(html)
    if m:
        out["country"] = m.group(1) or m.group(2)
    m = re.search(r'"fulfillment_support":\{([^{}]*)\}', html)
    if m:
        out["fulfillment"] = sorted(k for k, v in re.findall(r'"([a-z_]+)":(true|false)', m.group(1)) if v == "true")
    st, _, txt, _, _ = await f.get(urljoin(base, "/sitemap.xml"), tries=1)
    if st == 200 and "<loc>" in txt:
        locs = re.findall(r"<loc>\s*([^<\s]+/product/[^<\s]+)\s*</loc>", txt)
        if locs:
            out["n_sitemap_products"] = len(locs)
            out["sample_url"] = locs[0]
            out["names"] = [unquote(u.rstrip("/").split("/")[-2]).replace("-", " ") for u in locs[:40]]
    return out or None


PRICE_ATTR = re.compile(r'data-price-amount="\d|itemprop="price"[^>]{0,60}content="\d|property="(?:product:price:amount|og:price:amount)"|og:type"\s+content="product', re.I)
BIGC_CARD = re.compile(r'<a[^>]+href="([^"#]+)"[^>]*(?:data-event-type="product-click"|class="[^"]*(?:card-figure__link|product-item-link|woocommerce-LoopProduct-link|product-thumbnail|product-item-photo)[^"]*")'
                       r'|class="[^"]*(?:card-figure__link|product-item-link|woocommerce-LoopProduct-link|product-thumbnail|product-item-photo)[^"]*"[^>]*href="([^"#]+)"', re.I)


def analyze(html, url):
    text = S.visible_text(html, limit=MAX_BYTES)
    links = [m.group(1) for m in S.PRODUCT_LINK.finditer(html[:MAX_BYTES])]
    links += [a or b for a, b in BIGC_CARD.findall(html[:MAX_BYTES])]
    return {"text": text, "title": S.title_of(html), "desc": S.meta(html, "description") or S.meta(html, "og:description") or "",
            "platform": S.detect_platform(html, url), "links": links,
            "atc": len(S.ADD_TO_CART.findall(html[:MAX_BYTES])), "cart": len(S.CART_CHECKOUT.findall(html[:MAX_BYTES])),
            "ld": S.jsonld_types(html)[0], "prices": len(S.PRICE_DOLLAR.findall(text)) + len(S.PRICE_USD.findall(text)) + len(PRICE_ATTR.findall(html[:MAX_BYTES]))}


def pick_product_urls(final, root, a, probe, cand, n=2):
    host = urlsplit(final).netloc
    opts = []
    if probe and probe.get("sample_url"):
        opts.append(probe["sample_url"])
    for l in a["links"]:
        full = urljoin(final, l)
        if not NON_PRODUCT_URL.search(full):
            opts.append(full)
    s = cand.get("sample_url")
    if s and PRODUCT_URL.search(s) and not NON_PRODUCT_URL.search(s):
        opts.append(s)
    out = []
    for u in opts:
        try:
            uh = urlsplit(u).netloc
        except ValueError:
            continue
        if (uh == host or (root and uh.endswith(root))) and "/product-category/" not in u:
            u = u.replace("http://", "https://", 1) if final.startswith("https://") else u
            if u not in out:
                out.append(u)
        if len(out) >= n:
            break
    return out


INFO_LINK = re.compile(r"href=[\"']([^\"'#<>\s]{0,200}(?:contact|about|shipping|delivery|policies|policy|faq|location|store-info|terms)[^\"'#<>\s]{0,80})[\"']", re.I)


async def fetch_info_pages(f, final, html, n=2):
    host = urlsplit(final).netloc
    seen, texts, htmls, urls = set(), [], [], []
    for m in INFO_LINK.finditer(html[:MAX_BYTES]):
        u = urljoin(final, m.group(1))
        if urlsplit(u).netloc != host or u in seen or re.search(r"\.(?:pdf|jpg|png)$|privacy|cookie|login|account", u, re.I):
            continue
        seen.add(u)
        if len(seen) > n:
            break
        st, fin, h, _, _ = await f.get(u, tries=1)
        if st == 200 and h:
            htmls.append(h[:400000])
            texts.append(S.visible_text(h, limit=400000)[:100000])
            urls.append(fin)
    return " ".join(htmls), " ".join(texts), urls


async def verify_one(f: Fetcher, cand: dict) -> dict:
    t0 = time.monotonic()
    key, url = cand["key"], cand["url"]
    res = {"key": key, "final_url": url, "final_key": key, "http_status": None, "store_name": "", "platform": cand.get("platform_hint") or "",
           "category": "", "us_score": 0, "us_evidence": "{}", "ecom_evidence": "{}", "product_evidence": "", "status": "unverified",
           "reason": "", "evidence_url": url, "verified_at": db.now(), "method": "http"}

    def done(status, reason):
        res["status"], res["reason"] = status, reason[:400]
        res["elapsed"] = round(time.monotonic() - t0, 2)
        res["verified_at"] = db.now()
        return res

    if cand.get("root_domain") in MARKETPLACE_ROOTS:
        return done("rejected", "excluded_marketplace: " + MARKETPLACE_ROOTS[cand["root_domain"]])
    edge = {"wix": "wix-edge", "square": "square-edge", "squarespace": "sqs-edge"}.get(cand.get("platform_hint") or "")
    if edge and cand.get("root_domain") not in ("wixsite.com", "square.site", "squarespace.com"):
        h0 = urlsplit(url).hostname or ""
        for h in {h0, h0[4:] if h0.startswith("www.") else "www." + h0}:
            SHARED_EDGE[h] = edge
    st, final, html, hdrs, err = await f.get(url)
    if st is None and (err or "").split(":")[0] in ("connect_error", "timeout") and url.startswith("https://") and cand.get("platform_hint") not in ("wix", "square", "bigcartel"):
        host = urlsplit(url).hostname or ""
        alt = url.replace("://", "://www.", 1) if not host.startswith("www.") and host.count(".") == 1 else "http://" + url[8:]
        st, final, html, hdrs, err = await f.get(alt, tries=1)
    res["http_status"], res["final_url"], res["evidence_url"] = st, final, final
    if st is None:
        if err == "dns_not_resolved":
            return done("rejected", "dns_not_resolved")
        if err == "robots_disallowed":
            return done("unverified", "robots_disallowed_homepage")
        return done("unverified", f"fetch_failed:{err}")
    fid = identity(final)
    res["final_key"] = fid["key"] if fid else None
    if fid and fid["root_domain"] in MARKETPLACE_ROOTS:
        return done("rejected", "redirects_to_marketplace:" + fid["root_domain"])
    if fid is None and urlsplit(final).hostname and any(urlsplit(final).hostname.endswith(x) for x in ("wix.com", "squarespace.com", "bigcartel.com", "square.site", "weebly.com", "godaddy.com", "shopify.com", "ecwid.com", "bigcommerce.com")):
        return done("rejected", "redirects_to_platform_page (store removed/expired): " + final[:80])
    head = html[:6000]
    if st == 429:
        return done("unverified", "rate_limited_http_429")
    if st in (401, 403, 503) or (st >= 400 and CHALLENGE.search(head)) or (st == 200 and CHALLENGE.search(head) and len(html) < 15000):
        return done("unverified", f"blocked_or_challenge_http_{st}")
    if st in (404, 410):
        return done("rejected", f"http_{st}")
    if st >= 400:
        return done("unverified", f"http_{st}")

    a = analyze(html, final)
    plat = a["platform"]
    if plat == "custom/unknown" and cand.get("platform_hint"):
        plat_note = "hint:" + cand["platform_hint"]
    else:
        plat_note = ""
    res["platform"] = plat if plat != "custom/unknown" else (cand.get("platform_hint") or plat)
    if plat == "shopify":
        res["platform"] = "shopify"
    res["store_name"] = S.clean(S.store_name(html, key, urlsplit(final).hostname or ""))[:120]
    short = len(a["text"]) < 3500
    head_text = a["title"] + " " + a["text"][:4000]
    pk = (S.PARKED.search(head_text) if short else None) or (S.PARKED_TITLE.search(a["title"]) if len(a["text"]) < 2500 else None)
    if pk:
        return done("rejected", "parked_or_placeholder: " + pk.group(0)[:60])
    m = S.CLOSED.search(head_text) if len(a["text"]) < 8000 else None
    if m or "password-page" in html[:30000] and short:
        return done("rejected", "store_closed_or_maintenance" + (": " + m.group(0) if m else ""))

    if re.search(r"(?:^|[.\-/])(?:demo|sandbox|staging|test|dev)\d*[.\-]|-demo\.|demo-store|teststore", key, re.I) or re.match(r"^(?:demo|test) ?store$", res["store_name"] or "", re.I):
        return done("rejected", "demo_or_test_store")
    root = fid["root_domain"] if fid else ""
    base = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}/"
    if fid and fid["platform_hint"] is None and fid["key"].endswith("|us"):
        base = fid["url"]
    probe = None
    try:
        if plat == "woocommerce":
            probe = await probe_woo(f, base)
        elif plat == "bigcartel":
            probe = await probe_bigcartel(f, base)
        elif plat == "magento":
            probe = await probe_magento(f, base)
        elif plat == "squarespace":
            probe = await probe_squarespace(f, final)
        elif plat == "square":
            probe = await probe_square(f, html, base)
    except Exception as e:
        probe = {"error": type(e).__name__}
    api = {}
    if probe:
        for k in ("currency", "country", "timezone", "weight_unit"):
            if probe.get(k):
                api[k] = probe[k]
    tzm = TZ.search(html[:800000])
    if tzm and "timezone" not in api:
        api["timezone"] = tzm.group(1)

    # product page
    purls = pick_product_urls(final, root, a, probe, cand)
    p_html, p_final, p_st, perr = "", None, None, None
    pa = None
    for purl in purls:
        p_st, p_final, p_html, _, perr = await f.get(purl, tries=2)
        if p_st == 200 and p_html:
            pa = analyze(p_html, p_final)
            if plat == "squarespace" and not (probe or {}).get("product_type"):
                sq = await probe_squarespace(f, p_final)
                if sq:
                    probe = {**(probe or {}), **{k: v for k, v in sq.items() if v}}
                    for k in ("currency", "country", "timezone"):
                        if sq.get(k):
                            api[k] = sq[k]
            break
        p_html = ""
    product_fetch_failed = bool(purls) and pa is None and (perr or (p_st or 0) >= 500)
    ecom = {"platform": plat, "platform_note": plat_note, "home_product_links": len(a["links"]), "home_add_to_cart": a["atc"],
            "home_cart_markers": a["cart"], "home_prices": a["prices"], "jsonld": sorted(a["ld"] & {"Product", "Offer", "AggregateOffer", "ItemList", "OnlineStore", "Store"})}
    if probe:
        ecom["probe"] = {k: v for k, v in probe.items() if k != "names"}
    if pa:
        ecom["product_page"] = {"url": p_final, "add_to_cart": pa["atc"], "prices": pa["prices"], "jsonld": sorted(pa["ld"] & {"Product", "Offer", "AggregateOffer"}),
                                "title": pa["title"][:100]}
    res["product_evidence"] = p_final if pa else ((probe or {}).get("sample_url") or "")

    names = list((probe or {}).get("names") or [])
    if pa:
        names.append(S.meta(p_html, "og:title") or pa["title"])
    # physical vs digital / services / food from platform data
    ptypes = Counter()
    for h in (html, p_html):
        for m2 in WIX_PTYPE.finditer(h[:MAX_BYTES]):
            ptypes[m2.group(1).lower()] += 1
        if plat == "square":
            for m2 in SQ_PTYPE.finditer(h[:MAX_BYTES]):
                ptypes[m2.group(1).lower()] += 1
    if (probe or {}).get("product_type"):
        ptypes[str(probe["product_type"])] += 3
    if ptypes:
        ecom["product_types"] = dict(ptypes)
    phys = ptypes.get("physical", 0)
    food = ptypes.get("prepared_food_and_beverage", 0) + ptypes.get("food_and_beverage", 0)
    nonphys = sum(v for k, v in ptypes.items() if k not in ("physical", "prepared_food_and_beverage", "food_and_beverage"))
    if food and food >= phys:
        return done("rejected", f"restaurant_or_prepared_food (platform product types {dict(ptypes)})") | {"ecom_evidence": json.dumps(ecom)}
    if nonphys and not phys:
        return done("rejected", f"no_physical_products (platform product types {dict(ptypes)})") | {"ecom_evidence": json.dumps(ecom)}
    if probe and probe.get("api") == "woocommerce_store_api" and probe.get("n"):
        if probe.get("demo", 0) >= max(2, probe["n"] // 2):
            return done("rejected", "theme_demo_products_only (woocommerce sample data)")
    if plat == "square" and probe and probe.get("fulfillment") is not None:
        ful = probe["fulfillment"]
        if ful == ["digital"]:
            return done("rejected", "no_physical_products (square fulfillment: digital only)")
        if "shipping" not in ful:
            menu = [n for n in names if n and MENU.search(n)]
            if ful and set(ful) <= {"pickup", "delivery", "dine_in", "manual"} and (len(menu) >= max(2, len(names) // 3) or "dine_in" in ful):
                return done("rejected", f"restaurant_or_local_food_ordering (square fulfillment {ful}; menu-like items {len(menu)}/{len(names)})")
            return done("unverified", f"no_shipping_fulfillment (square fulfillment {ful or 'none'}: local pickup/delivery only)")
    menu = [n for n in names if n and MENU.search(n)]
    if menu and S.FOOD_NAME.search((res["store_name"] or "") + " " + a["title"]) and len(menu) >= 0.2 * len(names) and not phys:
        return done("rejected", f"restaurant_or_food_service (name '{S.FOOD_NAME.search((res['store_name'] or '') + ' ' + a['title']).group(0)}'; menu-like items {len(menu)}/{len(names)})")
    if len(names) >= 4 and len(menu) >= 0.35 * len(names) and not phys:
        return done("rejected", f"restaurant_or_cafe_menu_items ({len(menu)}/{len(names)}: {' / '.join(x[:25] for x in menu[:3])})")
    svc_names = [n for n in names if n and (S.DIGITAL.search(n) or S.SERVICE.search(n))]
    if len(names) >= 3 and len(svc_names) >= 0.5 * len(names) and not phys:
        return done("rejected", f"mostly_services_or_digital_by_product_names ({len(svc_names)}/{len(names)}: {' / '.join(x[:30] for x in svc_names[:3])})")

    product_ev, purchase_ev = [], []
    if probe and probe.get("n"):
        product_ev.append(f"{probe['n']} products via {probe.get('api')}")
    if pa and (pa["prices"] or pa["ld"] & {"Product", "Offer"}):
        product_ev.append("product page with price" + (" + schema.org Product" if "Product" in pa["ld"] else ""))
    sq_title = S.clean(S.meta(p_html, "og:title") or "") if pa else ""
    sq_ok = bool(plat == "square" and probe and probe.get("merchant_id") and pa and "/product/" in (p_final or "") and sq_title
                 and sq_title.split(" | ")[0].strip().lower() != (res["store_name"] or "").strip().lower())
    if sq_ok:
        product_ev.append(f"Square Online product page (JS-rendered): {S.clean(S.meta(p_html, 'og:title'))[:60]}"
                          + (f"; {probe.get('n_sitemap_products')} product URLs in sitemap" if probe.get("n_sitemap_products") else ""))
        purchase_ev.append(f"Square Online store checkout (merchant {probe['merchant_id']})")
    if len(a["links"]) >= 3:
        product_ev.append(f"{len(a['links'])} product links on homepage")
    if "Product" in a["ld"] or "Offer" in a["ld"]:
        product_ev.append("schema.org Product/Offer on homepage")
    if probe and probe.get("purchasable"):
        purchase_ev.append(f"{probe['purchasable']} purchasable products ({probe.get('api')})")
    if pa and pa["atc"]:
        purchase_ev.append("add-to-cart on product page")
    if a["atc"]:
        purchase_ev.append("add-to-cart markers on homepage")
    if a["cart"] >= 2 or (pa and pa["cart"] >= 2):
        purchase_ev.append("cart/checkout markers")
    ecom["product_evidence"], ecom["purchase_evidence"] = product_ev, purchase_ev
    res["ecom_evidence"] = json.dumps(ecom, ensure_ascii=False)

    blob_html = html + (p_html[:400000] if p_html else "")
    blob_text = a["text"] + " " + (pa["text"][:100000] if pa else "")
    score, ev = S.us_signals(blob_html, blob_text, final, api)
    res["us_score"] = round(score, 2)
    res["us_evidence"] = json.dumps(ev, ensure_ascii=False)
    cat_texts = [a["title"] + " " + res["store_name"], a["desc"], S.meta(html, "keywords") or "", " ".join(names), a["text"][:6000]]
    res["category"] = S.classify(cat_texts, [6, 4, 2, 3, 1])

    if plat == "shopify":
        return done("rejected", "shopify_store (out of shard scope: non-Shopify platforms)")
    strong_product = (bool(probe and probe.get("n")) or bool(pa and (pa["prices"] or "Product" in pa["ld"])) or sq_ok
                      or bool(pa and pa["atc"] and len(a["links"]) >= 5))
    has_purchase = bool(purchase_ev) or (plat in ("bigcommerce", "magento", "salesforce-commerce", "volusion", "shift4shop", "bigcartel", "ecwid", "prestashop", "opencart", "shopware") and a["cart"] >= 1)
    if not product_ev and not purchase_ev:
        if len(a["text"]) < 1500 and html.count("<script") >= 3:
            return done("unverified", "js_rendered_or_thin_page (no ecommerce evidence in static HTML)")
        return done("rejected", "no_ecommerce_evidence (no products / cart found)")
    if (not strong_product or not has_purchase) and product_fetch_failed:
        return done("unverified", f"product_page_fetch_failed:{perr or p_st} (retry later); " + ",".join(product_ev + purchase_ev))
    if not strong_product or not has_purchase:
        return done("unverified", "insufficient_ecommerce_evidence: " + (",".join(product_ev + purchase_ev) or "none"))

    blob = a["title"] + " " + a["desc"] + " " + a["text"][:15000] + " " + " ".join(names)
    n_rest = len(S.RESTAURANT.findall(a["title"] + " " + a["desc"] + " " + a["text"][:8000]))
    n_svc = len(S.SERVICE.findall(a["title"] + " " + a["desc"] + " " + a["text"][:8000]))
    n_dig = len(S.DIGITAL.findall(blob))
    if not phys:
        if n_rest >= 6 and res["category"] not in ("Food & Beverage", "Home & Garden"):
            return done("rejected", f"likely_restaurant_or_food_service ({n_rest} markers)")
        if n_rest >= 8:
            return done("unverified", f"possible_restaurant_or_food_service ({n_rest} markers; manual review)")
        if n_svc >= 8 and not (pa and pa["atc"]):
            return done("rejected", f"likely_services ({n_svc} markers)")
        if n_dig >= 8 and res["category"] in ("General Merchandise", "Books, Music & Media", "Office & School Supplies"):
            return done("unverified", f"possibly_digital_only ({n_dig} digital markers; manual review)")
    if S.ORG_NAME.search(res["store_name"] or "") and not phys:
        return done("unverified", "organization_or_service_name_with_shop (manual review): " + S.ORG_NAME.search(res["store_name"]).group(0))
    if S.MARKETPLACE_TEXT.search(blob):
        return done("unverified", "possible_multi_vendor_marketplace (manual review)")

    ust, ureason = S.us_verdict(score, ev)
    if ust == "unverified" and (ev.get("currency_USD") or ev.get("usd_prices") or ev.get("dollar_prices")):
        ih, it, iurls = await fetch_info_pages(f, final, html)
        if it:
            score, ev = S.us_signals(blob_html + ih, blob_text + " " + it, final, api)
            ev["info_pages"] = iurls[:2]
            res["us_score"] = round(score, 2)
            res["us_evidence"] = json.dumps(ev, ensure_ascii=False)
            ust, ureason = S.us_verdict(score, ev)
    if ust == "verified":
        notes = []
        if n_dig >= 4:
            notes.append(f"also some digital/service items ({n_dig})")
        return done("verified", "; ".join([f"store ok ({', '.join(product_ev[:2])}; {', '.join(purchase_ev[:2])}); {ureason}"] + notes))
    return done(ust, ureason)


COLS = ["key", "final_url", "final_key", "http_status", "store_name", "platform", "category", "us_score", "us_evidence",
        "ecom_evidence", "product_evidence", "status", "reason", "evidence_url", "verified_at", "method", "elapsed"]


def save_many(con, results):
    def _do():
        for res in results:
            res.setdefault("elapsed", 0)
            con.execute(f"INSERT OR REPLACE INTO verifications({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})", [res.get(c) for c in COLS])
            con.execute("UPDATE candidates SET status=?, attempts=attempts+1, last_attempt=? WHERE key=?", (res["status"], db.now(), res["key"]))
    db.retry(con, _do)


def claim(con, n, where):
    def _do():
        rows = con.execute(f"SELECT key,url,root_domain,platform_hint,priority,sample_url FROM candidates WHERE status='pending' {where} "
                           f"ORDER BY priority DESC, hits DESC LIMIT ?", (n,)).fetchall()
        con.executemany("UPDATE candidates SET status='in_progress', last_attempt=? WHERE key=?", [(db.now(), r[0]) for r in rows])
        return [dict(zip(("key", "url", "root_domain", "platform_hint", "priority", "sample_url"), r)) for r in rows]
    return db.retry(con, _do)


async def main(concurrency, per_host, worker, where, idle_exit, max_total):
    import warnings
    warnings.filterwarnings("ignore")
    con = db.connect()
    f = Fetcher(concurrency, per_host)
    q: asyncio.Queue = asyncio.Queue(maxsize=concurrency * 2)
    out: list = []
    stats = Counter()
    t0 = time.time()
    claimed = [0]

    async def producer():
        idle = None
        while True:
            if max_total and claimed[0] >= max_total:
                break
            if q.qsize() < concurrency:
                batch = claim(con, concurrency, where)
                if not batch:
                    idle = idle or time.time()
                    if time.time() - idle > idle_exit:
                        break
                    await asyncio.sleep(15)
                    continue
                idle = None
                claimed[0] += len(batch)
                for c in batch:
                    await q.put(c)
            else:
                await asyncio.sleep(0.3)
        for _ in range(concurrency):
            await q.put(None)

    async def consumer():
        while True:
            c = await q.get()
            if c is None:
                return
            try:
                r = await asyncio.wait_for(verify_one(f, c), 150)
            except asyncio.TimeoutError:
                r = {"key": c["key"], "final_url": c["url"], "status": "unverified", "reason": "verification_timeout", "verified_at": db.now(), "evidence_url": c["url"]}
            except Exception as e:
                r = {"key": c["key"], "final_url": c["url"], "status": "unverified", "reason": f"verifier_error:{type(e).__name__}:{str(e)[:80]}", "verified_at": db.now(), "evidence_url": c["url"]}
            out.append(r)
            stats[r["status"]] += 1
            stats["total"] += 1

    async def flusher():
        while True:
            await asyncio.sleep(5)
            if out:
                batch = out[:]
                del out[:len(batch)]
                try:
                    save_many(con, batch)
                except Exception as e:
                    out.extend(batch)
                    print(f"[verify:{worker}] save failed, will retry: {e!r}", flush=True)

    async def reporter():
        while True:
            await asyncio.sleep(60)
            el = time.time() - t0
            print(f"[verify:{worker}] {dict(stats)} per_min={stats['total'] / (el / 60):.0f} req={f.stats['requests']} "
                  f"429={f.stats['http_429']} robots_no={f.stats['robots_disallowed']}", flush=True)

    fl = asyncio.create_task(flusher())
    rep = asyncio.create_task(reporter())
    await asyncio.gather(producer(), *[consumer() for _ in range(concurrency)])
    fl.cancel()
    rep.cancel()
    if out:
        save_many(con, out)
    print(f"[verify:{worker}] finished {dict(stats)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=100)
    ap.add_argument("--per-host", type=int, default=2)
    ap.add_argument("--worker", default=f"w{os.getpid()}")
    ap.add_argument("--where", default="")
    ap.add_argument("--idle-exit", type=int, default=600)
    ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    asyncio.run(main(a.concurrency, a.per_host, a.worker, a.where, a.idle_exit, a.max))
