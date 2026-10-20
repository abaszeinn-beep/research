"""Async ecommerce + market-relevance verifier.

Claims pending candidates from SQLite (highest priority first) and verifies each against
its live website with bounded global concurrency, per-host politeness, timeouts and
bounded exponential-backoff retries. Runs concurrently with discovery processes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import socket
import time
import urllib.robotparser
from collections import Counter, defaultdict
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from . import db
from .common import DEFAULT_HEADERS, MARKETPLACE_ROOTS, identity
from . import signals as S
from .market import M, on_cctld

MAX_BYTES = 3_000_000
CHALLENGE = re.compile(r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|"
                       r"access denied|request could not be satisfied|pardon our interruption|"
                       r"captcha|are you a robot|incapsula|perimeterx|px-captcha|distil|ddos-guard|sucuri website firewall", re.I)

LISTING_HINT = re.compile(r"href=[\"'](?!data:)([^\"'#<>\s]{0,200}?(?:/products/?|/collections/all|/shop/?|/store/?|/categories/[^\"']+|/category/[^\"']+|/collections/[^\"']+|/c/[^\"']+|/-/c\d+|product-category/[^\"']+|/all-products|/catalog[^\"']*|/new-arrivals?|/offers)[^\"'#<>\s]{0,200})[\"']", re.I)


FOREIGN_GEO = M.FOREIGN_GEO
MKT_GEO = M.GEO
DEMO = re.compile(r"^(?:متجر تجريبي|متجر تجريبى|demo store|test store|my store|متجري|store name|اسم المتجر)$|متجر تجريبي|demo ?store|test ?store|متجر اختبار", re.I)


def bucket(host: str) -> str:
    """Hosts sharing one platform edge/rate limit are throttled together."""
    for suf in ("myshopify.com", "zid.store", "salla.sa"):
        if host == suf or host.endswith("." + suf):
            return suf
    return host


BUCKET_LIMITS = {"salla.sa": (4, 0.25), "api.salla.dev": (4, 0.25), "myshopify.com": (3, 0.6), "zid.store": (3, 0.4)}


class Fetcher:
    def __init__(self, concurrency: int, per_host: int):
        limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
        self.client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, limits=limits,
                                        timeout=httpx.Timeout(20.0, connect=10.0), verify=False, http2=False)
        self.global_sem = asyncio.Semaphore(concurrency)
        self.per_host = per_host
        self.host_sems: dict[str, asyncio.Semaphore] = {}
        self.host_last: dict[str, float] = defaultdict(float)
        self.host_gap: dict[str, float] = defaultdict(lambda: 0.5)
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.robots_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.stats = Counter()

    def _sem(self, host):
        if host not in self.host_sems:
            n, gap = BUCKET_LIMITS.get(host, (self.per_host, 0.5))
            self.host_gap[host] = gap
            self.host_sems[host] = asyncio.Semaphore(n)
        return self.host_sems[host]

    async def _raw_get(self, url, headers=None, read_limit=MAX_BYTES):
        async with self.client.stream("GET", url, headers=headers) as r:
            chunks, size = [], 0
            async for ch in r.aiter_bytes():
                chunks.append(ch)
                size += len(ch)
                if size >= read_limit:
                    break
            body = b"".join(chunks)
            if body[:2] == b"\x1f\x8b":
                import gzip
                try:
                    body = gzip.decompress(body)
                except Exception:
                    pass
            enc = r.encoding or "utf-8"
            try:
                text = body.decode(enc, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return r.status_code, str(r.url), text, dict(r.headers)

    async def allowed(self, url) -> bool:
        sp = urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        async with self.robots_lock[base]:
            if base not in self.robots:
                rp = None
                try:
                    st, _, txt, _ = await asyncio.wait_for(self._raw_get(base + "/robots.txt", read_limit=300_000), 15)
                    if st == 200 and "<html" not in txt[:500].lower():
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(txt.splitlines())
                except Exception:
                    rp = None
                self.robots[base] = rp
        rp = self.robots[base]
        if rp is None:
            return True
        try:
            return rp.can_fetch("*", url) or rp.can_fetch(DEFAULT_HEADERS["User-Agent"], url)
        except Exception:
            return True

    async def get(self, url, headers=None, tries=3, check_robots=True):
        """Return (status, final_url, text, headers, error)."""
        if check_robots and not await self.allowed(url):
            self.stats["robots_disallowed"] += 1
            return None, url, "", {}, "robots_disallowed"
        host = bucket(urlsplit(url).hostname or "")
        delay = 2.0
        last_err = None
        for attempt in range(tries):
            async with self.global_sem, self._sem(host):
                gap = time.monotonic() - self.host_last[host]
                want = self.host_gap[host]
                if gap < want:
                    await asyncio.sleep(want - gap)
                self.host_last[host] = time.monotonic()
                try:
                    st, final, text, hdrs = await asyncio.wait_for(self._raw_get(url, headers), 45)
                    self.stats["requests"] += 1
                    base_gap = BUCKET_LIMITS.get(host, (0, 0.5))[1]
                    if st == 429:
                        self.stats["http_429"] += 1
                        self.host_gap[host] = min(self.host_gap[host] * 1.5 + 0.2, 6.0)
                    elif self.host_gap[host] > base_gap:
                        self.host_gap[host] = max(base_gap, self.host_gap[host] * 0.97)
                    if st in (429, 502, 503, 504) and attempt < tries - 1 and not CHALLENGE.search(text[:5000]):
                        last_err = f"http_{st}"
                        if st == 429:
                            ra = hdrs.get("retry-after", "")
                            delay = max(delay, min(float(ra), 60) if ra.isdigit() else 15)
                    else:
                        return st, final, text, hdrs, None
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    msg = str(e)
                    if "Name or service not known" in msg or "nodename nor servname" in msg or "No address associated" in msg or "getaddrinfo failed" in msg:
                        return None, url, "", {}, "dns_not_resolved"
                    last_err = "connect_error"
                except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, asyncio.TimeoutError):
                    last_err = "timeout"
                    if attempt >= 1:
                        break
                except httpx.TooManyRedirects:
                    return None, url, "", {}, "too_many_redirects"
                except (httpx.HTTPError, UnicodeError, ValueError, OSError) as e:
                    last_err = f"http_error:{type(e).__name__}"
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, 16)
        self.stats["failed_fetch"] += 1
        return None, url, "", {}, last_err


def dns_ok(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except Exception:
        return False


async def salla_probe(f: Fetcher, html: str, page_url: str):
    m = re.search(r'"store":\{"id":(\d+)', html)
    if not m:
        return None
    sid = m.group(1)
    st, _, txt, _, err = await f.get("https://api.salla.dev/store/v1/products?per_page=30",
                                      headers={"Store-Identifier": sid, "Accept": "application/json", "Referer": page_url},
                                      check_robots=False)
    if st != 200:
        return {"store_id": sid, "error": err or f"http_{st}"}
    try:
        data = json.loads(txt).get("data") or []
    except ValueError:
        return {"store_id": sid, "error": "bad_json"}
    types = Counter((p.get("type") or "product") for p in data)
    statuses = Counter((p.get("status") or "") for p in data)
    cur = set(re.findall(r'"currency"\s*:\s*"([A-Z]{3})"', txt))
    sample = next((p.get("url") for p in data if p.get("url")), None)
    names = [p.get("name") or "" for p in data][:30]
    cats = [((p.get("category") or {}).get("name") or "") for p in data][:30]
    return {"store_id": sid, "n": len(data), "types": dict(types), "statuses": dict(statuses), "currency": sorted(cur),
            "sample_url": sample, "names": names, "cats": cats}


async def shopify_probe(f: Fetcher, base: str):
    out = {}
    st, _, txt, _, _ = await f.get(urljoin(base, "/meta.json"))
    if st == 200 and txt.strip().startswith("{"):
        try:
            mj = json.loads(txt)
            out.update({k: mj.get(k) for k in ("name", "currency", "country", "city", "province", "myshopify_domain", "domain")})
        except ValueError:
            pass
    st, _, txt, _, _ = await f.get(urljoin(base, "/products.json?limit=30"))
    if st == 200 and txt.strip().startswith("{"):
        try:
            prods = json.loads(txt).get("products") or []
            ship = sum(1 for p in prods if any(v.get("requires_shipping") for v in (p.get("variants") or [])))
            out.update({"n": len(prods), "requires_shipping": ship,
                        "names": [p.get("title") or "" for p in prods][:30],
                        "types": [p.get("product_type") or "" for p in prods][:30],
                        "sample_url": urljoin(base, "/products/" + prods[0]["handle"]) if prods else None})
        except (ValueError, KeyError):
            pass
    return out or None


async def woo_probe(f: Fetcher, base: str):
    st, _, txt, _, _ = await f.get(urljoin(base, "/wp-json/wc/store/v1/products?per_page=20"))
    if st == 200 and txt.strip().startswith("["):
        try:
            prods = json.loads(txt)
        except ValueError:
            return None
        cur = sorted({(p.get("prices") or {}).get("currency_code") for p in prods if p.get("prices")} - {None})
        names = [re.sub(r"\s+", " ", (p.get("name") or "")).strip() for p in prods]
        demo = sum(1 for n in names if WOO_DEMO.match(n))
        return {"n": len(prods), "demo": demo, "currency": cur, "names": names[:20],
                "sample_url": prods[0].get("permalink") if prods else None,
                "purchasable": sum(1 for p in prods if p.get("is_purchasable")),
                "service_links": sum(1 for p in prods if WOO_SERVICE_PATH.search(unquote(p.get("permalink") or "")))}
    return None


SITEMAP_PRODUCT = re.compile(r"<loc>\s*(https?://[^<\s]{0,300}?(?:/products?/[^</]+|/product-[^</\s]+|/catalog/product/[^</]+|/p/[^</]+|/p\d{5,}|-p-\d+|/dp/[^<]+|/item/[^</]+|/pd/[^<]+|/style/[a-z]{2}\d{4,}[^<\s]*)/?)\s*</loc>", re.I)
ZID_TEST_NAME = re.compile(r"^(?:prod(?:uct)?\s?\d*|(?:options? )?(?:prod )?test(?:\s*\d+|\s+(?:new )?product.*)?|test new.*|تجربة(?:\s*[\d٠-٩]+)?|منتج تجريبي.*|منتج (?:رقم )?[\d٠-٩]+|p)$", re.I)
ZID_RANDOM_SLUG = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{8,12}$")
ZID_DIGITAL_SLUG = re.compile(r"\bpdf\b|chat ?gpt|رقمي|إلكتروني|الكتروني|استشار|رحلة .{0,40}يوم|اشتراك", re.I)
WOO_SERVICE_PATH = re.compile(r"/(?:services?|الخدمة|الخدمات|خدمات|خدمة|courses?|الدورات|دورة|booking|حجز|packages?|الباقات|باقة)/", re.I)
WOO_DEMO = re.compile(r"^(?:wordpress pennant|hoodie(?: with (?:logo|zipper|pocket))?|beanie(?: with logo)?|album|single|t-shirt(?: with logo)?|cap|sunglasses|polo|belt|long sleeve tee|v-neck t-shirt|logo collection|levitating .*|lorem ipsum.*|sample product.*|product name|test product.*|منتج تجريبي.*|منتج \d+)$", re.I)


async def sitemap_probe(f: Fetcher, base: str):
    """Look for product URLs in the site's sitemap(s) (robots.txt Sitemap: lines or /sitemap.xml)."""
    if base.rstrip("/") not in f.robots:
        await f.allowed(base if base.endswith("/") else base + "/")
    rp = f.robots.get(base.rstrip("/"))
    maps = []
    try:
        maps = list((rp.site_maps() or []) if rp else [])
    except Exception:
        maps = []
    if not maps:
        maps = [urljoin(base, "/sitemap.xml"), urljoin(base, "/sitemap_index.xml")]
    seen = 0
    for sm in maps[:4]:
        st, _, txt, _, err = await f.get(sm, tries=2)
        seen += 1
        if st != 200 or "<loc>" not in (txt or ""):
            continue
        prods = SITEMAP_PRODUCT.findall(txt)
        children = re.findall(r"<sitemap>\s*<loc>\s*([^<]+)</loc>", txt, re.I)
        if prods and not children:
            return {"sitemap": sm, "product_urls": len(prods), "sample_url": prods[0].strip()}
        # "sitemaps" contains the substring "item"; only treat a child as a product sitemap when its name says product.
        named = [c for c in children if re.search(r"product", c, re.I)]
        # Magento-style indexes put product URLs in a later shard; try the last child as well as the first.
        prod_children = named or list(dict.fromkeys(children[:1] + children[-1:]))
        for ch in prod_children[:2]:
            st2, _, t2, _, _ = await f.get(ch.strip(), tries=2)
            if st2 == 200 and t2:
                named_product = bool(re.search(r"product", ch, re.I))
                locs = re.findall(r"<loc>\s*([^<\s]{1,500})\s*</loc>", t2) if named_product else SITEMAP_PRODUCT.findall(t2)
                if len(locs) >= 5:
                    return {"sitemap": ch.strip(), "product_urls": len(locs), "sample_url": locs[0].strip()}
    return None


def analyze(html: str, url: str):
    text = S.visible_text(html)
    title = S.title_of(html)
    desc = S.meta(html, "description") or S.meta(html, "og:description") or ""
    platform = S.detect_platform(html, url)
    types, ld_cur = S.jsonld_types(html)
    prod_links = set(m.group(0) for m in S.PRODUCT_LINK.finditer(html[:1_500_000]))
    return {
        "text": text, "title": title, "desc": desc, "platform": platform,
        "ld_types": types, "ld_currency": ld_cur,
        "n_product_links": len(prod_links),
        "add_to_cart": len(S.ADD_TO_CART.findall(html[:1_500_000])),
        "cart": len(S.CART_CHECKOUT.findall(html[:1_500_000])),
        "mkt_prices": len(S.PRICE_MKT.findall(text)),
        "any_prices": len(S.PRICE_ANY.findall(text)),
    }


def thin_page(html, a):
    return len(a["text"]) < 1200 and html.count("<script") >= 3


async def verify_one(f: Fetcher, cand: dict) -> dict:
    t0 = time.monotonic()
    key, url = cand["key"], cand["url"]
    res = {"key": key, "final_url": url, "final_key": key, "http_status": None, "store_name": "", "platform": cand.get("platform_hint") or "",
           "category": "", "subcategory": "", "market_score": 0, "market_evidence": "{}", "ecom_evidence": "{}",
           "product_evidence": "", "status": "unverified", "reason": "", "evidence_url": url, "verified_at": db.now(),
           "duplicate_of": None, "method": "http"}

    def done(status, reason):
        res["status"], res["reason"] = status, reason
        res["elapsed"] = round(time.monotonic() - t0, 2)
        res["verified_at"] = db.now()
        return res

    if cand.get("root_domain") in MARKETPLACE_ROOTS:
        return done("rejected", "excluded_marketplace: " + MARKETPLACE_ROOTS[cand["root_domain"]])

    if key.endswith(".myshopify.com"):
        st, mfinal, txt, _, _ = await f.get(urljoin(url, "/meta.json"), tries=2)
        if st == 200 and txt.strip().startswith("{"):
            try:
                mj = json.loads(txt)
            except ValueError:
                mj = {}
            country, currency = mj.get("country"), mj.get("currency")
            if country and currency and country != M.shopify_country and currency != M.currency:
                res.update({"http_status": st, "final_url": mfinal, "store_name": mj.get("name") or "", "platform": "shopify",
                            "market_evidence": json.dumps({"shopify_country": country, "shopify_currency": currency}), "evidence_url": mfinal})
                return done("rejected", f"non_market_shopify_store (meta.json country={country}, currency={currency})")
            dom = (mj.get("domain") or "").lower()
            if dom and not dom.endswith(".myshopify.com"):
                url = "https://" + dom + "/"

    st, final, html, hdrs, err = await f.get(url)
    if st is None and err == "connect_error" and url.startswith("https://"):
        st, final, html, hdrs, err = await f.get("http://" + url[8:], tries=2)
    if st is None and err != "robots_disallowed":
        host = urlsplit(url).hostname
        alt = None
        if host and not host.startswith("www.") and cand.get("platform_hint") is None:
            alt = url.replace("://", "://www.", 1)
        if alt and err != "timeout":
            st, final, html, hdrs, err2 = await f.get(alt, tries=2)
            err = err if st is None else None
    res["http_status"] = st
    res["final_url"] = final
    if st is None:
        if err == "dns_not_resolved":
            return done("rejected", "dns_not_resolved")
        if err == "robots_disallowed":
            return done("unverified", "robots_disallowed_homepage")
        return done("unverified", f"fetch_failed:{err}")

    fid = identity(final)
    if fid:
        res["final_key"] = fid["key"]
        if fid["root_domain"] in MARKETPLACE_ROOTS:
            return done("rejected", "redirects_to_marketplace:" + fid["root_domain"])
    else:
        res["final_key"] = None

    head = html[:8000]
    if st == 429:
        return done("unverified", "rate_limited_http_429 (retry later)")
    if st in (403, 401, 429, 503) or (st >= 400 and CHALLENGE.search(head)):
        if CHALLENGE.search(head) or st in (403, 429, 503):
            return done("unverified", f"blocked_or_challenge_http_{st}")
    if st == 404 or st == 410:
        return done("rejected", f"http_{st}")
    if st >= 400:
        return done("unverified", f"http_{st}")

    a = analyze(html, final)
    res["platform"] = a["platform"]
    res["store_name"] = S.store_name(html, cand["key"], urlsplit(final).hostname or "")
    short = len(a["text"]) < 4000
    head_text = (a["title"] + " " + a["text"][:4000])
    pk = (S.PARKED.search(head_text) if short else None) or (S.PARKED_TITLE.search(a["title"]) if len(a["text"]) < 3000 else None)
    if pk:
        return done("rejected", "parked_or_placeholder: " + pk.group(0)[:60])
    if re.search(r'<body[^>]*class="[^"]*\bconstruction\b', html[:20000]) or "ترقَّب إطلاق المتجر" in html[:20000] or "ترقب إطلاق المتجر" in html[:20000]:
        return done("rejected", "store_not_launched (platform 'coming soon' page)")
    if re.search(r'<body[^>]*class="[^"]*\bmaintenance\b', html[:20000]) or (len(a["text"]) < 6000 and S.CLOSED.search(head_text)) or "password-page" in html[:30000] and len(a["text"]) < 6000:
        m = S.CLOSED.search(head_text)
        return done("rejected", "store_closed_or_maintenance" + (": " + m.group(0) if m else ""))
    if re.search(r'window\.location(?:\.href)?\s*=\s*["\']/lander', html[:3000]):
        return done("rejected", "parked_or_placeholder: lander redirect")

    if DEMO.search(res["store_name"] or "") or re.match(r"salla\.sa/dev-", key) or re.search(r"demostore\.|demo-store|/dev-[a-z0-9]{10,}", final):
        return done("rejected", "demo_or_test_store")

    plat = a["platform"]
    probe = None
    base = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}/"
    try:
        if plat == "salla":
            probe = await salla_probe(f, html, final)
        elif plat == "shopify":
            probe = await shopify_probe(f, base)
        elif plat == "woocommerce":
            probe = await woo_probe(f, base)
    except Exception as e:  # probe failures must not kill the verification
        probe = {"error": type(e).__name__}

    if plat == "salla" and probe and str(probe.get("error", "")).startswith("http_429"):
        return done("unverified", "rate_limited_http_429 (salla api; retry later)")

    extra_html = ""
    extra_url = None
    need_listing = a["n_product_links"] < 3 and not (probe and probe.get("n"))
    if need_listing:
        cands = []
        for m in LISTING_HINT.finditer(html[:800_000]):
            href = m.group(1)
            full = urljoin(final, href)
            if urlsplit(full).netloc == urlsplit(final).netloc:
                cands.append(full)
        if plat == "zid" or ".zid.store" in final:
            cands.insert(0, urljoin(base, "/products/"))
        if cands:
            extra_url = cands[0]
            st2, fin2, h2, _, _ = await f.get(extra_url, tries=2)
            if st2 == 200:
                extra_html = h2
                extra_url = fin2
    if extra_html:
        a2 = analyze(extra_html, extra_url)
        for k in ("n_product_links", "add_to_cart", "cart", "mkt_prices", "any_prices"):
            a[k] = max(a[k], a2[k])
        a["ld_types"] |= a2["ld_types"]
        a["ld_currency"] |= a2["ld_currency"]

    ecom = {"platform": plat, "product_links": a["n_product_links"], "add_to_cart_markers": a["add_to_cart"],
            "cart_checkout_markers": a["cart"], "jsonld": sorted(a["ld_types"] & {"Product", "Offer", "AggregateOffer", "ItemList", "Store", "OnlineStore"})}
    product_names, api_currency = [], set(a["ld_currency"])
    physical = None
    if probe:
        ecom["probe"] = {k: v for k, v in probe.items() if k not in ("names", "cats")}
        product_names = (probe.get("names") or []) + (probe.get("cats") or [])
        if isinstance(probe.get("types"), list):
            product_names += probe["types"]
        pc = probe.get("currency")
        if isinstance(pc, list):
            api_currency |= set(pc)
        elif pc:
            api_currency.add(pc)
        if plat == "salla" and probe.get("types") is not None and isinstance(probe.get("types"), dict):
            t = probe["types"]
            phys = t.get("product", 0) + t.get("group_products", 0)
            digital = t.get("digital", 0) + t.get("codes", 0)
            service = t.get("service", 0) + t.get("booking", 0) + t.get("donating", 0)
            food = t.get("food", 0)
            physical = phys
            if probe.get("n", 0) == 0:
                return done("rejected", "no_products_listed (salla api returned 0 products)") | {"ecom_evidence": json.dumps(ecom, ensure_ascii=False)}
            if phys == 0 and food > 0 and food >= digital + service:
                return done("rejected", "restaurant_or_food_service (salla food-type products only)")
            if phys == 0 and digital > 0:
                return done("rejected", "digital_products_only (salla product types: %s)" % dict(t))
            if phys == 0 and service > 0:
                return done("rejected", "services_only (salla product types: %s)" % dict(t))
            if phys <= 10 and (service + digital) >= 2 * phys:
                return done("rejected", "mostly_services_or_digital (salla product types: %s)" % dict(t))
        if plat == "woocommerce" and probe.get("n"):
            if probe.get("demo", 0) >= max(2, probe["n"] // 2):
                return done("rejected", f"theme_demo_products_only (woocommerce sample data: {probe['demo']}/{probe['n']})")
            if probe.get("service_links", 0) >= max(2, probe["n"] // 2):
                return done("rejected", f"services_only (woocommerce service/booking permalinks: {probe['service_links']}/{probe['n']})")
            if probe.get("purchasable", 0) == 0:
                probe["n"] = 0
        if plat == "shopify" and probe.get("n"):
            physical = probe.get("requires_shipping", 0)
            if physical == 0:
                return done("rejected", "no_shippable_products (shopify products.json requires_shipping=0)")

    smp = None
    if not (probe and probe.get("n")) and a["n_product_links"] < 3 and "Product" not in a["ld_types"]:
        try:
            smp = await sitemap_probe(f, base)
        except Exception:
            smp = None
        if smp:
            ecom["sitemap_probe"] = smp

    pnames = [n for n in ((probe or {}).get("names") or []) if n]
    if plat == "zid" and not pnames:
        def zid_slugs(h):
            found = {unquote(m) for m in re.findall(r"/products/([^\"'?#/<>\s]{1,200})", h[:1_500_000])}
            return sorted(s for s in found if s.strip() and "\\" not in s)
        raw = zid_slugs(html + extra_html)
        if not raw and "/products/" not in (extra_url or ""):
            st3, _, h3, _, _ = await f.get(urljoin(base, "/products/"), tries=2)
            if st3 == 200:
                raw = zid_slugs(h3)
        slugs = [s.replace("-", " ") for s in raw]
        if slugs:
            if sum(1 for n in slugs if ZID_TEST_NAME.search(n)) >= max(1, len(slugs) // 2):
                return done("rejected", f"demo_or_test_store (zid placeholder product names: {', '.join(slugs[:3])})")
            ship = {"physical": 0, "non_physical": 0}
            sampled = []
            for s in raw[:4]:
                st4, _, h4, _, _ = await f.get(urljoin(base, "/products/" + s), tries=1)
                if st4 != 200:
                    continue
                t4 = S.meta(h4, "og:title")
                if t4:
                    sampled.append(t4)
                m = re.search(r'"requires_shipping"\s*:\s*(true|false)', h4)
                if m:
                    ship["physical" if m.group(1) == "true" else "non_physical"] += 1
            ecom["zid_shipping_sample"] = ship
            n_s = ship["physical"] + ship["non_physical"]
            if n_s and ship["physical"] == 0:
                return done("rejected", f"digital_or_services_only (zid requires_shipping=false for {n_s}/{n_s} sampled products)")
            if n_s >= 3 and ship["physical"] * 3 < n_s:
                return done("rejected", f"mostly_services_or_digital (zid requires_shipping: {ship})")
            physical = ship["physical"] if n_s else None
            svc = sum(1 for n in slugs if S.SERVICE_NAME.search(n) or S.DIGITAL.search(n) or ZID_DIGITAL_SLUG.search(n))
            if not n_s and len(slugs) <= 3 and svc:
                return done("unverified", f"few_products_service_or_digital_like (zid, {svc}/{len(slugs)}; manual review)")
            pnames = [s for s in slugs if not ZID_RANDOM_SLUG.search(s)] + sampled
            product_names = product_names + pnames[:60]
    svc_share = 0.0
    if pnames:
        hits = [n for n in pnames if S.SERVICE_NAME.search(n) or S.DIGITAL.search(n)]
        svc = len(hits)
        svc_share = svc / len(pnames)
        if (len(pnames) >= 3 and svc_share >= 0.5) or (len(pnames) < 3 and svc == len(pnames)):
            return done("rejected", f"mostly_services_or_digital_by_product_names ({svc}/{len(pnames)}; e.g. {' / '.join(h[:40] for h in hits[:3])})")
        if plat == "salla" and sum(1 for n in pnames if ZID_TEST_NAME.search(n.strip())) >= max(1, len(pnames) // 2):
            return done("rejected", f"demo_or_test_store (placeholder product names: {', '.join(pnames[:3])})")
        n_ch = sum(1 for n in pnames if S.CHARITY_PRODUCT.search(n))
        if n_ch >= max(1, len(pnames) // 3):
            return done("rejected", f"charity_or_donations (product names: {n_ch}/{len(pnames)})")
    if S.RESTAURANT_NAME.search(res.get("store_name") or ""):
        return done("rejected", "restaurant_or_food_service (store name: " + S.RESTAURANT_NAME.search(res["store_name"]).group(0) + ")")
    m_org = S.SERVICE_ORG.search(res.get("store_name") or "")
    if m_org and (physical is None or svc_share >= 0.25 or len(pnames) < 3):
        return done("unverified", f"service_style_store_name (manual review): {m_org.group(0)}; service-like products {svc_share:.0%}")

    product_ev = []
    if smp:
        product_ev.append(f"product URLs in sitemap ({smp.get('product_urls') or smp.get('product_sitemaps')})")
    if probe and probe.get("n"):
        product_ev.append(f"{probe.get('n')} products via {plat} storefront API")
    if a["n_product_links"] >= 2:
        product_ev.append(f"{a['n_product_links']} product links")
    if "Product" in a["ld_types"] or "Offer" in a["ld_types"]:
        product_ev.append("schema.org Product/Offer")
    if a["mkt_prices"] + a["any_prices"] >= 3:
        product_ev.append(f"{a['mkt_prices'] + a['any_prices']} price strings")
    purchase_ev = []
    if a["add_to_cart"]:
        purchase_ev.append("add-to-cart markers")
    if a["cart"] >= 2:
        purchase_ev.append("cart/checkout markers")
    if plat in ("salla", "zid", "shopify", "woocommerce", "magento", "salesforce-commerce", "opencart", "prestashop", "bigcommerce", "expandcart", "youcan", "matjrah", "sap-hybris", "vtex", "ecwid") :
        purchase_ev.append(f"{plat} commerce platform (cart/checkout built-in)")
    ecom["product_evidence"] = product_ev
    ecom["purchase_evidence"] = purchase_ev
    res["ecom_evidence"] = json.dumps(ecom, ensure_ascii=False)
    res["product_evidence"] = (probe or {}).get("sample_url") or (smp or {}).get("sample_url") or (extra_url if extra_html else "") or ""

    score, sev = S.market_signals(html + extra_html[:200000], a["text"], url, final, plat, api_currency)
    if probe and plat == "shopify" and probe.get("country"):
        if probe["country"] == M.shopify_country:
            sev["shopify_shop_country"] = M.shopify_country
            score += 3
        else:
            sev["shopify_shop_country"] = probe["country"]
            score -= 1.5
    if probe and plat == "woocommerce" and probe.get("currency") and M.currency not in probe["currency"]:
        sev["woo_store_currency"] = probe["currency"]
        score -= 3
    if probe and plat == "shopify" and probe.get("currency") == M.currency:
        sev["shopify_base_currency"] = M.currency
    res["market_score"] = round(score, 2)
    res["market_evidence"] = json.dumps(sev, ensure_ascii=False)

    cat_texts = [a["title"] + " " + res["store_name"], a["desc"], S.meta(html, "keywords") or "", " ".join(product_names), a["text"][:6000]]
    cat, sub = S.classify_category(cat_texts, [6, 4, 2, 2, 1])
    res["cat_text"] = "\x1f".join(t[:3000] for t in cat_texts)
    res["category"], res["subcategory"] = cat, sub

    has_product = bool(product_ev)
    has_purchase = bool(purchase_ev)
    if not has_product and not has_purchase:
        if thin_page(html, a):
            return done("unverified", "js_rendered_or_thin_page (no ecommerce evidence in static HTML)")
        return done("rejected", "no_ecommerce_evidence")
    if not has_product or not has_purchase:
        if thin_page(html, a):
            return done("unverified", "partial_ecommerce_evidence_js_page: " + ",".join(product_ev + purchase_ev))
        if has_product and not has_purchase and (a["mkt_prices"] >= 3 or ("schema.org Product/Offer" in product_ev and a["mkt_prices"] >= 1)):
            purchase_ev.append("purchasable listings (product pages/offers with prices)")
        else:
            return done("unverified" if (has_product or a["cart"]) else "rejected",
                        "insufficient_ecommerce_evidence: " + (",".join(product_ev + purchase_ev) or "none"))

    blob = (a["title"] + " " + a["desc"] + " " + a["text"][:20000] + " " + " ".join(product_names))
    n_dig = len(S.DIGITAL.findall(blob))
    n_srv = len(S.SERVICE.findall(a["title"] + " " + a["desc"] + " " + a["text"][:8000]))
    n_rest = len(S.RESTAURANT.findall(a["title"] + " " + a["desc"] + " " + a["text"][:8000]))
    weak_products = a["add_to_cart"] < 2 and a["n_product_links"] < 10 and not (probe and probe.get("n"))
    if physical is None and weak_products:
        if n_dig >= 6 and cat in ("General / Unclassified", "Gaming", "Books & Stationery"):
            return done("rejected", f"likely_digital_only ({n_dig} digital-goods markers)")
        if n_rest >= 6 and cat not in ("Chocolates & Sweets", "Coffee, Tea & Dates", "Grocery & Food", "Kitchenware & Tableware", "Home Appliances"):
            return done("rejected", f"likely_restaurant_or_food_service ({n_rest} markers)")
        if n_srv >= 6 and not a["add_to_cart"]:
            return done("rejected", f"likely_services ({n_srv} service markers)")

    name_title = (res["store_name"] or "") + " " + a["title"]
    n_char = len(S.CHARITY.findall(name_title + " " + a["desc"] + " " + a["text"][:8000]))
    if S.CHARITY.search(name_title) or n_char >= 5:
        if not (physical and physical >= 3 and n_char < 5):
            return done("rejected", f"charity_or_donations ({n_char} markers)")
    if physical is None and S.ORG.search(res["store_name"] or ""):
        return done("unverified", "organization_site_with_shop_features (manual review): " + S.ORG.search(res["store_name"]).group(0))
    if plat in ("custom/unknown", "wix", "odoo", "nopcommerce", "wuilt", "woocommerce") and not (probe and probe.get("n")):
        strong_prod = a["n_product_links"] >= 3 or "Product" in a["ld_types"] or a["mkt_prices"] >= 3 or bool(smp and smp.get("product_urls", 0) >= 5)
        if not (a["add_to_cart"] >= 1 and strong_prod):
            return done("unverified", "weak_ecommerce_evidence_custom_platform: " + ",".join(product_ev + purchase_ev))

    strong = any(k in sev for k in ("cctld", "market_locale", "currency_code", "local_prices", "local_phone", "vat_number", "shopify_shop_country"))
    if sev.get("shopify_shop_country") not in (None, M.shopify_country) and not any(k in sev for k in ("cctld", "market_locale", "vat_number")):
        strong = "local_phone" in sev and ("local_prices" in sev or "currency_code" in sev)
    res["ecom_evidence"] = json.dumps(ecom, ensure_ascii=False)
    if FOREIGN_GEO.search(final) and not MKT_GEO.search(final) and not any(k in sev for k in ("currency_code", "local_prices", "cctld", "vat_number", "shopify_shop_country")):
        return done("rejected", "redirects_to_non_market_storefront (geo/locale): " + final[:80])
    if score >= 4 and strong:
        res["status"] = "verified"
        note = []
        if n_dig >= 3:
            note.append(f"also lists some digital goods ({n_dig} markers)")
        res["reason"] = "; ".join(["ecommerce+market evidence ok"] + note)
        res["elapsed"] = round(time.monotonic() - t0, 2)
        res["verified_at"] = db.now()
        return res
    if score >= 2 and strong:
        return done("unverified", f"weak_market_signals (score={score:.1f})")
    if "other_currency" in sev or sev.get("shopify_shop_country") not in (None, M.shopify_country):
        return done("rejected", f"not_market_relevant (score={score:.1f}, {sev.get('other_currency') or sev.get('shopify_shop_country')})")
    return done("rejected" if score < 1 else "unverified", f"insufficient_market_signals (score={score:.1f})")


COLS = ["key", "final_url", "final_key", "http_status", "store_name", "platform", "category", "subcategory", "market_score",
        "market_evidence", "ecom_evidence", "product_evidence", "status", "reason", "evidence_url", "verified_at", "duplicate_of", "method", "elapsed", "cat_text"]


def save(con, res):
    res.setdefault("elapsed", 0)
    vals = [res.get(c) for c in COLS]
    for _ in range(20):
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(f"INSERT OR REPLACE INTO verifications({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})", vals)
            con.execute("UPDATE candidates SET status=?, attempts=attempts+1, last_attempt=? WHERE key=?", (res["status"], db.now(), res["key"]))
            con.execute("COMMIT")
            return
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            time.sleep(1 + random.random())


def claim(con, n, worker, where_extra=""):
    for _ in range(20):
        try:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                f"SELECT key,url,root_domain,platform_hint,priority FROM candidates WHERE status='pending' {where_extra} ORDER BY priority DESC, (rowid * 2654435761) % 1000003 LIMIT ?", (n,)
            ).fetchall()
            con.executemany("UPDATE candidates SET status='in_progress', last_attempt=? WHERE key=?", [(db.now(), r[0]) for r in rows])
            con.execute("COMMIT")
            return [dict(zip(("key", "url", "root_domain", "platform_hint", "priority"), r)) for r in rows]
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            time.sleep(1 + random.random())
    return []


async def main(concurrency, per_host, worker, idle_exit, where_extra, reset_stale):
    import warnings
    warnings.filterwarnings("ignore")
    con = db.connect()
    if reset_stale:
        con.execute("UPDATE candidates SET status='pending' WHERE status='in_progress'")
    f = Fetcher(concurrency, per_host)
    queue: asyncio.Queue = asyncio.Queue(maxsize=concurrency * 3)
    stats = Counter()
    t_start = time.time()
    idle_since = [None]

    async def producer():
        while True:
            if queue.qsize() < concurrency * 2:
                batch = claim(con, concurrency * 2, worker, where_extra)
                if not batch:
                    if idle_since[0] is None:
                        idle_since[0] = time.time()
                    if idle_exit and time.time() - idle_since[0] > idle_exit:
                        for _ in range(concurrency):
                            await queue.put(None)
                        return
                    await asyncio.sleep(10)
                    continue
                idle_since[0] = None
                for c in batch:
                    await queue.put(c)
            else:
                await asyncio.sleep(0.5)

    async def consumer(i):
        while True:
            c = await queue.get()
            if c is None:
                return
            try:
                res = await asyncio.wait_for(verify_one(f, c), 240)
            except asyncio.TimeoutError:
                res = {"key": c["key"], "final_url": c["url"], "status": "unverified", "reason": "verification_timeout", "verified_at": db.now(), "evidence_url": c["url"]}
            except Exception as e:
                res = {"key": c["key"], "final_url": c["url"], "status": "unverified", "reason": f"verifier_error:{type(e).__name__}:{str(e)[:80]}", "verified_at": db.now(), "evidence_url": c["url"]}
            save(con, res)
            stats[res["status"]] += 1
            stats["total"] += 1

    async def reporter():
        while True:
            await asyncio.sleep(60)
            el = time.time() - t_start
            info = dict(stats) | {"per_min": round(stats["total"] / (el / 60), 1), "requests": f.stats["requests"], "http_429": f.stats["http_429"],
                                  "salla_gap": round(f.host_gap.get("salla.sa", 0), 2)}
            print(f"[verify:{worker}] {info}", flush=True)
            db.heartbeat(con, f"verify:{worker}", "code-worker(asyncio)", concurrency, info)

    db.heartbeat(con, f"verify:{worker}", "code-worker(asyncio)", concurrency, {})
    rep = asyncio.create_task(reporter())
    await asyncio.gather(producer(), *[consumer(i) for i in range(concurrency)])
    rep.cancel()
    print(f"[verify:{worker}] finished {dict(stats)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=48)
    ap.add_argument("--per-host", type=int, default=2)
    ap.add_argument("--worker", default=f"w{os.getpid()}")
    ap.add_argument("--idle-exit", type=int, default=0, help="exit after N seconds with empty queue (0=never)")
    ap.add_argument("--where", default="", help="extra SQL filter on candidates, e.g. \"AND platform_hint='salla'\"")
    ap.add_argument("--reset-stale", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.concurrency, a.per_host, a.worker, a.idle_exit, a.where, a.reset_stale))
